"""A parked run survives every resume delivered against its checkpoint.

Real executors resume real graphs over a real ``AsyncSqliteSaver`` and relay
through a real in-process gateway. A resume carries its action receipt into
the graph as an input write, and LangGraph holds every input write against the
checkpoint the run is parked on until a superstep consumes it. Two approvals in
one worker turn, and one resume delivered twice, therefore both put two
receipts on the same channel in the same step. Neither may fail the run, and
neither may leave the thread's durable state unreadable.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.accepted_input import freeze_accepted_input
from ...graph.nodes._worker_permissions import (
    permission_callback_for,
    recorded_permission_answers,
)
from ...providers.team_selection import model_assignment_digest
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...thread.action_receipts import (
    GraphActionReceipt,
    control_action_payload_fingerprint,
)
from ...thread.enums import ControlActionType
from ...thread.resume_values import permission_resume_value
from .._dispatch_receipts import DispatchReceiptReporter
from ..executor import Executor
from .test_executor import (
    _current_ingest_dispatch,
    _make_bridge,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...ipc.schemas import DispatchRequest
    from ..graph_lifecycle import RegisteredCompiledGraph

_OPTIONS: list[dict[str, Any]] = [
    {"optionId": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"optionId": "reject_once", "name": "Reject once", "kind": "reject_once"},
]


def _bound_permission_callback(state: Any) -> Any:
    """The callback the worker node binds, over this run's recorded answers.

    The test graphs bind it exactly as the production node does, so what they
    exercise is the real request-id lookup rather than a callback that never
    sees the answers the executor recorded.
    """
    return permission_callback_for(recorded_permission_answers(state))


def _install_two_permission_graph(
    executor: Executor, request: DispatchRequest, answered: dict[str, str]
) -> RegisteredCompiledGraph:
    """Compile a real graph whose single node asks for two tool permissions.

    The node calls the production permission callback, so the interrupt
    payloads, their request ids and the option validation are the ones a
    worker turn really raises. Answers are recorded per call rather than
    appended, because an interrupted task replays its node body from the top
    on every resume and an append would record the replay rather than the
    answers the turn obtained.
    """

    async def worker_node(state: Any) -> dict[str, Any]:
        answered["Edit"] = await _bound_permission_callback(state)(
            "Edit", {"path": "a.py"}, _OPTIONS
        )
        answered["Bash"] = await _bound_permission_callback(state)(
            "Bash", {"command": "pytest"}, _OPTIONS
        )
        return {"messages": [AIMessage(content="done")], "next": "FINISH"}

    builder = new_state_graph()
    add_test_node(builder, "worker", worker_node)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    graph: RegisteredCompiledGraph = compile_test_graph(
        builder, checkpointer=executor._checkpointer
    )
    executor.register_compiled_graph(
        request.thread_id,
        (
            request.require_graph_definition().team_id,
            request.workspace_root,
            request.autonomous,
            model_assignment_digest(request.model_assignment),
            request.require_graph_definition().digest(),
        ),
        graph,
    )
    return graph


def _resume_dispatch(
    ingest: DispatchRequest,
    *,
    ordinal: int,
    resume_value: object,
) -> DispatchRequest:
    """One accepted resume action, identified as the gateway identifies it."""
    request = ingest.model_copy(
        update={
            "action": "resume",
            "dispatch_id": f"{ingest.thread_id}-resume-{ordinal}",
            "content": None,
            "option_id": resume_value,
            "graph_action_receipt": None,
        }
    )
    accepted = freeze_accepted_input(request, intent={"option_id": resume_value})
    receipt = GraphActionReceipt(
        schema_version="graph-action-v1",
        thread_id=request.thread_id,
        action_id=f"{request.thread_id}-resume-action-{ordinal}",
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        payload_fingerprint=control_action_payload_fingerprint(accepted),
        dispatch_id=request.dispatch_id,
        run_revision=ordinal,
        writer_generation=ordinal + 1,
    )
    return request.model_copy(update={"graph_action_receipt": receipt})


def _answer_for(parked: Any) -> object:
    """The typed answer a client sends for the request now on display."""
    payload = parked.value
    return permission_resume_value(
        "permission_request",
        "allow_once",
        None,
        request_id=payload["request_id"],
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_two_approvals_in_one_worker_turn_both_apply(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A turn needing a second tool approval finishes it."""
    thread_id = "resume-two-approvals"
    answered: dict[str, str] = {}
    bridge = _make_bridge()
    executor = Executor(checkpointer=checkpointer, bridge=bridge)
    try:
        ingest = _current_ingest_dispatch(thread_id)
        graph = _install_two_permission_graph(executor, ingest, answered)
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        await executor.handle_dispatch(ingest)
        first_park = (await graph.aget_state(config)).interrupts
        assert [park.value["tool_name"] for park in first_park] == ["Edit"]

        await executor.handle_dispatch(
            _resume_dispatch(ingest, ordinal=1, resume_value=_answer_for(first_park[0]))
        )
        second_park = (await graph.aget_state(config)).interrupts
        assert [park.value["tool_name"] for park in second_park] == ["Bash"]

        second = _resume_dispatch(
            ingest, ordinal=2, resume_value=_answer_for(second_park[0])
        )
        await executor.handle_dispatch(second)

        # The run finished, so both calls were answered and neither
        # resume was refused by the channel the receipts land on.
        final = await graph.aget_state(config)
        assert final.next == ()
        assert final.interrupts == ()
        assert answered == {"Edit": "allow_once", "Bash": "allow_once"}

        # The checkpoint names the action that last reached the graph,
        # and holds an incorporation receipt for every action that did.
        durable = await checkpointer.aget_tuple(config)
        assert durable is not None
        values = durable.checkpoint["channel_values"]
        receipt = second.require_graph_action_receipt()
        assert values["active_graph_action_receipt"] == receipt.model_dump(mode="json")
        assert set(values["graph_action_receipts"]) == {
            ingest.dispatch_id,
            f"{thread_id}-resume-1",
            f"{thread_id}-resume-2",
        }
    finally:
        await bridge.close()
        await executor.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_a_resume_that_only_asks_again_reports_its_application(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """An answer that parks the turn on its next question still lands.

    The resume that settles the first approval leaves the run parked on the
    second, so no superstep commits and the receipt stays a write held
    against the parked checkpoint. The gateway settles the action only on
    the application report, so a reporter reading committed channels alone
    never sends one, and recovery later redelivers an answer the run already
    consumed.
    """
    thread_id = "resume-asks-again-receipt"
    answered: dict[str, str] = {}
    relayed: list[dict[str, Any]] = []
    bridge = _make_bridge(relayed=relayed)
    executor = Executor(checkpointer=checkpointer, bridge=bridge)
    try:
        ingest = _current_ingest_dispatch(thread_id)
        graph = _install_two_permission_graph(executor, ingest, answered)
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        await executor.handle_dispatch(ingest)
        first_park = (await graph.aget_state(config)).interrupts
        first = _resume_dispatch(
            ingest, ordinal=1, resume_value=_answer_for(first_park[0])
        )
        await executor.handle_dispatch(first)
        second_park = (await graph.aget_state(config)).interrupts
        assert [park.value["tool_name"] for park in second_park] == ["Bash"]
        await bridge.flush_events()

        applied = [
            item["payload"]
            for item in relayed
            if item["payload"].get("type") == "dispatch_applied"
        ]
        assert [payload["dispatch_id"] for payload in applied] == [
            ingest.dispatch_id,
            first.dispatch_id,
        ]
        assert applied[1]["graph_action_receipt"] == (
            first.require_graph_action_receipt().model_dump(mode="json")
        )
    finally:
        await bridge.close()
        await executor.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unreadable_checkpoint_is_reported_as_a_failed_receipt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A read that fails is a receipt failure, not a receipt that is not due.

    Both reads a run makes can fail, and then the gateway never settles the
    action; a debug line saying the checkpoint does not carry the dispatch yet
    would blame the checkpoint's contents for what was an unreachable store.
    """
    relayed: list[dict[str, Any]] = []
    bridge = _make_bridge(relayed=relayed)
    request = _current_ingest_dispatch("receipt-unreadable")
    async with AsyncSqliteSaver.from_conn_string(":memory:") as closed:
        await closed.setup()

    def log_extra(req: DispatchRequest, **fields: Any) -> dict[str, Any]:
        return {"thread_id": req.thread_id, **fields}

    try:
        with caplog.at_level("WARNING", logger="vaultspec_a2a.worker.executor"):
            await DispatchReceiptReporter().report(
                request, closed, bridge, 5.0, log_extra
            )
        await bridge.flush_events()
    finally:
        await bridge.close()

    assert relayed == []
    failures = [
        record
        for record in caplog.records
        if getattr(record, "action", None) == "dispatch_application_receipt_failed"
    ]
    assert len(failures) == 1
    assert failures[0].levelname == "WARNING"


def _install_blocking_permission_graph(
    executor: Executor,
    request: DispatchRequest,
    answered: list[str],
    *,
    past_the_gate: asyncio.Event | None = None,
    stranded: list[asyncio.Task[Any]] | None = None,
) -> RegisteredCompiledGraph:
    """Compile a real graph whose turn keeps working after its answer arrives.

    The window between the answer reaching the node and the superstep
    committing is where a worker dies in production: the answer is already
    held against the parked checkpoint, and the run is still parked, so the
    gateway hands the same action to a restarted worker.

    A node given *past_the_gate* announces that it is inside that window and
    then never leaves it, so the turn cannot commit behind the test's back.
    It records the task it is running under in *stranded* so the test can end
    it rather than leave it pending.
    """

    async def worker_node(state: Any) -> dict[str, Any]:
        answered.append(
            await _bound_permission_callback(state)("Edit", {"path": "a.py"}, _OPTIONS)
        )
        if past_the_gate is not None:
            running = asyncio.current_task()
            if running is not None and stranded is not None:
                stranded.append(running)
            past_the_gate.set()
            await asyncio.Event().wait()
        return {"messages": [AIMessage(content="done")], "next": "FINISH"}

    builder = new_state_graph()
    add_test_node(builder, "worker", worker_node)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    graph: RegisteredCompiledGraph = compile_test_graph(
        builder, checkpointer=executor._checkpointer
    )
    executor.register_compiled_graph(
        request.thread_id,
        (
            request.require_graph_definition().team_id,
            request.workspace_root,
            request.autonomous,
            model_assignment_digest(request.model_assignment),
            request.require_graph_definition().digest(),
        ),
        graph,
    )
    return graph


@pytest.mark.asyncio(loop_scope="function")
async def test_a_resume_redelivered_after_its_turn_died_applies(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A resume delivered twice to one parked checkpoint applies and completes.

    The first worker takes the answer, gets past the gate, and dies before its
    superstep commits, so nothing durable records that the action applied and
    the run is still parked on the request it answered. The gateway redelivers
    the same action to a restarted worker, whose receipt lands on the very
    checkpoint the first delivery's is already held against.
    """
    thread_id = "resume-redelivered"
    answered: list[str] = []
    ingest = _current_ingest_dispatch(thread_id)
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    past_the_gate = asyncio.Event()
    stranded: list[asyncio.Task[Any]] = []

    before_bridge = _make_bridge()
    before = Executor(checkpointer=checkpointer, bridge=before_bridge)
    try:
        graph = _install_blocking_permission_graph(
            before,
            ingest,
            answered,
            past_the_gate=past_the_gate,
            stranded=stranded,
        )
        await before.handle_dispatch(ingest)
        parked = (await graph.aget_state(config)).interrupts
        resume = _resume_dispatch(
            ingest, ordinal=1, resume_value=_answer_for(parked[0])
        )
        dispatch = asyncio.create_task(before.handle_dispatch(resume))
        await asyncio.wait_for(past_the_gate.wait(), timeout=10.0)
        # The worker goes away with the turn still inside the node, which
        # is the window a crash lands in.
        dispatch.cancel()
        await asyncio.wait([dispatch], timeout=10.0)
        for task in stranded:
            task.cancel()
        await asyncio.wait(stranded, timeout=10.0)
        assert answered == ["allow_once"]
    finally:
        await before_bridge.close()
        await before.shutdown()

    # Nothing committed, so the run is still waiting on the same request.
    still_parked = (await graph.aget_state(config)).interrupts
    assert [park.value["tool_name"] for park in still_parked] == ["Edit"]

    after_bridge = _make_bridge()
    after = Executor(checkpointer=checkpointer, bridge=after_bridge)
    try:
        graph = _install_blocking_permission_graph(after, ingest, answered)
        await after.handle_dispatch(resume)

        # The redelivery ran the turn to the end rather than failing it,
        # and the thread's state is still readable - which is what the
        # gateway, recovery and every status read depend on.
        final = await graph.aget_state(config)
        assert final.next == ()
        assert final.interrupts == ()
        assert answered == ["allow_once", "allow_once"]

        durable = await checkpointer.aget_tuple(config)
        assert durable is not None
        receipt = resume.require_graph_action_receipt()
        values = durable.checkpoint["channel_values"]
        assert values["active_graph_action_receipt"] == receipt.model_dump(mode="json")
    finally:
        await after_bridge.close()
        await after.shutdown()
