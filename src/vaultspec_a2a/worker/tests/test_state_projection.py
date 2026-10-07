"""State-normalization contract coverage for execution-state projection."""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START
from langgraph.types import Command, Interrupt, PregelTask, interrupt
from pydantic import BaseModel, ConfigDict

from ...providers import ProviderCondition
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...thread.action_receipts import GraphActionReceipt
from ...thread.cancellation_evidence import CancellationEvidence
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.failure_evidence import GraphFailureEvidence, failure_detail_fingerprint
from ..ipc import WorkerBridge
from ..state_projection import (
    ResumeAdmission,
    ResumeRefusal,
    ResumeRefusalCause,
    StateProjector,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig


class _AskState(TypedDict, total=False):
    answer: str


class _StateNormalizationFixture(BaseModel):
    """Typed fixture for the normalizer's explicit snapshot field contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    next: tuple[str, ...]
    interrupts: tuple[Interrupt, ...]
    tasks: tuple[PregelTask, ...]
    config: dict[str, object]
    parent_config: dict[str, object] | None


def test_normalize_execution_state_projects_interrupt_contract() -> None:
    """Normalize real LangGraph interrupt and task values without graph persistence."""
    approval_interrupt = Interrupt(
        value={"type": "approval", "request_id": "request-7"},
        id="interrupt-7",
    )
    state = _StateNormalizationFixture(
        next=("await_approval",),
        interrupts=(approval_interrupt,),
        tasks=(
            PregelTask(
                id="task-7",
                name="await_approval",
                path=("__pregel_pull", "await_approval"),
                interrupts=(approval_interrupt,),
            ),
        ),
        config={"configurable": {"checkpoint_id": "checkpoint-7"}},
        parent_config={"configurable": {"checkpoint_id": "checkpoint-6"}},
    )

    payload = StateProjector.normalize_execution_state(state)

    assert payload.checkpoint_id == "checkpoint-7"
    assert payload.parent_checkpoint_id == "checkpoint-6"
    assert payload.next_nodes == ["await_approval"]
    assert payload.interrupt_count == 1
    assert payload.task_count == 1
    task = payload.tasks[0]
    assert task.task_id == "task-7"
    assert task.name == "await_approval"
    assert task.path == ["__pregel_pull", "await_approval"]
    assert task.interrupt_ids == ["interrupt-7"]
    assert task.interrupt_types == ["approval"]
    assert not task.has_error
    assert not task.has_nested_state
    assert not task.has_result


def _resume_receipt(thread_id: str) -> GraphActionReceipt:
    """The journal identity a dispatched resume carries into the preflight."""
    return GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=thread_id,
        action_id="answer-action",
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        payload_fingerprint=f"sha256:{'1' * 64}",
        dispatch_id="answer-dispatch",
        run_revision=1,
        writer_generation=2,
    )


async def _held_writes(saver: InMemorySaver, config: RunnableConfig) -> tuple[Any, ...]:
    """The writes the store holds against the thread's latest checkpoint."""
    stored = await saver.aget_tuple(config)
    assert stored is not None
    return tuple(stored.pending_writes or ())


@pytest.mark.asyncio
async def test_a_node_that_asks_again_is_still_the_next_node() -> None:
    """A node re-parked by an answer that did not settle it stays the position.

    LangGraph drops such a task from ``next`` because it already holds a
    resume write; the projection must still report the node the run is parked
    at, or a gate awaiting a decision reads as merely running. The held writes
    are what keep the two apart: a task that consumed an answer and asked
    again produced no output, so it is still waiting.
    """

    def ask_until_settled(state: _AskState) -> _AskState:
        answer = interrupt({"type": "approval", "request_id": "request-9"})
        while answer != "settled":
            answer = interrupt({"type": "approval", "request_id": "request-9"})
        return {"answer": answer}

    builder = new_state_graph(_AskState)
    add_test_node(builder, "ask_until_settled", ask_until_settled)
    builder.add_edge(START, "ask_until_settled")
    builder.add_edge("ask_until_settled", END)
    saver = InMemorySaver()
    graph = compile_test_graph(builder, checkpointer=saver)
    config: RunnableConfig = {"configurable": {"thread_id": "ask-again"}}

    await graph.ainvoke({}, config=config)
    await graph.ainvoke(Command(resume="unrelated"), config=config)
    state = await graph.aget_state(config)
    assert state.next == ()

    payload = StateProjector.normalize_execution_state(
        state, await _held_writes(saver, config)
    )

    assert payload.next_nodes == ["ask_until_settled"]
    assert payload.interrupt_count == 1

    await graph.ainvoke(Command(resume="settled"), config=config)
    settled = StateProjector.normalize_execution_state(
        await graph.aget_state(config), await _held_writes(saver, config)
    )
    assert settled.next_nodes == []


class _FanOutState(TypedDict, total=False):
    answers: Annotated[list[str], operator.add]


def _fan_out_graph(saver: InMemorySaver) -> Any:
    """Two branches that each stop to ask their own question."""

    def gate(request_id: str) -> Any:
        def node(state: _FanOutState) -> _FanOutState:
            del state
            answer = interrupt({"type": "approval", "request_id": request_id})
            return {"answers": [f"{request_id}:{answer}"]}

        return node

    builder = new_state_graph(_FanOutState)
    add_test_node(builder, "alpha", gate("request-alpha"))
    add_test_node(builder, "beta", gate("request-beta"))
    builder.add_edge(START, "alpha")
    builder.add_edge(START, "beta")
    builder.add_edge("alpha", END)
    builder.add_edge("beta", END)
    return compile_test_graph(builder, checkpointer=saver)


async def _answer(graph: Any, config: RunnableConfig, request_id: str) -> None:
    """Answer one of the pending questions, addressed to its own interrupt."""
    state = await graph.aget_state(config)
    target = next(
        parked
        for parked in state.interrupts
        if parked.value["request_id"] == request_id
    )
    await graph.ainvoke(Command(resume={target.id: "approved"}), config=config)


@pytest.mark.asyncio
async def test_only_the_branch_still_asking_is_disclosed() -> None:
    """An answered fan-out branch stops being one of the run's open questions.

    LangGraph leaves the answered branch's interrupt in the checkpoint until
    the superstep commits, and the superstep cannot commit while the other
    branch is parked, so the snapshot lists both questions indefinitely. A
    client reloading the run re-rendered one it had already answered.
    """
    saver = InMemorySaver()
    graph = _fan_out_graph(saver)
    config: RunnableConfig = {"configurable": {"thread_id": "fan-out-disclosure"}}

    await graph.ainvoke({"answers": []}, config=config)
    both = StateProjector.normalize_execution_state(
        await graph.aget_state(config), await _held_writes(saver, config)
    )
    assert both.interrupt_count == 2

    await _answer(graph, config, "request-alpha")
    state = await graph.aget_state(config)
    # The snapshot has not changed its mind: this is what the projection reads past.
    assert len(state.interrupts) == 2

    remaining = StateProjector.normalize_execution_state(
        state, await _held_writes(saver, config)
    )

    assert remaining.interrupt_count == 1
    asking = [task for task in remaining.tasks if task.interrupt_ids]
    assert [task.name for task in asking] == ["beta"]
    # The answered branch is still a pending task - its output has not been
    # committed either - but it is no longer asking anything.
    assert {task.name for task in remaining.tasks} == {"alpha", "beta"}
    assert remaining.next_nodes == ["beta"]


@pytest.mark.asyncio
async def test_a_resume_naming_an_answered_branch_is_refused() -> None:
    """The preflight admits an answer only against a question still open.

    Admitting a redelivery of the answered request spends it on a task that
    has already consumed one: the node replays its stored answer, finishes,
    and the second answer is never read - so the client's action does nothing
    and the run stays parked on the other branch.
    """
    saver = InMemorySaver()
    graph = _fan_out_graph(saver)
    thread_id = "fan-out-preflight"
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    projector = StateProjector(
        checkpointer=saver,
        bridge=WorkerBridge(api_url="http://control:8000", worker_id="preflight-test"),
    )
    receipt = _resume_receipt(thread_id)

    await graph.ainvoke({"answers": []}, config=config)
    await _answer(graph, config, "request-alpha")

    answered_again = await projector.pre_flight_resume(
        graph,
        cast("dict[str, Any]", config),
        receipt,
        resume_value={"request_id": "request-alpha", "verdict": "approved"},
        timeout_seconds=10.0,
    )

    assert isinstance(answered_again, ResumeRefusal)
    assert answered_again.cause is ResumeRefusalCause.REQUEST_NOT_PENDING
    assert answered_again.pending_request_ids == ("request-beta",)

    still_open = await projector.pre_flight_resume(
        graph,
        cast("dict[str, Any]", config),
        receipt,
        resume_value={"request_id": "request-beta", "verdict": "approved"},
        timeout_seconds=10.0,
    )

    # One question left, so the answer needs no address - and LangGraph takes
    # a bare value here, which is the reading this admission has to match.
    assert isinstance(still_open, ResumeAdmission)
    assert still_open.interrupt_id is None
    settled = await graph.ainvoke(Command(resume="approved"), config=config)
    assert sorted(settled["answers"]) == [
        "request-alpha:approved",
        "request-beta:approved",
    ]


def test_normalize_state_keeps_missing_configurable_metadata_optional() -> None:
    """A checkpoint without configurable metadata remains a valid empty projection."""
    state = _StateNormalizationFixture(
        next=(),
        interrupts=(),
        tasks=(),
        config={},
        parent_config=None,
    )

    payload = StateProjector.normalize_execution_state(state)

    assert payload.checkpoint_id is None
    assert payload.parent_checkpoint_id is None


def test_normalize_state_raises_for_malformed_configurable_metadata() -> None:
    """A present non-mapping configurable value raises for emitter degradation."""
    state = _StateNormalizationFixture(
        next=(),
        interrupts=(),
        tasks=(),
        config={"configurable": []},
        parent_config=None,
    )

    with pytest.raises(TypeError, match="configurable metadata"):
        StateProjector.normalize_execution_state(state)


def _relayed_terminal_projector(
    relayed: list[dict[str, Any]],
) -> StateProjector:
    """Build a projector whose bridge posts to a real in-process gateway.

    The terminal event is what the gateway persists, so the assertions below are
    on the JSON that actually crossed the worker-to-gateway hop - a real
    ``WorkerBridge`` serialising over real HTTP into a real ASGI app - rather
    than on a dictionary handed straight back to the test.
    """
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        body = await request.json()
        relayed.extend(body["events"])
        return Response(content='{"status":"ok"}', media_type="application/json")

    # Dispatched by the ASGI app at request time via the decorator registration
    # above, not by direct call — referenced here only so static analysis sees
    # it as used.
    _ = _batch

    bridge = WorkerBridge(api_url="http://control:8000", worker_id="projector-test")
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://control:8000",
    )
    return StateProjector(checkpointer=InMemorySaver(), bridge=bridge)


def _failure_evidence(
    thread_id: str, detail: str, condition: ProviderCondition
) -> GraphFailureEvidence:
    return GraphFailureEvidence(
        schema_version="graph-failure-v1",
        action=GraphActionReceipt(
            schema_version="graph-action-v1",
            thread_id=thread_id,
            action_id="accepted-action",
            action_type=ControlActionType.INGEST,
            payload_fingerprint=f"sha256:{'0' * 64}",
            dispatch_id="accepted-dispatch",
            run_revision=0,
            writer_generation=1,
        ),
        outcome="failed",
        detail_fingerprint=failure_detail_fingerprint(detail),
        provider_condition=condition.value,
    )


class TestTerminalConditionCarriage:
    """The condition rides the terminal event the gateway persists.

    The error frame that also carries it is droppable, so this payload is the
    only channel a reloading client can recover the condition from.
    """

    @pytest.mark.asyncio
    async def test_a_failed_terminal_carries_the_condition_it_was_given(self) -> None:
        """A classified failure reports the lane's own verdict, not the floor."""
        relayed: list[dict[str, Any]] = []
        projector = _relayed_terminal_projector(relayed)
        detail = "the provider refused for rate"

        await projector.emit_terminal_status(
            "thread-throttled",
            ThreadStatus.FAILED,
            error_detail=detail,
            provider_condition=ProviderCondition.THROTTLED,
            evidence=_failure_evidence(
                "thread-throttled", detail, ProviderCondition.THROTTLED
            ),
        )

        assert len(relayed) == 1
        payload = relayed[0]["payload"]
        assert payload["status"] == ThreadStatus.FAILED.value
        assert payload["provider_condition"] == ProviderCondition.THROTTLED.value
        assert payload["error_detail"] == "the provider refused for rate"

    @pytest.mark.asyncio
    async def test_a_failed_terminal_never_leaves_the_condition_absent(self) -> None:
        """The floor is applied here so no call site can omit the field.

        Every pre-run refusal in the executor fails a run without observing a
        provider. Depending on each of them to remember a condition is how the
        blank terminal this campaign removes came about in the first place.
        """
        relayed: list[dict[str, Any]] = []
        projector = _relayed_terminal_projector(relayed)
        detail = "no graph to run"

        await projector.emit_terminal_status(
            "thread-unclassified",
            ThreadStatus.FAILED,
            error_detail=detail,
            evidence=_failure_evidence(
                "thread-unclassified", detail, ProviderCondition.UNKNOWN
            ),
        )

        assert len(relayed) == 1
        assert (
            relayed[0]["payload"]["provider_condition"]
            == ProviderCondition.UNKNOWN.value
        )

    @pytest.mark.asyncio
    async def test_a_completed_terminal_carries_no_condition_at_all(self) -> None:
        """A run that did not fail has no provider failure to classify.

        Stamping the unknown member on a successful run would read as a
        provider failure nobody observed.
        """
        relayed: list[dict[str, Any]] = []
        projector = _relayed_terminal_projector(relayed)

        await projector.emit_terminal_status("thread-ok", ThreadStatus.COMPLETED)

        assert len(relayed) == 1
        assert "provider_condition" not in relayed[0]["payload"]

    @pytest.mark.asyncio
    async def test_cancelled_terminal_carries_exact_cancellation_evidence(self) -> None:
        relayed: list[dict[str, Any]] = []
        projector = _relayed_terminal_projector(relayed)
        evidence = CancellationEvidence(
            schema_version="cancellation-evidence-v1",
            dispatch_id="cancel-dispatch",
            outcome="ceased",
        )

        await projector.emit_terminal_status(
            "thread-cancelled",
            ThreadStatus.CANCELLED,
            evidence=evidence,
        )

        assert len(relayed) == 1
        assert relayed[0]["payload"]["cancellation_evidence"] == (
            evidence.model_dump(mode="json")
        )

    @pytest.mark.asyncio
    async def test_non_cancelled_terminal_refuses_cancellation_evidence(self) -> None:
        projector = _relayed_terminal_projector([])
        evidence = CancellationEvidence(
            schema_version="cancellation-evidence-v1",
            dispatch_id="cancel-dispatch",
            outcome="no_active_work",
        )

        with pytest.raises(ValueError, match="requires a cancelled terminal"):
            await projector.emit_terminal_status(
                "thread-completed",
                ThreadStatus.COMPLETED,
                evidence=evidence,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("thread_id", "detail", "condition"),
        (
            ("another-thread", "failure detail", ProviderCondition.THROTTLED),
            ("thread-failed", "different detail", ProviderCondition.THROTTLED),
            ("thread-failed", "failure detail", ProviderCondition.UNKNOWN),
        ),
    )
    async def test_failed_terminal_refuses_mismatched_evidence(
        self, thread_id: str, detail: str, condition: ProviderCondition
    ) -> None:
        projector = _relayed_terminal_projector([])
        evidence = _failure_evidence(
            "thread-failed", "failure detail", ProviderCondition.THROTTLED
        )
        with pytest.raises(ValueError, match="does not match terminal payload"):
            await projector.emit_terminal_status(
                thread_id,
                ThreadStatus.FAILED,
                error_detail=detail,
                provider_condition=condition,
                evidence=evidence,
            )
