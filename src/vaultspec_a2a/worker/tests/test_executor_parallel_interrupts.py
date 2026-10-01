"""A run waiting on several questions can be answered one at a time.

Real executors resume a real fan-out graph over a real ``AsyncSqliteSaver``.
LangGraph matches a bare resume value to a run's single pending interrupt and
refuses one outright while several are pending, so an answer to one of several
has to name the interrupt it belongs to. A fan-out stage parks each branch on
its own question, which is how a run comes to wait on more than one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command, Send, interrupt

from ...api.tests.clarification_harness import new_state_graph
from ...control.permission_dispatch import answered_permission_request
from ...providers.team_selection import model_assignment_digest
from ..executor import Executor
from ..state_projection import ResumeRefusalCause
from .test_executor import (
    _current_ingest_dispatch,
    _frames_of,
    _make_recording_bridge,
)
from .test_executor_resume_receipts import _resume_dispatch

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...ipc.schemas import DispatchRequest
    from ..graph_lifecycle import RegisteredCompiledGraph

_BRANCHES = ("left", "right")


def _install_two_gate_fan_out(
    executor: Executor, request: DispatchRequest, answered: dict[str, str]
) -> RegisteredCompiledGraph:
    """Compile a real graph that parks two branches on two questions at once."""

    async def fan(state: Any) -> Command[Any]:
        del state
        return Command(goto=[Send("gate", {"branch": branch}) for branch in _BRANCHES])

    async def gate(state: Any) -> dict[str, Any]:
        branch = state["branch"]
        given = interrupt({"type": "permission_request", "request_id": f"req-{branch}"})
        # Read through the production reader, so the shape a branch accepts is
        # the shape a dispatched answer really carries.
        named = answered_permission_request(given)
        assert named is not None, given
        request_id, option_id = named
        assert request_id == f"req-{branch}", named
        answered[branch] = option_id
        return {"messages": [AIMessage(content=f"{branch} done")]}

    async def join(state: Any) -> dict[str, Any]:
        del state
        return {"next": "FINISH"}

    builder = new_state_graph()
    builder.add_node("fan", fan)
    builder.add_node("gate", gate)
    builder.add_node("join", join)
    builder.add_edge("__start__", "fan")
    builder.add_edge("gate", "join")
    builder.add_edge("join", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(
        checkpointer=executor._checkpointer
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
async def test_each_of_two_parallel_questions_takes_its_own_answer() -> None:
    """Two branches parked at once are answered one dispatch at a time."""
    thread_id = "parallel-gates"
    answered: dict[str, str] = {}
    relayed: list[dict[str, Any]] = []
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        bridge = _make_recording_bridge(relayed)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            ingest = _current_ingest_dispatch(thread_id)
            graph = _install_two_gate_fan_out(executor, ingest, answered)
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            await executor.handle_dispatch(ingest)
            parked = (await graph.aget_state(config)).interrupts
            assert sorted(park.value["request_id"] for park in parked) == [
                "req-left",
                "req-right",
            ]

            relayed.clear()
            await executor.handle_dispatch(
                _resume_dispatch(
                    ingest,
                    ordinal=1,
                    resume_value={"option_id": "allow_once", "request_id": "req-left"},
                )
            )
            await bridge.flush_events()

            # The left branch took its answer and only the left branch did.
            # The run is not settled: its other branch is still waiting, and
            # LangGraph keeps listing both interrupts until the superstep that
            # holds them commits, so the branch that ran is the evidence here.
            assert answered == {"left": "allow_once"}
            assert _frames_of(relayed, "error") == []
            assert _frames_of(relayed, "thread_terminal") == []

            await executor.handle_dispatch(
                _resume_dispatch(
                    ingest,
                    ordinal=2,
                    resume_value={
                        "option_id": "reject_once",
                        "request_id": "req-right",
                    },
                )
            )
            assert answered == {"left": "allow_once", "right": "reject_once"}
            final = await graph.aget_state(config)
            assert final.next == ()
            assert final.interrupts == ()
        finally:
            await bridge.close()
            await executor.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_an_answer_naming_none_of_several_questions_is_refused() -> None:
    """A bare answer to a run waiting on two is refused, not guessed at.

    LangGraph refuses it too, but from inside the run: the refusal surfaces as
    a failed run rather than as an answer the client can correct.
    """
    thread_id = "parallel-gates-bare"
    answered: dict[str, str] = {}
    relayed: list[dict[str, Any]] = []
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        bridge = _make_recording_bridge(relayed)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            ingest = _current_ingest_dispatch(thread_id)
            graph = _install_two_gate_fan_out(executor, ingest, answered)
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            await executor.handle_dispatch(ingest)
            relayed.clear()
            await executor.handle_dispatch(
                _resume_dispatch(ingest, ordinal=1, resume_value="allow_once")
            )
            await bridge.flush_events()

            assert answered == {}
            errors = _frames_of(relayed, "error")
            assert [error["code"] for error in errors] == [
                ResumeRefusalCause.AMBIGUOUS_TARGET.value
            ]
            assert errors[0]["recoverable"] is True
            # The run is not failed: both questions are still answerable.
            assert _frames_of(relayed, "thread_terminal") == []
            still = (await graph.aget_state(config)).interrupts
            assert sorted(park.value["request_id"] for park in still) == [
                "req-left",
                "req-right",
            ]
        finally:
            await bridge.close()
            await executor.shutdown()
