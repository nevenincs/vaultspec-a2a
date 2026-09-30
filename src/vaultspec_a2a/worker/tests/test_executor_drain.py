"""A worker shutdown drains its runs at a superstep boundary.

A real executor runs a real two-node graph over a real checkpointer, relaying
through a real in-process gateway. The drain is requested while the first node
is mid-turn: that node finishes, the run stops before the second one, the
checkpoint names the second node as next, and no terminal status is relayed,
because the run is not over - its open action is delivered again after restart.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...api.tests.clarification_harness import new_state_graph
from ...providers.team_selection import model_assignment_digest
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
            await asyncio.wait_for(first_started.wait(), timeout=10.0)
            drain = asyncio.create_task(executor.drain("test shutdown"))
            release_first.set()
            await asyncio.wait_for(dispatch, timeout=10.0)
            await asyncio.wait_for(drain, timeout=10.0)

            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": request.thread_id}}
            )
            assert snapshot.next == ("second",)
            terminals = [
                item["payload"]
                for item in relayed
                if item["payload"].get("event_type") == "thread_terminal"
            ]
            assert terminals == []
        finally:
            await bridge.close()
