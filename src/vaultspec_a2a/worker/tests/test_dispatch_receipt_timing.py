"""The gateway learns a dispatch was incorporated while the run is still going.

The application receipt proves a dispatch reached the graph by reading the
incorporation back off a committed checkpoint. It was triggered by the run's
first event, which by construction precedes every checkpoint of that run, so
the read found nothing, returned silently, and the gateway heard nothing until
the run settled - which for a long run is minutes, and for a run that never
settles is never.

A real executor runs a real two-node graph over a real checkpointer and relays
through a real in-process gateway, so the ordering asserted here is the
ordering a gateway sees.
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


def _relayed_kinds(relayed: list[dict[str, Any]]) -> list[str]:
    """Name each relayed frame by what a gateway would route it on."""
    kinds: list[str] = []
    for item in relayed:
        payload = item["payload"]
        event_type = payload.get("event_type")
        if event_type is not None:
            kinds.append(str(event_type))
        elif payload.get("type") is not None:
            kinds.append(str(payload["type"]))
    return kinds


@pytest.mark.asyncio(loop_scope="function")
async def test_the_application_receipt_precedes_the_work_it_reports_on() -> None:
    """The receipt is relayed once, before the run's later nodes run."""
    second_started = asyncio.Event()

    async def first(state: Any) -> dict[str, Any]:
        del state
        return {"messages": [AIMessage(content="first")]}

    async def second(state: Any) -> dict[str, Any]:
        del state
        second_started.set()
        return {"messages": [AIMessage(content="second")]}

    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        relayed: list[dict[str, Any]] = []
        bridge = _make_bridge(relayed=relayed)
        try:
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            request = _current_ingest_dispatch("receipt-timing-run")
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

            await asyncio.wait_for(executor.handle_dispatch(request), timeout=30.0)
            await bridge.flush_events()

            assert second_started.is_set()
            kinds = _relayed_kinds(relayed)
            assert kinds.count("dispatch_applied") == 1, kinds
            receipt_at = kinds.index("dispatch_applied")
            terminal_at = kinds.index("thread_terminal")
            assert receipt_at < terminal_at, kinds
            # The second node's own status frames come after the receipt, so
            # the gateway knew the dispatch had landed while the run was
            # still executing rather than only once it was over.
            statuses = [
                index for index, kind in enumerate(kinds) if kind == "agent_status"
            ]
            assert statuses, kinds
            assert receipt_at < statuses[-1], kinds
        finally:
            await bridge.close()
