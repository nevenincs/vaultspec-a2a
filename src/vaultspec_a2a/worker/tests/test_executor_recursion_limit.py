"""A served run is held to the recursion limit its preset declares.

The gateway sends the operator-wide ceiling on every dispatch. A real executor
runs a real graph longer than the preset's own budget, over a real
checkpointer and a real in-process gateway relay: the run must fail on the
recursion limit instead of running on under the looser ceiling.
"""

from __future__ import annotations

import asyncio
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...api.tests.clarification_harness import new_state_graph
from ...providers.team_selection import model_assignment_digest
from ...team.team_config import load_team_config
from ..executor import Executor, _recursion_limit
from .test_executor import _current_ingest_dispatch, _make_bridge

if TYPE_CHECKING:
    from ..graph_lifecycle import RegisteredCompiledGraph

_PRESET_LIMIT = load_team_config("mock-success-single").graph.recursion_limit


def test_the_tighter_of_ceiling_and_preset_budget_holds() -> None:
    loose = _current_ingest_dispatch("limit-loose", recursion_limit=100)
    tight = _current_ingest_dispatch("limit-tight", recursion_limit=4)

    assert _recursion_limit(loose) == _PRESET_LIMIT
    assert _recursion_limit(tight) == 4
    assert _recursion_limit(loose.model_copy(update={"graph_definition": None})) == (
        100
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_a_run_longer_than_its_preset_budget_fails_on_the_limit() -> None:
    async def step(state: Any) -> dict[str, Any]:
        del state
        return {"messages": [AIMessage(content="step")]}

    nodes = [f"step_{index:02d}" for index in range(_PRESET_LIMIT + 2)]
    async with AsyncSqliteSaver.from_conn_string(":memory:") as checkpointer:
        await checkpointer.setup()
        relayed: list[dict[str, Any]] = []
        bridge = _make_bridge(relayed=relayed)
        try:
            executor = Executor(checkpointer=checkpointer, bridge=bridge)
            request = _current_ingest_dispatch("limit-run", recursion_limit=100)
            builder = new_state_graph()
            for node in nodes:
                builder.add_node(node, step)
            builder.add_edge("__start__", nodes[0])
            for current, following in pairwise(nodes):
                builder.add_edge(current, following)
            builder.add_edge(nodes[-1], "__end__")
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

            await asyncio.wait_for(executor.handle_dispatch(request), timeout=20.0)

            payloads = [item["payload"] for item in relayed]
            terminals = [
                p for p in payloads if p.get("event_type") == "thread_terminal"
            ]
            assert [t.get("status") for t in terminals] == ["failed"]
            assert any(p.get("code") == "RECURSION_LIMIT_EXCEEDED" for p in payloads), (
                payloads
            )
        finally:
            await bridge.close()
