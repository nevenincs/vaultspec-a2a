"""A signal that ends a run is delivered without finishing the run first.

A ``BaseException`` outside ``Exception`` belongs to whoever runs the ingest.
The ingest reports the run as not finished and lets the signal through, but it
must not first do the work that settles a run that is still being served: the
chunk flush and the interrupt read that projects a parked question. Those
awaits stand between a stop request and its owner, and the read describes a
run the signal has already ended.

The run here really parks before it is signalled, and its control is the same
graph left to finish, so the absence asserted on the signalled run is the
absence of something the same park otherwise produces.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ...graph.events import ClarificationPending, ErrorOccurred
from ..aggregator import EventAggregator
from ._error_injecting_graph import InjectedSignal
from ._parked_signal_graph import build_parked_then_signalled_graph

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ...graph.events import DomainEvent
    from ._parked_signal_graph import ParkedSignalInput


async def _ingest_parked_run(
    thread_id: str, *, raise_signal: bool, broadcast: list[DomainEvent]
) -> str:
    """Run the parked graph, collecting every event its viewer was sent.

    The events are collected even when the ingest raises, because what the
    viewer was told before the signal surfaced is the thing under test.
    """
    aggregator = EventAggregator()
    queue = aggregator.add_subscriber(f"{thread_id}-client")
    aggregator.subscribe(f"{thread_id}-client", [thread_id])
    graph_input: ParkedSignalInput = {
        "request_id": f"{thread_id}-question",
        "raise_signal": raise_signal,
    }
    ingest = cast("Callable[..., Coroutine[Any, Any, str]]", aggregator.ingest)
    try:
        return await ingest(
            thread_id=thread_id,
            agent_id="supervisor",
            graph=build_parked_then_signalled_graph(),
            graph_input=graph_input,
            config={"configurable": {"thread_id": thread_id}},
        )
    finally:
        broadcast.extend(queue.get_nowait().event for _ in range(queue.qsize()))


def _questions(events: list[DomainEvent]) -> list[str]:
    return [
        event.request_id for event in events if isinstance(event, ClarificationPending)
    ]


@pytest.mark.asyncio
async def test_a_run_that_parks_projects_its_question() -> None:
    """The control: the same park, left to settle, is projected to its viewer."""
    broadcast: list[DomainEvent] = []

    outcome = await _ingest_parked_run(
        "parked-run", raise_signal=False, broadcast=broadcast
    )

    assert outcome == "interrupted"
    assert _questions(broadcast) == ["parked-run-question"]


@pytest.mark.asyncio
async def test_a_signal_after_a_park_is_delivered_without_settling_the_run() -> None:
    """The signal reaches its owner before any settling read is made.

    The viewer is still told the run did not finish; it is not told the run is
    waiting on a question, because no read of the parked state was made on the
    way out.
    """
    broadcast: list[DomainEvent] = []

    with pytest.raises(InjectedSignal):
        await _ingest_parked_run(
            "signalled-run", raise_signal=True, broadcast=broadcast
        )

    assert _questions(broadcast) == []
    errors = [event for event in broadcast if isinstance(event, ErrorOccurred)]
    assert errors
    assert "InjectedSignal" in errors[-1].message
