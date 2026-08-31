"""Server-Sent Events body for a run's progress stream.

The generator and the response builder behind the versioned
``GET /v1/runs/{run_id}/stream`` verb. They live beside the gateway rather than
inside it because the verb's module is already large and this is a
self-contained streaming concern with no routing of its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..control.config import settings
from ..database import get_thread
from ..graph.enums import ServerEventType
from ..providers.conditions import ProviderCondition
from ..streaming.sse_frames import encode_sse_frame
from ..streaming.types import SequencedEvent
from ..thread.enums import TERMINAL_STATUSES, ThreadStatus
from ..thread.errors import EventAggregatorError
from ..thread.snapshots import normalize_wire_event_type
from .event_adapter import sequenced_to_positive_payload
from .schemas.events import HeartbeatEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..streaming.aggregator import EventAggregator

logger = logging.getLogger(__name__)

__all__ = ["build_thread_stream_response"]

_UNRECORDED_REASON = "The run failed; no reason was recorded"
"""Stands in for a failed run whose durable row holds a condition and no reason.

Says what is true of the RECORD rather than inventing an account of the failure,
so a client is never handed a diagnosis nothing observed.
"""


async def _stream_thread_events(
    *,
    aggregator: EventAggregator,
    thread_id: str,
    initial_status: str,
    failure_reason: str | None = None,
    provider_condition: str | None = None,
) -> AsyncIterator[bytes]:
    """Yield thread-scoped events from the shared subscriber queue as SSE.

    *failure_reason* and *provider_condition* are the durable columns of the run
    being attached to, and they matter only on the replay path: a client that
    attaches after the run has already ended receives no live frames at all, so
    whatever the replay does not say is lost to it.
    """
    client_id = f"sse-{uuid4()}"
    try:
        queue = aggregator.add_subscriber(client_id)
    except EventAggregatorError:
        # The route refuses at capacity before the thread lookup, but that check
        # and this registration are separated by the response-start boundary:
        # this generator does not run until the client begins reading the body.
        # A concurrent stream can take the last slot in between, so the
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
            # A run that failed before this client attached gets the same pair of
            # frames a live client saw, in the same order and shape: the coded
            # error first, then the terminal carrying the reason. Replaying only
            # the terminal told a reconnecting client "failed" and nothing else,
            # while the durable row held both halves of the answer the whole
            # time. The condition rides the error frame's code exactly as it does
            # live, rather than widening the terminal frame to carry it twice.
            if initial_status == ThreadStatus.FAILED.value and (
                failure_reason or provider_condition
            ):
                yield encode_sse_frame(
                    {
                        "type": "error",
                        "event_type": "error",
                        "thread_id": thread_id,
                        # The floor stands in for a row written before the
                        # condition column existed; the reason is still true.
                        "code": provider_condition or ProviderCondition.UNKNOWN.value,
                        "message": failure_reason or _UNRECORDED_REASON,
                        # The run is already over, so nothing about it can be
                        # retried - whatever recoverability meant while it ran.
                        "recoverable": False,
                    },
                    event="error",
                    thread_id=thread_id,
                )
            terminal: dict[str, object] = {
                "type": "thread_terminal",
                "event_type": "thread_terminal",
                "thread_id": thread_id,
                "status": initial_status,
                "replay": True,
            }
            if failure_reason:
                terminal["error_detail"] = failure_reason
            yield encode_sse_frame(
                terminal,
                event="thread_terminal",
                thread_id=thread_id,
            )
            return

        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(),
                    timeout=settings.stream_heartbeat_interval_seconds,
                )
            except TimeoutError:
                heartbeat = HeartbeatEvent(
                    timestamp=datetime.now(UTC),
                    server_uptime_seconds=time.monotonic() - start_time,
                )
                yield encode_sse_frame(
                    heartbeat.model_dump(mode="json"),
                    event=ServerEventType.HEARTBEAT,
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

    The single code path behind the versioned ``/v1/runs/{run_id}/stream`` verb
    (a run id is the thread id). Callers pass ``not_found_detail`` so the 404
    speaks their own resource vocabulary.
    """
    # Refused before the thread lookup, deliberately. The limit exists to stop a
    # caller exhausting queues and delivery tasks, so it must be decided from
    # process-local state rather than after a database round trip that the same
    # flood would also multiply. It says nothing about the request's identity or
    # its target - only that this process is already at capacity.
    #
    # This is the cheap early refusal, not the bound itself: registration happens
    # once the response body starts, and the shared subscriber registry enforces
    # the same limit at the moment of registration, which is where it holds.
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
            failure_reason=thread.failure_reason,
            provider_condition=thread.provider_condition,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
