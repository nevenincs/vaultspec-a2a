"""A node that outruns its own run budget fails the run and names itself.

Driven through a real compiled LangGraph graph and the real aggregator ingest:
the node's ``TimeoutPolicy`` is enforced by LangGraph, and the classification
under test is what ingest reports once LangGraph raises.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict, cast

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import TimeoutPolicy

from ...graph.compiler import _add_node
from ...graph.events import ErrorOccurred
from ..aggregator import EventAggregator

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ..types import SequencedEvent, StreamableGraph


class _State(TypedDict):
    note: str


async def _outlasting_node(state: _State) -> dict[str, str]:
    del state
    await asyncio.sleep(30)
    return {"note": "never"}


def _graph_with_node_budget(run_timeout: float) -> StreamableGraph:
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _State))
    _add_node(
        builder,
        "slow_author",
        _outlasting_node,
        timeout=TimeoutPolicy(run_timeout=run_timeout),
    )
    builder.add_edge(START, "slow_author")
    builder.add_edge("slow_author", END)
    return cast("StreamableGraph", builder.compile())


@pytest.mark.asyncio
async def test_a_node_timeout_fails_the_run_naming_the_node_and_limit() -> None:
    aggregator = EventAggregator()
    queue = aggregator.add_subscriber("client-node-timeout")
    aggregator.subscribe("client-node-timeout", ["thread-node-timeout"])
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", aggregator.ingest)

    outcome = await asyncio.wait_for(
        ingest(
            thread_id="thread-node-timeout",
            agent_id="supervisor",
            graph=_graph_with_node_budget(0.2),
            graph_input={"note": ""},
            config={"configurable": {"thread_id": "thread-node-timeout"}},
        ),
        timeout=10.0,
    )

    assert outcome == "failed"
    events: list[SequencedEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    errors = [s.event for s in events if isinstance(s.event, ErrorOccurred)]
    assert errors, "a timed-out node must surface an error event"
    error = errors[-1]
    assert error.code == "STEP_TIMEOUT"
    assert error.recoverable is True
    assert "'slow_author'" in error.message
    assert "run timeout" in error.message
    assert aggregator.take_failure_reason("thread-node-timeout") == error.message
