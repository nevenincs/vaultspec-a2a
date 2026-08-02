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
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from ..graph.events import ErrorOccurred

if TYPE_CHECKING:
    from .types import SequencedEvent

__all__ = ["deliver_bounded"]

logger = logging.getLogger(__name__)

_PROTECTED_WIRE_TYPES = frozenset({"error", "thread_terminal"})
"""Relayed frame types that outlive their queue position under backpressure.

Both state an outcome exactly once. Every other frame on this stream is either
repeated, superseded, or recoverable by re-reading authoritative state.
"""


def _is_protected(payload: object) -> bool:
    """Report whether *payload* is an outcome frame rather than progress.

    Handles both shapes that cross this queue: the relayed worker payloads,
    which are already wire dictionaries, and the in-process domain events, which
    are not yet projected onto the wire vocabulary and so are recognised by their
    own type instead of by a string they do not yet carry.
    """
    if isinstance(payload, Mapping):
        return cast("Mapping[str, object]", payload).get("type") in (
            _PROTECTED_WIRE_TYPES
        )
    return isinstance(getattr(payload, "event", None), ErrorOccurred)


def _evict_one(queue: asyncio.Queue[Any]) -> bool:
    """Free exactly one slot, taking the oldest droppable entry.

    The common case is the old one and costs the same: the head is ordinary
    progress and is dropped where it stands. Only when the head is an outcome
    frame does this scan behind it, and it restores the survivors in their
    original order because a consumer reads an error before the terminal that
    follows it.

    When every buffered entry is an outcome frame the oldest still yields, since
    the alternative is an unbounded queue and the bound is the whole point of
    this module. That case needs a queue holding nothing but errors and
    terminals, which is a saturated client rather than a normal one.
    """
    try:
        head = queue.get_nowait()
    except asyncio.QueueEmpty:
        # Another consumer drained it between the fullness check and this call,
        # so the queue has room and nothing was given up to make it.
        return False
    if not _is_protected(head):
        return True

    held: list[object] = [head]
    evicted = False
    while True:
        try:
            item = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if not evicted and not _is_protected(item):
            evicted = True
            continue
        held.append(item)
    if not evicted:
        held.pop(0)
    for item in held:
        queue.put_nowait(cast("SequencedEvent", item))
    return True


def deliver_bounded(
    queue: asyncio.Queue[Any],
    payload: object,
    *,
    client_id: str,
    log_extra: dict[str, object] | None = None,
) -> bool:
    """Put *payload* on *queue*, evicting the oldest droppable event when full.

    Args:
        queue: The client's bounded relay queue.
        payload: A pre-serialized event to deliver.
        client_id: Identifier used in the backpressure warnings.
        log_extra: Structured logging fields. Callers that carry richer context -
            a thread identifier, a bounded action name - pass it here so the two
            relay paths can log at different fidelity without forking the policy
            they share.

    Returns:
        ``True`` when the payload was enqueued, ``False`` when it was dropped
        because the queue remained full even after an eviction.
    """
    extra = log_extra or {}
    if queue.full() and _evict_one(queue):
        logger.warning(
            "Dropped an event for slow client %s (relay backpressure, maxsize=%d)",
            client_id,
            queue.maxsize,
            extra={**extra, "action": "relay_drop_oldest"} if extra else None,
        )
    try:
        queue.put_nowait(cast("SequencedEvent", payload))
    except asyncio.QueueFull:
        logger.warning(
            "Relay event dropped for client %s - queue still full",
            client_id,
            extra={**extra, "action": "relay_drop_event"} if extra else None,
        )
        return False
    return True
