"""GET /threads/{thread_id}/stream -- Server-Sent Events for thread activity."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ...control.config import settings
from ...database.session import get_db
from ...database.thread_repository import get_thread
from ...streaming.aggregator import EventAggregator, SequencedEvent
from ...streaming.sse_frames import encode_sse_frame
from ...thread.enums import TERMINAL_STATUSES
from ...thread.errors import EventAggregatorError
from ...thread.snapshots import normalize_wire_event_type
from ..dependencies import get_aggregator
from ..event_adapter import sequenced_to_positive_payload
from ..schemas.events import HeartbeatEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()


async def _stream_thread_events(
    *,
    aggregator: EventAggregator,
    thread_id: str,
    initial_status: str,
) -> AsyncIterator[bytes]:
    """Yield thread-scoped events from the shared subscriber queue as SSE."""
    client_id = f"sse-{uuid4()}"
    try:
        queue = aggregator.add_subscriber(client_id)
    except EventAggregatorError:
        # The route refuses at capacity before the thread lookup, but that check
        # and this registration are separated by the response-start boundary:
        # this generator does not run until the client begins reading the body.
        # Other callers - including the event WebSocket, which shares the same
        # subscriber registry - can take the last slot in between. So the
        # registry's own refusal is authoritative, and the caller learns of it as
        # a terminal frame rather than a connection that dies mid-response.
        logger.warning(
            "Refused SSE stream for thread %s: subscriber registry at capacity",
            thread_id,
            extra={
                "client_id": client_id,
                "thread_id": thread_id,
                "action": "stream_refused",
            },
        )
        yield encode_sse_frame(
            {
                "type": "stream_rejected",
                "event_type": "stream_rejected",
                "thread_id": thread_id,
                "reason": "stream_limit_exceeded",
            },
            event="stream_rejected",
            thread_id=thread_id,
        )
        return

    start_time = time.monotonic()

    # Registration and its cleanup guard open together, deliberately. The client
    # holds one of the gateway's bounded stream slots from the moment
    # ``add_subscriber`` returns, so every statement that follows must sit inside
    # the ``finally`` that gives the slot back - a raise between the two would
    # strand the registration for the life of the process.
    try:
        aggregator.subscribe(client_id, [thread_id])

        if initial_status in TERMINAL_STATUSES:
            yield encode_sse_frame(
                {
                    "type": "thread_terminal",
                    "event_type": "thread_terminal",
                    "thread_id": thread_id,
                    "status": initial_status,
                    "replay": True,
                },
                event="thread_terminal",
                thread_id=thread_id,
            )
            return

        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(),
                    timeout=settings.ws_heartbeat_interval_seconds,
                )
            except TimeoutError:
                heartbeat = HeartbeatEvent(
                    timestamp=datetime.now(UTC),
                    server_uptime_seconds=time.monotonic() - start_time,
                )
                yield encode_sse_frame(
                    heartbeat.model_dump(mode="json"),
                    event="heartbeat",
                    thread_id=thread_id,
                )
                continue

            if isinstance(item, SequencedEvent):
                # In-process events are projected onto the positive progress
                # allowlist here; relayed worker payloads were already projected
                # at the relay seam. The encode boundary re-applies the allowlist
                # to both, so a forbidden body cannot cross by either path.
                payload = sequenced_to_positive_payload(item)
            else:
                payload = normalize_wire_event_type(item)

            event_type = payload.get("type")
            yield encode_sse_frame(
                payload,
                event=str(event_type) if isinstance(event_type, str) else None,
                thread_id=thread_id,
            )
            if event_type == "thread_terminal":
                return
    finally:
        aggregator.remove_subscriber(client_id)


async def build_thread_stream_response(
    *,
    db: AsyncSession,
    aggregator: EventAggregator,
    thread_id: str,
    not_found_detail: str = "Thread not found",
) -> StreamingResponse:
    """Build the SSE ``StreamingResponse`` for a thread, or raise a 404.

    The single code path behind both the internal ``/api/threads/{id}/stream``
    route and the versioned ``/v1/runs/{run_id}/stream`` gateway verb: the run
    surface reuses this verbatim (a run id is the thread id), so the public edge
    re-serves the same bounded, versioned v1 progress frames without a second
    implementation. Callers pass ``not_found_detail`` to speak their own resource
    vocabulary in the 404.
    """
    # Refused before the thread lookup, deliberately. The limit exists to stop a
    # caller exhausting queues and delivery tasks, so it must be decided from
    # process-local state rather than after a database round trip that the same
    # flood would also multiply. It says nothing about the request's identity or
    # its target - only that this process is already at capacity.
    #
    # This is the cheap early refusal, not the bound itself: registration happens
    # once the response body starts, and the subscriber registry is shared with
    # the event WebSocket. The registry enforces the same limit at the moment of
    # registration, which is where it actually holds.
    limit = settings.max_stream_connections
    if limit > 0 and aggregator.subscriber_count() >= limit:
        raise HTTPException(
            status_code=503,
            detail=("Gateway is at its progress-stream connection limit; retry later"),
            headers={"Retry-After": "5"},
        )

    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=not_found_detail)

    return StreamingResponse(
        _stream_thread_events(
            aggregator=aggregator,
            thread_id=thread_id,
            initial_status=thread.status,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/threads/{thread_id}/stream")
async def stream_thread_events(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
) -> StreamingResponse:
    """Stream thread events over SSE for clients that do not use WebSockets."""
    return await build_thread_stream_response(
        db=db, aggregator=aggregator, thread_id=thread_id
    )
