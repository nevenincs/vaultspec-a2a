"""The stream quota must bind where registration happens, not only where it is checked.

The global cap on progress-stream subscribers is already proven against the SSE
edge with a real authenticated client (see the S160 global-quota cases in
``test_progress_allowlist``). That route-level check is not where the bound
actually holds: it runs while the response is being built, before the
registration it authorises has happened, so a concurrent stream can take the
last slot in between.

So this covers what the route-level check cannot - that a caller refused at
registration is told so rather than dropped, that the loser of that race does not
linger in the registry it was refused from, and that an admitted stream hands its
slot back. Real registry, no mocks. Capacity is created by registering real
subscribers through the aggregator's production API, so the registry is genuinely
full rather than reported full.

The per-principal dimension is deliberately unrepresented here. This edge
authenticates one shared service token and derives no caller identity from it, so
there is no principal to key a quota on and no honest test to write for one.
"""

from __future__ import annotations

import pytest

from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus
from ..thread_stream import _stream_thread_events


def _occupy(aggregator: EventAggregator, count: int, *, prefix: str) -> None:
    """Register *count* real subscribers through the production registry API."""
    for index in range(count):
        aggregator.add_subscriber(f"{prefix}-{index}")


@pytest.mark.asyncio(loop_scope="function")
async def test_a_stream_refused_at_registration_is_told_why() -> None:
    """The registry's refusal reaches the SSE caller as a frame, not a dead socket.

    The route's pre-check and the registration it authorises are separated by the
    response-start boundary: the body generator does not run until the client
    begins reading, and another stream can take the last slot in between. The
    registry is therefore where the bound actually holds, and a caller that loses
    that race must learn why.

    Drives the real response generator against a genuinely full registry, which is
    precisely the state that race produces.
    """
    aggregator = EventAggregator()
    limit = domain_config.max_stream_connections
    _occupy(aggregator, limit, prefix="raced")

    frames = [
        frame
        async for frame in _stream_thread_events(
            aggregator=aggregator,
            thread_id="run-1",
            initial_status=ThreadStatus.RUNNING.value,
        )
    ]

    assert len(frames) == 1
    body = frames[0].decode("utf-8")
    assert "stream_rejected" in body
    assert "stream_limit_exceeded" in body
    # The loser of the race must not linger in the registry it was refused from.
    assert aggregator.subscriber_count() == limit


@pytest.mark.asyncio(loop_scope="function")
async def test_a_served_stream_gives_its_slot_back_and_spares_the_held_ones() -> None:
    """An admitted stream releases its slot, and refusing it disturbs nobody.

    The counterpart to the refusal case. A cap only stays meaningful if admitted
    streams hand their slots back, and a cap that shed EXISTING streams under
    load would turn a bounded resource into an outage for the callers that
    arrived first.
    """
    aggregator = EventAggregator()
    _occupy(aggregator, 2, prefix="held")
    before = aggregator.subscriber_count()

    frames = [
        frame
        async for frame in _stream_thread_events(
            aggregator=aggregator,
            thread_id="run-terminal",
            initial_status=ThreadStatus.COMPLETED.value,
        )
    ]

    assert len(frames) == 1
    assert "thread_terminal" in frames[0].decode("utf-8")
    assert aggregator.subscriber_count() == before
    assert aggregator.get_subscriber_queue("held-0") is not None
    assert aggregator.get_subscriber_queue("held-1") is not None
