"""An ingest delivered again after a restart continues its run, not replays it.

Real executors run real graphs over a real checkpointer and relay through a
real in-process gateway. After a worker restart the gateway delivers a run's
open action again; the checkpoint - read through the action receipts it
carries - decides whether that delivery is a new turn, the continuation of a
run stopped part-way, or something that must not run at all.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...providers.team_selection import model_assignment_digest
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...thread.enums import ControlActionType, ThreadStatus
from ..executor import Executor
from .test_executor import (
    _current_ingest_dispatch,
    _frames_of,
    _make_recording_bridge,
)

if TYPE_CHECKING:
    from ...ipc.schemas import DispatchRequest
    from ..graph_lifecycle import RegisteredCompiledGraph


def _register(executor: Executor, request: DispatchRequest, graph: Any) -> None:
    definition = request.require_graph_definition()
    executor.register_compiled_graph(
        request.thread_id,
        (
            definition.team_id,
            request.workspace_root,
            request.autonomous,
            model_assignment_digest(request.model_assignment),
            definition.digest(),
        ),
        graph,
    )


def _two_step_graph(checkpointer: Any, runs: list[str], gate: asyncio.Event) -> Any:
    async def first(state: Any) -> dict[str, Any]:
        del state
        runs.append("first")
        await gate.wait()
        return {"messages": [AIMessage(content="first")]}

    async def second(state: Any) -> dict[str, Any]:
        del state
        runs.append("second")
        return {"messages": [AIMessage(content="second")]}

    builder = new_state_graph()
    add_test_node(builder, "first", first)
    add_test_node(builder, "second", second)
    builder.add_edge("__start__", "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", "__end__")
    graph: RegisteredCompiledGraph = compile_test_graph(
        builder, checkpointer=checkpointer
    )
    return graph


def _follow_up(request: DispatchRequest, dispatch_id: str) -> DispatchRequest:
    receipt = request.require_graph_action_receipt()
    return request.model_copy(
        update={
            "dispatch_id": dispatch_id,
            "graph_action_receipt": receipt.model_copy(
                update={
                    "dispatch_id": dispatch_id,
                    "action_id": f"{dispatch_id}-action",
                    "action_type": ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                    "writer_generation": receipt.writer_generation + 1,
                }
            ),
        }
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_a_drained_run_delivered_again_continues_where_it_stopped() -> None:
    runs: list[str] = []
    gate = asyncio.Event()
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        request = _current_ingest_dispatch("redelivered-run")
        relayed: list[dict[str, Any]] = []

        before_bridge = _make_recording_bridge(relayed)
        before = Executor(checkpointer=checkpointer, bridge=before_bridge)
        graph = _two_step_graph(checkpointer, runs, gate)
        try:
            _register(before, request, graph)
            dispatch = asyncio.create_task(before.handle_dispatch(request))
            while runs != ["first"]:
                await asyncio.sleep(0.01)
            drain = asyncio.create_task(before.drain("restart"))
            gate.set()
            await asyncio.wait_for(dispatch, timeout=10.0)
            await asyncio.wait_for(drain, timeout=10.0)
        finally:
            await before_bridge.close()
            await before.shutdown()
        assert runs == ["first"]

        # The restarted worker is handed the same open action again.
        after_relayed: list[dict[str, Any]] = []
        bridge = _make_recording_bridge(after_relayed)
        after = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            _register(after, request, graph)
            await asyncio.wait_for(after.handle_dispatch(request), timeout=10.0)
            await bridge.flush_events()

            assert runs == ["first", "second"]
            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": request.thread_id}}
            )
            inputs = [
                m for m in snapshot.values["messages"] if isinstance(m, HumanMessage)
            ]
            assert [m.content for m in inputs] == ["build it"]
            terminals = _frames_of(after_relayed, "thread_terminal")
            assert [t["status"] for t in terminals] == [ThreadStatus.COMPLETED]
        finally:
            await bridge.close()
            await after.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_a_follow_up_over_a_finished_turn_runs_instead_of_reporting_done() -> (
    None
):
    runs: list[str] = []
    gate = asyncio.Event()
    gate.set()
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        relayed: list[dict[str, Any]] = []
        bridge = _make_recording_bridge(relayed)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        try:
            first_turn = _current_ingest_dispatch("follow-up-run")
            graph = _two_step_graph(checkpointer, runs, gate)
            _register(executor, first_turn, graph)
            await asyncio.wait_for(executor.handle_dispatch(first_turn), timeout=10.0)
            assert runs == ["first", "second"]

            second_turn = _follow_up(first_turn, "follow-up-run-second")
            _register(executor, second_turn, graph)
            await asyncio.wait_for(executor.handle_dispatch(second_turn), timeout=10.0)
            await bridge.flush_events()

            assert runs == ["first", "second", "first", "second"]
            terminals = _frames_of(relayed, "thread_terminal")
            assert [t["status"] for t in terminals] == [
                ThreadStatus.COMPLETED,
                ThreadStatus.COMPLETED,
            ]
        finally:
            await bridge.close()
            await executor.shutdown()


@pytest.mark.asyncio(loop_scope="function")
async def test_an_unreadable_checkpoint_refuses_rather_than_reingesting() -> None:
    runs: list[str] = []
    gate = asyncio.Event()
    gate.set()
    async with AsyncSqliteSaver.from_conn_string(":memory:") as closed:
        await closed.setup()
    # The saver's connection is closed now: every read of it fails for real.
    relayed: list[dict[str, Any]] = []
    bridge = _make_recording_bridge(relayed)
    executor = Executor(checkpointer=closed, bridge=bridge)
    try:
        request = _current_ingest_dispatch("unreadable-run")
        _register(executor, request, _two_step_graph(closed, runs, gate))
        await asyncio.wait_for(executor.handle_dispatch(request), timeout=10.0)
        await bridge.flush_events()

        assert runs == []
        terminals = _frames_of(relayed, "thread_terminal")
        assert [t["status"] for t in terminals] == [ThreadStatus.FAILED]
        assert "could not be read" in terminals[0]["error_detail"]
    finally:
        await bridge.close()
        await executor.shutdown()
