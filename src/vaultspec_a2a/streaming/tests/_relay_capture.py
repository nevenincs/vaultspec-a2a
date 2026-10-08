"""What a producer hands its relay, captured through its broadcast hook.

The broadcast hook is the seam the worker relays every event through, so a
capture seated on it holds exactly what the gateway would receive. A test reads
it as a list when it wants every event in order, and as a queue filtered to some
runs when it drains events as the relay would deliver them.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..aggregator import RunEventProducer
    from ..types import SequencedEvent

__all__ = ["relayed_events", "relayed_queue"]


def relayed_events(producer: RunEventProducer) -> list[SequencedEvent]:
    """Collect every event *producer* hands its relay, in order."""
    received: list[SequencedEvent] = []

    async def _capture(sequenced: SequencedEvent) -> None:
        received.append(sequenced)

    producer.add_broadcast_hook(_capture)
    return received


def relayed_queue(
    producer: RunEventProducer, *thread_ids: str
) -> asyncio.Queue[SequencedEvent]:
    """Queue what *producer* hands its relay for *thread_ids*, in order."""
    queue: asyncio.Queue[SequencedEvent] = asyncio.Queue()

    async def _capture(sequenced: SequencedEvent) -> None:
        if sequenced.event.thread_id in thread_ids:
            queue.put_nowait(sequenced)

    producer.add_broadcast_hook(_capture)
    return queue
