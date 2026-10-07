"""Bounded delivery into a per-client relay queue.

A slow client must not stall the relay for everyone else, so each client owns a
bounded queue and a full queue evicts to make room. Two relay paths implemented
that rule independently - the server-sent-event subscriber registry and the
WebSocket connection manager - and a backpressure policy that exists twice will
eventually be two policies.

The drop is deliberate and lossy. A client that cannot keep up loses the oldest
events rather than the newest, because a viewer reconnecting mid-run is better
served by recent state than by a stale prefix, and recovery of what was dropped
comes from checkpoint re-projection rather than from the stream.

That reasoning holds for the progress events it was written about and fails for
two of them. A run's failure and its terminal are not stale prefix - they are the
outcome, they are emitted once, and nothing later restates them on this stream,
so a client that loses one under backpressure is left watching a run that never
appears to end. They are therefore evicted LAST rather than never: the bound is
what stops one slow client exhausting the process, so eviction always happens and
the queue never grows. What changed is only which entry yields.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, MutableSequence
from dataclasses import dataclass
from typing import Any, cast

from ..graph.enums import ServerEventType, StreamFrameKind
from ..thread.snapshots import wire_event_type

__all__ = [
    "PROTECTED_WIRE_TYPES",
    "DeliveryOutcome",
    "deliver_bounded",
    "is_protected_payload",
    "pop_oldest_droppable",
]

logger = logging.getLogger(__name__)

PROTECTED_WIRE_TYPES = frozenset(
    {ServerEventType.ERROR, StreamFrameKind.THREAD_TERMINAL}
)
"""Relayed frame types that outlive their queue position under backpressure.

Both state an outcome exactly once. Every other frame on this stream is either
repeated, superseded, or recoverable by re-reading authoritative state.
"""


def is_protected_payload(payload: object) -> bool:
    """Report whether *payload* is an outcome frame rather than progress.

    An outcome is recognised by its wire type, read under either key a relayed
    payload may carry it; anything that is not a wire mapping is ordinary
    progress.
    """
    if not isinstance(payload, Mapping):
        return False
    return wire_event_type(cast("Mapping[str, Any]", payload)) in PROTECTED_WIRE_TYPES


def pop_oldest_droppable[T](
    entries: MutableSequence[T], is_protected: Callable[[T], bool]
) -> T:
    """Remove and return the oldest entry *is_protected* does not shield.

    The one eviction rule for every bounded event buffer - the relay queues
    here and the worker's own outbound buffer - so which event a full buffer
    gives up is decided once rather than once per buffer. The survivors keep
    their order, because a consumer reads an error before the terminal that
    follows it.

    When every entry is protected the oldest still yields, since the
    alternative is an unbounded buffer and the bound is the whole point. That
    case needs a buffer holding nothing but errors and terminals, which is a
    saturated consumer rather than a normal one. *entries* must not be empty.
    """
    index = next(
        (position for position, entry in enumerate(entries) if not is_protected(entry)),
        0,
    )
    return entries.pop(index)


def _evict_one(queue: asyncio.Queue[Any]) -> bool:
    """Free exactly one slot in *queue*, under :func:`pop_oldest_droppable`.

    The common case is the old one and costs the same: the head is ordinary
    progress and is dropped where it stands. Only when the head is an outcome
    frame is the queue drained behind it, so the shared rule can choose, and
    the survivors are restored in their original order.
    """
    try:
        head = queue.get_nowait()
    except asyncio.QueueEmpty:
        # Another consumer drained it between the fullness check and this call,
        # so the queue has room and nothing was given up to make it.
        return False
    if not is_protected_payload(head):
        return True

    held: list[object] = [head]
    while True:
        try:
            held.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    pop_oldest_droppable(held, is_protected_payload)
    for item in held:
        queue.put_nowait(item)
    return True


@dataclass(frozen=True, slots=True)
class DeliveryOutcome:
    """What one bounded delivery did, including what it cost.

    ``delivered`` alone was not enough to answer the consumer's question. A drop
    under backpressure was reported to the operator's log and to nobody else, so
    a viewer's history simply lost entries with no indication it had: the stream
    read as a complete account of the run when it was not. ``dropped`` is that
    indication, and it is counted rather than flagged so a caller can coalesce a
    burst into one resynchronization notice instead of one per lost event.
    """

    delivered: bool
    dropped: int = 0

    def __bool__(self) -> bool:
        """Read as the delivery verdict, which is what every caller branches on."""
        return self.delivered


def deliver_bounded(
    queue: asyncio.Queue[Any],
    payload: object,
    *,
    client_id: str,
) -> DeliveryOutcome:
    """Put *payload* on *queue*, evicting the oldest droppable event when full.

    Args:
        queue: The client's bounded relay queue.
        payload: A pre-serialized event to deliver.
        client_id: Identifier used in the backpressure warnings.

    Returns:
        A :class:`DeliveryOutcome` saying whether the payload was enqueued and
        how many events this delivery cost the client.
    """
    dropped = 0
    if queue.full() and _evict_one(queue):
        dropped += 1
        logger.warning(
            "Dropped an event for slow client %s (relay backpressure, maxsize=%d)",
            client_id,
            queue.maxsize,
        )
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        logger.warning(
            "Relay event dropped for client %s - queue still full",
            client_id,
        )
        return DeliveryOutcome(delivered=False, dropped=dropped + 1)
    return DeliveryOutcome(delivered=True, dropped=dropped)
