"""Bounded delivery into a per-client relay queue.

A slow client must not stall the relay for everyone else, so each client owns a
bounded queue and a full queue drops its oldest event to make room. Two relay
paths implemented that rule independently - the server-sent-event subscriber
registry and the WebSocket connection manager - and a backpressure policy that
exists twice will eventually be two policies.

The drop is deliberate and lossy. A client that cannot keep up loses the oldest
events rather than the newest, because a viewer reconnecting mid-run is better
served by recent state than by a stale prefix, and recovery of what was dropped
comes from checkpoint re-projection rather than from the stream.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from .types import SequencedEvent

__all__ = ["deliver_bounded"]

logger = logging.getLogger(__name__)


def deliver_bounded(
    queue: asyncio.Queue[Any],
    payload: object,
    *,
    client_id: str,
    log_extra: dict[str, object] | None = None,
) -> bool:
    """Put *payload* on *queue*, dropping the oldest event when it is full.

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
        because the queue remained full even after evicting its oldest entry.
    """
    extra = log_extra or {}
    if queue.full():
        try:
            queue.get_nowait()
            logger.warning(
                "Dropped oldest event for slow client %s "
                "(relay backpressure, maxsize=%d)",
                client_id,
                queue.maxsize,
                extra={**extra, "action": "relay_drop_oldest"} if extra else None,
            )
        except asyncio.QueueEmpty:
            # Another consumer drained it between the check and the get; the
            # queue now has room, so there is nothing to report.
            pass
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
