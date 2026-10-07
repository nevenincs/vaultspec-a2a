"""An answer reaches the graph only when the run is waiting on its question.

Real executors drive real graphs over a real ``AsyncSqliteSaver`` and relay
through a real in-process gateway. LangGraph hands a resume value to the first
``interrupt()`` of the next superstep, so a run that is not parked, or parked
on a different question, would have an answer nobody gave for it settle the
question it does reach. Both are refused here, and a refusal leaves the run
exactly as it was.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.permission_dispatch import permission_resume_value
from ...providers.team_selection import model_assignment_digest
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...thread.enums import ThreadStatus
from ..executor import Executor
from ..state_projection import ResumeRefusalCause
from .test_executor import (
    _current_ingest_dispatch,
    _frames_of,
    _make_recording_bridge,
)
from .test_executor_resume_receipts import (
    _OPTIONS,
    _bound_permission_callback,
    _resume_dispatch,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...ipc.schemas import DispatchRequest
    from ..graph_lifecycle import RegisteredCompiledGraph


def _cache_key(request: DispatchRequest) -> tuple[Any, ...]:
    definition = request.require_graph_definition()
    return (
        definition.team_id,
        request.workspace_root,
        request.autonomous,
        model_assignment_digest(request.model_assignment),
        definition.digest(),
    )


def _install_gate_behind_a_step(
    executor: Executor,
    request: DispatchRequest,
    entered: list[str],
    *,
    hold: asyncio.Event,
) -> RegisteredCompiledGraph:
    """Compile a real graph whose gate sits one superstep past the start.

    A drain leaves a checkpoint whose next node is the gate but which is
    parked on nothing. That is the shape a resume must not be spent on, and
    *hold* is what lets the test request the drain while the first node is
    still running.
    """

    async def before(state: Any) -> dict[str, Any]:
        del state
        entered.append("before")
        await hold.wait()
        return {"messages": [AIMessage(content="ready")]}

    async def gate(state: Any) -> dict[str, Any]:
        entered.append("gate")
        decision = await _bound_permission_callback(state)(
            "Edit", {"path": "a.py"}, _OPTIONS
        )
        entered.append(f"gate:{decision}")
        return {"messages": [AIMessage(content="done")], "next": "FINISH"}

    builder = new_state_graph()
    add_test_node(builder, "before", before)
    add_test_node(builder, "gate", gate)
    builder.add_edge("__start__", "before")
    builder.add_edge("before", "gate")
    builder.add_edge("gate", "__end__")
    graph: RegisteredCompiledGraph = compile_test_graph(
        builder, checkpointer=executor._checkpointer
    )
    executor.register_compiled_graph(request.thread_id, _cache_key(request), graph)
    return graph


@pytest.mark.asyncio(loop_scope="function")
async def test_a_resume_on_an_unparked_checkpoint_never_reaches_the_gate() -> None:
    """A run stopped between supersteps refuses the answer instead of using it."""
    thread_id = "resume-unparked"
    entered: list[str] = []
    relayed: list[dict[str, Any]] = []
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        bridge = _make_recording_bridge(relayed)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            ingest = _current_ingest_dispatch(thread_id)
            hold = asyncio.Event()
            graph = _install_gate_behind_a_step(executor, ingest, entered, hold=hold)
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            # A drain stops the run at the superstep boundary in front of the
            # gate, which is the shape a restarted worker inherits.
            dispatch = asyncio.create_task(executor.handle_dispatch(ingest))
            while entered != ["before"]:
                await asyncio.sleep(0.01)
            drain = asyncio.create_task(executor.drain("restart"))
            hold.set()
            await asyncio.wait_for(dispatch, timeout=10.0)
            await asyncio.wait_for(drain, timeout=10.0)

            before_state = await graph.aget_state(config)
            assert before_state.next == ("gate",)
            assert before_state.interrupts == ()
        finally:
            await bridge.close()
            await executor.shutdown()

        # A drained worker refuses every later dispatch, so the answer reaches
        # the worker that restarts over the same checkpoint.
        relayed.clear()
        bridge = _make_recording_bridge(relayed)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            executor.register_compiled_graph(
                ingest.thread_id, _cache_key(ingest), graph
            )
            # A bare option id, which names no request and so cannot be
            # matched against what the run asked. Only the run not being
            # parked can turn it away.
            await executor.handle_dispatch(
                _resume_dispatch(ingest, ordinal=1, resume_value="allow_once")
            )
            await bridge.flush_events()

            # The gate never ran, so no answer was spent on a question no
            # human was shown.
            assert entered == ["before"]
            after = await graph.aget_state(config)
            assert after.next == ("gate",)
            assert after.interrupts == ()

            errors = _frames_of(relayed, "error")
            assert [error["code"] for error in errors] == [
                ResumeRefusalCause.NOT_PARKED.value
            ]
            assert errors[0]["recoverable"] is True
            # A refused answer is a client's mistake, not the run's death.
            assert _frames_of(relayed, "thread_terminal") == []
        finally:
            await bridge.close()
            await executor.shutdown()


def _install_single_permission_graph(
    executor: Executor, request: DispatchRequest, answered: dict[str, str]
) -> RegisteredCompiledGraph:
    """Compile a real graph parking once on one production permission request."""

    async def worker_node(state: Any) -> dict[str, Any]:
        answered["Edit"] = await _bound_permission_callback(state)(
            "Edit", {"path": "a.py"}, _OPTIONS
        )
        return {"messages": [AIMessage(content="done")], "next": "FINISH"}

    builder = new_state_graph()
    add_test_node(builder, "worker", worker_node)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    graph: RegisteredCompiledGraph = compile_test_graph(
        builder, checkpointer=executor._checkpointer
    )
    executor.register_compiled_graph(request.thread_id, _cache_key(request), graph)
    return graph


@pytest.mark.asyncio(loop_scope="function")
async def test_a_foreign_answer_is_refused_and_the_run_still_resolves() -> None:
    """An answer to a question the run is not asking is turned away, not spent."""
    thread_id = "resume-foreign-request"
    answered: dict[str, str] = {}
    relayed: list[dict[str, Any]] = []
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        bridge = _make_recording_bridge(relayed)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            ingest = _current_ingest_dispatch(thread_id)
            graph = _install_single_permission_graph(executor, ingest, answered)
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            await executor.handle_dispatch(ingest)
            parked = (await graph.aget_state(config)).interrupts
            asked = parked[0].value["request_id"]

            relayed.clear()
            await executor.handle_dispatch(
                _resume_dispatch(
                    ingest,
                    ordinal=1,
                    resume_value=permission_resume_value(
                        "permission_request",
                        "allow_once",
                        None,
                        request_id="perm-a-question-from-another-turn",
                    ),
                )
            )
            await bridge.flush_events()

            assert answered == {}
            errors = _frames_of(relayed, "error")
            assert [error["code"] for error in errors] == [
                ResumeRefusalCause.REQUEST_NOT_PENDING.value
            ]
            assert _frames_of(relayed, "thread_terminal") == []

            # The question is still open, and the answer it was waiting for
            # still resolves it.
            still = (await graph.aget_state(config)).interrupts
            assert [park.value["request_id"] for park in still] == [asked]

            relayed.clear()
            await executor.handle_dispatch(
                _resume_dispatch(
                    ingest,
                    ordinal=2,
                    resume_value=permission_resume_value(
                        "permission_request", "allow_once", None, request_id=asked
                    ),
                )
            )
            await bridge.flush_events()

            assert answered == {"Edit": "allow_once"}
            assert (await graph.aget_state(config)).next == ()
            terminals = _frames_of(relayed, "thread_terminal")
            assert [terminal["status"] for terminal in terminals] == [
                ThreadStatus.COMPLETED
            ]
        finally:
            await bridge.close()
            await executor.shutdown()
