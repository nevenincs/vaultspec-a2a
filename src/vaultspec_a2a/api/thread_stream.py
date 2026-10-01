"""Server-Sent Events body for a run's progress stream.

The generator and the response builder behind the versioned
``GET /v1/runs/{run_id}/stream`` verb. They live beside the gateway rather than
inside it because the verb's module is already large and this is a
self-contained streaming concern with no routing of its own.

Attachment order is the load-bearing part. The viewer is registered and
subscribed BEFORE the run's durable state is read, so an outcome relayed from
that moment on lands in this viewer's queue instead of falling between the read
and the subscription. The state read then leads the stream as a snapshot frame,
which is what lets a consumer tell "the run was already like this when I
arrived" from "this just happened". Neither the snapshot nor any later frame is
authoritative: they say where the run stood, and ``run-status`` says where it
stands.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..control.config import settings
from ..database import get_thread
from ..graph.enums import ServerEventType
from ..providers.conditions import ProviderCondition
from ..streaming.sse_frames import encode_sse_frame
from ..streaming.types import SequencedEvent
from ..thread.enums import TERMINAL_STATUS_VALUES, ThreadStatus
from ..thread.errors import EventAggregatorError
from .event_adapter import sequenced_to_positive_payload
from .schemas.events import HeartbeatEvent

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..streaming.aggregator import EventAggregator

logger = logging.getLogger(__name__)

__all__ = ["build_thread_stream_response"]

_UNRECORDED_REASON = "The run failed; no reason was recorded"
"""Stands in for a failed run whose durable row holds a condition and no reason.

Says what is true of the RECORD rather than inventing an account of the failure,
so a client is never handed a diagnosis nothing observed.
"""


@dataclass(frozen=True, slots=True)
class _DurableRunState:
    """The run's durable outcome fields, read whole and detached from the session."""

    status: str
    failure_reason: str | None
    provider_condition: str | None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUS_VALUES


async def _read_durable_state(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str
) -> _DurableRunState | None:
    """Read the run's durable state through a session that closes immediately.

    Short-lived by design. This runs inside the response body, and a session
    held across a stream would hold a pooled connection and its read transaction
    for as long as the viewer stayed attached - which is what made a handful of
    viewers able to exhaust the pool and stall every other request on the engine.
    """
    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
        if thread is None:
            return None
        return _DurableRunState(
            status=thread.status,
            failure_reason=thread.failure_reason,
            provider_condition=thread.provider_condition,
        )


def _queue_progress_payload(item: object) -> dict[str, object] | None:
    """Decode either producer shape held by the shared subscriber queue."""
    if isinstance(item, SequencedEvent):
        return sequenced_to_positive_payload(item)
    if isinstance(item, dict):
        return cast("dict[str, object]", item)
    return None


def _replay_is_served(aggregator: EventAggregator, thread_id: str) -> bool:
    """Whether this run's outgoing frames can be replayed to a reconnect.

    Two conditions, and both are about this gateway rather than this stream.
    The feature switch governs the whole mechanism. The run being NUMBERED is
    what says the switch was on when its frames crossed the fan-out: numbering
    and retention are bound together at the seat, so a numbered run is a
    retained one, and an unnumbered run's body still carries the worker's own
    counter - a number that restarts with its process and must never be offered
    back as a cursor.
    """
    if not settings.stream_replay_enabled:
        return False
    allocator = aggregator.sequence_allocator
    return allocator is not None and allocator.is_numbered(thread_id)


def _retained_sequence(payload: dict[str, object]) -> int | None:
    """Return the durable number a served frame carries, if it carries one."""
    sequence = payload.get("sequence")
    if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0:
        return sequence
    return None


def _snapshot_frame(thread_id: str, status: str) -> bytes:
    """The first frame of every stream: where the run stood at attachment."""
    return encode_sse_frame(
        {
            "type": "stream_snapshot",
            "event_type": "stream_snapshot",
            "thread_id": thread_id,
            "status": status,
        },
        event="stream_snapshot",
        thread_id=thread_id,
    )


def _backpressure_frame(thread_id: str, dropped: int) -> bytes:
    """Tell the consumer its own queue overflowed and by how much.

    A drop was reported only to the operator's log, so a viewer's history lost
    entries while still reading as a complete account of the run. This is the
    bounded resynchronization indication that replaces that silence: it names the
    cause and the count, and the consumer's remedy is always the same - re-read
    run-status, which is the authority these frames never were.
    """
    return encode_sse_frame(
        {
            "type": "progress_dropped",
            "event_type": "progress_dropped",
            "thread_id": thread_id,
            "reason": "backpressure",
            "dropped_count": dropped,
        },
        event="progress_dropped",
        thread_id=thread_id,
    )


def _rejection_frame(thread_id: str, reason: str) -> bytes:
    """Close a stream that cannot be served, in the client's own vocabulary."""
    return encode_sse_frame(
        {
            "type": "stream_rejected",
            "event_type": "stream_rejected",
            "thread_id": thread_id,
            "reason": reason,
        },
        event="stream_rejected",
        thread_id=thread_id,
    )


def _terminal_replay_frames(thread_id: str, state: _DurableRunState) -> Iterator[bytes]:
    """Replay the durable error and terminal in the same order as live delivery.

    A condition without a recorded reason gets a truthful fallback message;
    the already ended run cannot be retried from this frame.
    """
    if state.status == ThreadStatus.FAILED.value and (
        state.failure_reason or state.provider_condition
    ):
        yield encode_sse_frame(
            {
                "type": "error",
                "event_type": "error",
                "thread_id": thread_id,
                "code": state.provider_condition or ProviderCondition.UNKNOWN.value,
                "message": state.failure_reason or _UNRECORDED_REASON,
                "recoverable": False,
            },
            event="error",
            thread_id=thread_id,
        )
    terminal: dict[str, object] = {
        "type": "thread_terminal",
        "event_type": "thread_terminal",
        "thread_id": thread_id,
        "status": state.status,
        "replay": True,
    }
    if state.failure_reason:
        terminal["error_detail"] = state.failure_reason
    yield encode_sse_frame(terminal, event="thread_terminal", thread_id=thread_id)


def _resync_frames(
    aggregator: EventAggregator, client_id: str, thread_id: str
) -> Iterator[bytes]:
    """Emit one backpressure notice covering everything dropped since the last."""
    dropped = aggregator.take_dropped_count(client_id)
    if dropped:
        logger.warning(
            "Stream %s lost %d events to backpressure on thread %s",
            client_id,
            dropped,
            thread_id,
            extra={
                "client_id": client_id,
                "thread_id": thread_id,
                "action": "stream_backpressure_resync",
                "dropped": dropped,
            },
        )
        yield _backpressure_frame(thread_id, dropped)


async def _stream_thread_events(
    *,
    aggregator: EventAggregator,
    thread_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[bytes]:
    """Yield thread-scoped events from the shared subscriber queue as SSE."""
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
        yield _rejection_frame(thread_id, "stream_limit_exceeded")
        return

    start_time = time.monotonic()

    # Registration and its cleanup guard open together, deliberately. The client
    # holds one of the gateway's bounded stream slots from the moment
    # ``add_subscriber`` returns, so every statement that follows must sit inside
    # the ``finally`` that gives the slot back - a raise between the two would
    # strand the registration for the life of the process.
    try:
        aggregator.subscribe(client_id, [thread_id])

        # Authority is read only now. Before, it was read first and the
        # subscription attached after, so an outcome relayed in between reached
        # neither: the read was too early to see it and the queue too late to
        # receive it, and the viewer heartbeated over a run that had ended.
        state = await _read_durable_state(session_factory, thread_id)
        if state is None:
            # The run existed when the route answered and does not now.
            yield _rejection_frame(thread_id, "run_not_found")
            return

        yield _snapshot_frame(thread_id, state.status)

        if state.terminal:
            for frame in _terminal_replay_frames(thread_id, state):
                yield frame
            return

        while True:
            try:
                item = await asyncio.wait_for(
                    queue.get(),
                    timeout=settings.stream_heartbeat_interval_seconds,
                )
            except TimeoutError:
                for frame in _resync_frames(aggregator, client_id, thread_id):
                    yield frame
                # An idle beat is also where a run that ended without this
                # viewer hearing about it is caught. The relay fans out before
                # it persists, so a terminal delivered in that gap belongs to
                # neither side; re-reading here bounds how long such a stream can
                # heartbeat over a finished run to one beat, rather than forever.
                settled = await _read_durable_state(session_factory, thread_id)
                if settled is not None and settled.terminal:
                    for frame in _terminal_replay_frames(thread_id, settled):
                        yield frame
                    return
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

            for frame in _resync_frames(aggregator, client_id, thread_id):
                yield frame

            # In-process events are projected onto the positive progress
            # allowlist here; relayed worker payloads were already projected
            # at the relay seam. The encode boundary re-applies the allowlist
            # to both, so a forbidden body cannot cross by either path.
            # Local domain events carry sequence wrappers; worker relay events
            # have already crossed the positive projection as plain mappings.
            payload = _queue_progress_payload(item)
            if payload is None:
                continue

            event_type = payload.get("type")
            # Read per frame rather than once at attachment: a run reaches its
            # numbering on its first relayed batch, which can land after a
            # viewer has already subscribed and been handed its snapshot.
            sequence = (
                _retained_sequence(payload)
                if _replay_is_served(aggregator, thread_id)
                else None
            )
            yield encode_sse_frame(
                payload,
                event=str(event_type) if isinstance(event_type, str) else None,
                thread_id=thread_id,
                sequence=sequence,
            )
            if event_type == "thread_terminal":
                return
    finally:
        aggregator.remove_subscriber(client_id)


async def build_thread_stream_response(
    *,
    db: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    aggregator: EventAggregator,
    thread_id: str,
    not_found_detail: str = "Thread not found",
) -> StreamingResponse:
    """Build the SSE ``StreamingResponse`` for a thread, or raise a 404.

    The single code path behind the versioned ``/v1/runs/{run_id}/stream`` verb
    (a run id is the thread id). Callers pass ``not_found_detail`` so the 404
    speaks their own resource vocabulary.

    *db* answers the one question that must be settled before the response
    starts - does this run exist - and is the caller's request-scoped session.
    *session_factory* is what the body then reads authority through, in sessions
    of its own that close as soon as each read is done, because the body outlives
    the request scope.
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
            session_factory=session_factory,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
