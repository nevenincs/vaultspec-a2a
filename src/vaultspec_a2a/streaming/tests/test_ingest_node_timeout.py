"""A node that outruns its own run budget fails the run and names itself.

Driven through a real compiled LangGraph graph and the real producer ingest:
the node's ``TimeoutPolicy`` is enforced by LangGraph, and the classification
under test is what ingest reports once LangGraph raises.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict, cast

import pytest
from langgraph.graph import END, START
from langgraph.types import TimeoutPolicy

from ...graph.events import ErrorOccurred
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..aggregator import RunEventProducer

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
    builder = new_state_graph(_State)
    add_test_node(
        builder,
        "slow_author",
        _outlasting_node,
        timeout=TimeoutPolicy(run_timeout=run_timeout),
    )
    builder.add_edge(START, "slow_author")
    builder.add_edge("slow_author", END)
    return cast("StreamableGraph", compile_test_graph(builder))


@pytest.mark.asyncio
async def test_a_node_timeout_fails_the_run_naming_the_node_and_limit() -> None:
    producer = RunEventProducer()
    events: list[SequencedEvent] = []

    async def _relay(sequenced: SequencedEvent) -> None:
        events.append(sequenced)

    # The broadcast hook is the seam the worker relays every event through.
    producer.add_broadcast_hook(_relay)
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", producer.ingest)

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
    errors = [s.event for s in events if isinstance(s.event, ErrorOccurred)]
    assert errors, "a timed-out node must surface an error event"
    error = errors[-1]
    assert error.code == "STEP_TIMEOUT"
    assert error.recoverable is True
    assert "'slow_author'" in error.message
    assert "run timeout" in error.message
    assert producer.take_failure_reason("thread-node-timeout") == error.message
