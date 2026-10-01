"""A first ingest redelivered over its own input checkpoint continues.

A worker killed between the checkpoint LangGraph commits for a run's input and
the first superstep that consumes it leaves the input durable and nothing else.
The gateway redelivers the open action to the restarted worker, which must
carry the run on from that checkpoint: re-sending the input would put the
user's message in the thread twice, and refusing it strands a run whose input
is already durable.

Real executor, real compiled graph, real SQLite store. The checkpoint the
restarted worker finds is one a real graph run wrote, replayed into this
store through the saver's own API, because the window it belongs to is shorter
than any scheduler can be asked to stop inside.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...tests._checkpoint_seeding import real_input_checkpoint
from ...thread.enums import ThreadStatus
from ..executor import Executor
from ..graph_lifecycle import GraphLifecycleManager
from .test_executor import (
    _current_ingest_dispatch,
    _frames_of,
    _make_recording_bridge,
)
from .test_executor_redelivery import _register, _two_step_graph

if TYPE_CHECKING:
    from ...ipc.schemas import DispatchRequest


def _first_ingest_input(request: DispatchRequest) -> dict[str, Any]:
    """The input the executor sends on a thread's first ingest."""
    receipt = request.require_graph_action_receipt()
    graph_input = GraphLifecycleManager.build_graph_input(request, is_first_ingest=True)
    graph_input["graph_action_receipts"] = {
        request.dispatch_id: receipt.model_dump(mode="json")
    }
    graph_input["active_graph_action_receipt"] = receipt.model_dump(mode="json")
    return graph_input


@pytest.mark.asyncio(loop_scope="function")
async def test_a_redelivered_first_ingest_over_its_input_checkpoint_runs_once() -> None:
    """The run completes, and the user's message is in the thread exactly once."""
    runs: list[str] = []
    gate = asyncio.Event()
    gate.set()
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        request = _current_ingest_dispatch("input-window-run")
        checkpoint, metadata = await real_input_checkpoint(_first_ingest_input(request))
        await checkpointer.aput(
            {"configurable": {"thread_id": request.thread_id, "checkpoint_ns": ""}},
            checkpoint,
            metadata,
            checkpoint["channel_versions"],
        )

        relayed: list[dict[str, Any]] = []
        bridge = _make_recording_bridge(relayed)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        graph = _two_step_graph(checkpointer, runs, gate)
        try:
            _register(executor, request, graph)
            await asyncio.wait_for(executor.handle_dispatch(request), timeout=30.0)
            await bridge.flush_events()

            assert runs == ["first", "second"]
            snapshot = await graph.aget_state(
                {"configurable": {"thread_id": request.thread_id}}
            )
            inputs = [
                m for m in snapshot.values["messages"] if isinstance(m, HumanMessage)
            ]
            assert [m.content for m in inputs] == ["build it"], (
                "the input already in the checkpoint was delivered again"
            )
            terminals = _frames_of(relayed, "thread_terminal")
            assert [t["status"] for t in terminals] == [ThreadStatus.COMPLETED]
        finally:
            await bridge.close()
            await executor.shutdown()
