"""GET /threads/{thread_id}/stream -- Server-Sent Events for thread activity."""

from __future__ import annotations

import asyncio
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
from ..dependencies import get_aggregator
from ..event_adapter import sequenced_to_wire
from ..schemas.events import HeartbeatEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _normalize_payload(payload: dict[str, object]) -> dict[str, object]:
    """Normalize non-schema relay payloads onto the SSE event surface."""
    if "type" in payload:
        return payload

    raw_type = payload.get("event_type")
    if isinstance(raw_type, str) and raw_type:
        normalized = dict(payload)
        normalized["type"] = raw_type
        return normalized

    return payload


async def _stream_thread_events(
    *,
    aggregator: EventAggregator,
    thread_id: str,
    initial_status: str,
) -> AsyncIterator[bytes]:
    """Yield thread-scoped events from the shared subscriber queue as SSE."""
    client_id = f"sse-{uuid4()}"
    queue = aggregator.add_subscriber(client_id)
    aggregator.subscribe(client_id, [thread_id])
    start_time = time.monotonic()

    try:
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
                payload = sequenced_to_wire(item).model_dump(mode="json")
            else:
                payload = _normalize_payload(item)

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
