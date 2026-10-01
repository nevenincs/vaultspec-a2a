"""A worker shutdown drains its runs at a superstep boundary.

A real executor runs a real two-node graph over a real checkpointer, relaying
through a real in-process gateway. The drain is requested while the first node
is mid-turn: that node finishes, the run stops before the second one, the
checkpoint names the second node as next, and no terminal status is relayed,
because the run is not over - its open action is delivered again after restart.

The drain a worker requested also outlives the runs that existed when it was
asked for, and a run cancelled outright once the drain budget runs out settles
no terminal either, on the same contract: both leave a resumable checkpoint and
an open action for recovery to deliver again.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_store
from langgraph.store.memory import InMemoryStore

from ...api.tests.clarification_harness import new_state_graph
from ...providers.team_selection import model_assignment_digest
from .._dispatch_contract import CAPACITY_ACCEPTED, CAPACITY_DRAINING
from ..executor import Executor
from .test_executor import _current_ingest_dispatch, _make_bridge

if TYPE_CHECKING:
    from ..graph_lifecycle import RegisteredCompiledGraph


@pytest.mark.asyncio(loop_scope="function")
async def test_shutdown_drain_stops_the_run_between_nodes_without_settling_it() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def first(state: Any) -> dict[str, Any]:
        del state
        # The drain is seated as the run's runtime, which is also where a node
        # finds its store; the graph's own store must still be the one it gets.
        get_store().put(("drain",), "first", {"ran": True})
        first_started.set()
        await release_first.wait()
        return {"messages": [AIMessage(content="first")]}

    async def second(state: Any) -> dict[str, Any]:
        del state
        return {"messages": [AIMessage(content="second")]}

    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        relayed: list[dict[str, Any]] = []
        bridge = _make_bridge(relayed=relayed)
        try:
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            request = _current_ingest_dispatch("drain-run")
            builder = new_state_graph()
            builder.add_node("first", first)
            builder.add_node("second", second)
            builder.add_edge("__start__", "first")
            builder.add_edge("first", "second")
            builder.add_edge("second", "__end__")
            store = InMemoryStore()
            graph: RegisteredCompiledGraph = builder.compile(
                checkpointer=checkpointer, store=store
            )
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

            dispatch = asyncio.create_task(executor.handle_dispatch(request))
            await asyncio.wait_for(first_started.wait(), timeout=10.0)
            drain = asyncio.create_task(executor.drain("test shutdown"))
            release_first.set()
            await asyncio.wait_for(dispatch, timeout=10.0)
            await asyncio.wait_for(drain, timeout=10.0)

            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": request.thread_id}}
            )
            assert snapshot.next == ("second",)
            assert store.get(("drain",), "first") is not None
            terminals = [
                item["payload"]
                for item in relayed
                if item["payload"].get("event_type") == "thread_terminal"
            ]
            assert terminals == []
        finally:
            await bridge.close()


@pytest.mark.asyncio(loop_scope="function")
async def test_drain_reaches_a_run_whose_control_opens_after_it_was_requested() -> None:
    """A dispatch admitted before the drain is still drained when it starts.

    The worker admits a dispatch by reserving its capacity and only then starts
    it in its task group, so a shutdown drain can land between the two. The run
    that starts afterwards stops at its first superstep boundary like every
    other one: its node never runs and its action stays open.
    """
    ran: list[str] = []

    async def only(state: Any) -> dict[str, Any]:
        del state
        ran.append("only")
        return {"messages": [AIMessage(content="only")]}

    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        relayed: list[dict[str, Any]] = []
        bridge = _make_bridge(relayed=relayed)
        try:
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            request = _current_ingest_dispatch("late-control-run")
            builder = new_state_graph()
            builder.add_node("only", only)
            builder.add_edge("__start__", "only")
            builder.add_edge("only", "__end__")
            graph: RegisteredCompiledGraph = builder.compile(checkpointer=checkpointer)
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

            reservation, reason = await executor.reserve_dispatch_capacity(
                request.thread_id
            )
            assert reason == CAPACITY_ACCEPTED
            # No run holds a control yet, so this drain returns at once - and
            # must still apply to the dispatch already admitted behind it.
            await asyncio.wait_for(executor.drain("test shutdown"), timeout=10.0)
            await asyncio.wait_for(
                executor.handle_reserved_dispatch(request, reservation), timeout=10.0
            )

            assert ran == []
            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": request.thread_id}}
            )
            assert snapshot.next == ("__start__",)
            await bridge.flush_events()
            terminals = [
                item["payload"]
                for item in relayed
                if item["payload"].get("event_type") == "thread_terminal"
            ]
            assert terminals == []
        finally:
            await bridge.close()


@pytest.mark.asyncio(loop_scope="function")
async def test_a_draining_worker_refuses_a_new_dispatch_under_its_own_reason() -> None:
    """A worker that began draining admits no further run, under its own token."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        bridge = _make_bridge()
        try:
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            await asyncio.wait_for(executor.drain("test shutdown"), timeout=10.0)
            reservation, reason = await executor.reserve_dispatch_capacity("late-run")
            assert reservation is None
            assert reason == CAPACITY_DRAINING
        finally:
            await bridge.close()


@pytest.mark.asyncio(loop_scope="function")
async def test_cancelling_a_run_mid_node_relays_no_failure_and_propagates() -> None:
    """A cancelled dispatch is not a failed run.

    The worker lifespan cancels whatever is still mid-turn once the drain
    budget runs out. That run's action stays open for redelivery, so the
    cancellation reaches the canceller instead of being reported as a provider
    failure that persists a FAILED terminal.
    """
    started = asyncio.Event()

    async def slow(state: Any) -> dict[str, Any]:
        del state
        started.set()
        await asyncio.sleep(60)
        return {"messages": [AIMessage(content="late")]}

    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        relayed: list[dict[str, Any]] = []
        bridge = _make_bridge(relayed=relayed)
        try:
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            request = _current_ingest_dispatch("cancelled-run")
            builder = new_state_graph()
            builder.add_node("slow", slow)
            builder.add_edge("__start__", "slow")
            builder.add_edge("slow", "__end__")
            graph: RegisteredCompiledGraph = builder.compile(checkpointer=checkpointer)
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

            dispatch = asyncio.create_task(executor.handle_dispatch(request))
            await asyncio.wait_for(started.wait(), timeout=10.0)
            dispatch.cancel()
            with pytest.raises(asyncio.CancelledError):
                await dispatch
            assert dispatch.cancelled()

            await bridge.flush_events()
            payloads = [item["payload"] for item in relayed]
            assert [p for p in payloads if p.get("event_type") == "error"] == []
            assert [
                p for p in payloads if p.get("event_type") == "thread_terminal"
            ] == []
        finally:
            await bridge.close()
