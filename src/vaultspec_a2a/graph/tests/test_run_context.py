"""Run identity reaches graph nodes as LangGraph Runtime context.

The resolver is exercised with real ``Runtime`` objects, and the plumbing is
proven end to end: a context handed to the aggregator's ingest arrives, intact,
inside a node of a real compiled graph, and a compiled team graph declares it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from ...streaming.aggregator import EventAggregator
from ...team.team_config import load_agent_config, load_team_config
from ...testing import add_test_node, compile_test_graph
from ..compiler import compile_team_graph
from ..run_context import RunContext, run_thread_id
from .conftest import deterministic_model_assignment

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ...streaming.types import StreamableGraph
    from ...thread.state import TeamState
    from ..protocols import ProviderFactoryProtocol

_CONTEXT = RunContext(thread_id="ctx-thread", dispatch_id="dispatch-7", action="resume")


def _state(thread_id: str | None) -> TeamState:
    state = cast("TeamState", {"messages": []})
    if thread_id is not None:
        state["thread_id"] = thread_id
    return state


def test_the_invocation_context_outranks_checkpointed_state() -> None:
    runtime = Runtime(context=_CONTEXT)
    assert run_thread_id(_state("state-thread"), runtime) == "ctx-thread"


def test_state_is_the_identity_only_when_no_context_is_running() -> None:
    assert run_thread_id(_state("state-thread"), None) == "state-thread"
    assert run_thread_id(_state("state-thread"), Runtime(context=None)) == (
        "state-thread"
    )
    assert run_thread_id(_state(None), None) is None


class _Seen(TypedDict):
    seen: str


@pytest.mark.asyncio
async def test_ingest_delivers_the_run_context_to_graph_nodes() -> None:
    received: list[object] = []

    async def record(state: _Seen, runtime: Runtime[RunContext]) -> dict[str, str]:
        del state
        received.append(runtime.context)
        return {"seen": "yes"}

    builder: StateGraph[Any, RunContext, Any, Any] = StateGraph(
        cast("Any", _Seen), context_schema=RunContext
    )
    add_test_node(builder, "record", record)
    builder.add_edge(START, "record")
    builder.add_edge("record", END)
    graph = cast("StreamableGraph", compile_test_graph(builder))

    aggregator = EventAggregator()
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", aggregator.ingest)
    outcome = await asyncio.wait_for(
        ingest(
            thread_id="ctx-thread",
            agent_id="supervisor",
            graph=graph,
            graph_input={"seen": ""},
            config={"configurable": {"thread_id": "ctx-thread"}},
            context=_CONTEXT,
        ),
        timeout=10.0,
    )

    assert outcome == "completed"
    assert received == [_CONTEXT]


@pytest.mark.asyncio
async def test_a_compiled_team_graph_runs_under_the_run_context(
    pf: ProviderFactoryProtocol,
) -> None:
    team = load_team_config("vaultspec-solo-coder")
    graph = compile_team_graph(
        team_config=team,
        agent_configs={w.agent_id: load_agent_config(w.agent_id) for w in team.workers},
        provider_factory=pf,
        model_assignment=deterministic_model_assignment(team),
    )
    assert cast("Any", graph).context_schema is RunContext
