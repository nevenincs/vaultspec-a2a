"""A registered SSE client must give its stream slot back on every exit.

``max_stream_connections`` bounds a process-lifetime resource: from the moment
``add_subscriber`` returns, the caller owns one of a fixed number of slots, and
nothing but ``remove_subscriber`` gives it back. So the window between
registration and cleanup is the whole safety property - any statement that runs
registered but outside the cleanup guard can strand a slot for the life of the
process, and the gateway would refuse honest callers on the strength of a client
that is long gone.

These drive the real response generator against a real ``EventAggregator`` at a
genuinely occupied capacity, and assert release the only way that means anything:
by having a subsequent client actually take the freed slot through the production
registry API. A count that merely decrements would not prove the slot is usable.

The registered window also covers ``subscribe``, which is called after
registration and cannot be observed to fail here: the route subscribes exactly
one thread id, which cannot exceed a positive ``max_subscriptions_per_client``,
and the cap is skipped outright when it is non-positive. There is therefore no
real input that makes it raise, and no honest test of that raise - only a fake
one, which would prove nothing about the gateway. What is testable is the
invariant that makes such a raise harmless: the registered window is enclosed by
the cleanup guard, exercised below through a normal completion and through a
client that abandons the stream mid-flight.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus
from ..routes.thread_stream import _stream_thread_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _occupy(aggregator: EventAggregator, count: int, *, prefix: str) -> None:
    """Register *count* real subscribers through the production registry API."""
    for index in range(count):
        aggregator.add_subscriber(f"{prefix}-{index}")


async def _drain(frames: AsyncIterator[bytes]) -> None:
    """Consume a stream the way a connected client does."""
    async for _ in frames:
        pass


@pytest.mark.asyncio(loop_scope="function")
async def test_a_finished_stream_hands_its_slot_to_the_next_caller() -> None:
    """A stream that ends normally must leave the registry able to admit again.

    Fills the registry to one slot short of the cap, lets a real stream take the
    last one, and then requires a fresh caller to be admitted through the same
    registry once that stream is done. Registration is refused at the cap, so the
    newcomer's admission is the release: had the finished stream kept its slot,
    ``add_subscriber`` would raise instead.
    """
    aggregator = EventAggregator()
    limit = domain_config.max_stream_connections
    _occupy(aggregator, limit - 1, prefix="held")

    frames = [
        frame
        async for frame in _stream_thread_events(
            aggregator=aggregator,
            thread_id="run-finished",
            initial_status=ThreadStatus.COMPLETED.value,
        )
    ]

    assert len(frames) == 1
    assert b"thread_terminal" in frames[0]
    assert aggregator.subscriber_count() == limit - 1
    assert aggregator.get_active_thread_ids() == []

    aggregator.add_subscriber("newcomer")
    assert aggregator.subscriber_count() == limit


@pytest.mark.asyncio(loop_scope="function")
async def test_a_stream_abandoned_mid_flight_hands_its_slot_to_the_next_caller() -> (
    None
):
    """Cancelling a live stream must release the slot, not strand it.

    This is the exit the gateway actually sees most: a client disconnects while
    the generator is parked on its queue, and the ASGI server cancels the task
    driving it. The cancellation lands inside the registered window - after
    ``add_subscriber`` and after ``subscribe``, which the subscription assertion
    below pins - so it is precisely the case the cleanup guard has to cover.
    """
    aggregator = EventAggregator()
    limit = domain_config.max_stream_connections
    _occupy(aggregator, limit - 1, prefix="held")

    stream = _stream_thread_events(
        aggregator=aggregator,
        thread_id="run-abandoned",
        initial_status=ThreadStatus.RUNNING.value,
    )
    task = asyncio.create_task(_drain(stream))

    async with asyncio.timeout(5):
        while aggregator.subscriber_count() < limit:
            await asyncio.sleep(0)

    # The whole registered window is live: the slot is taken and the thread
    # subscription that follows registration has been applied.
    assert aggregator.get_active_thread_ids() == ["run-abandoned"]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert aggregator.subscriber_count() == limit - 1
    assert aggregator.get_active_thread_ids() == []

    aggregator.add_subscriber("newcomer")
    assert aggregator.subscriber_count() == limit
