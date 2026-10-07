"""Server-Sent Events body for a run's progress stream.

The generator and the response builder behind the versioned
``GET /v1/runs/{run_id}/stream`` verb. They live beside the gateway rather than
inside it because the verb's module is already large and this is a
self-contained streaming concern with no routing of its own. What a resume can
be served from - the cursor, the retained window, the reason a window is short -
is answered next door in ``_stream_replay``; this module decides what to emit
and in what order.

Attachment order is the load-bearing part. The viewer is registered and
subscribed BEFORE the run's durable state is read, so an outcome relayed from
that moment on lands in this viewer's queue instead of falling between the read
and the subscription. The state read then leads the stream as a snapshot frame,
which is what lets a consumer tell "the run was already like this when I
arrived" from "this just happened". Neither the snapshot nor any later frame is
authoritative: they say where the run stood, and ``run-status`` says where it
stands.

A reconnecting viewer may offer the id it last received as a resumption cursor,
and the snapshot still leads: the retained frames after the cursor follow it,
and only then does the stream go live. The subscription is attached before any
of that, which is what makes the handover seamless and also what makes the
de-duplication below necessary.

The phases run in one fixed order and :class:`_ThreadStream` holds the little
state they share: resolve the cursor, attach, snapshot, replay, then either the
durable terminal or the live loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..control.config import settings
from ..database import get_thread
from ..domain_config import domain_config
from ..graph.enums import ServerEventType, StreamFrameKind
from ..providers.conditions import ProviderCondition
from ..streaming.sse_frames import encode_sse_frame, transport_frame
from ..thread.enums import TERMINAL_STATUS_VALUES, ThreadStatus
from ..thread.errors import StreamSubscriptionError
from ._stream_replay import (
    replay_is_served,
    replay_window,
    resume_position,
    retained_sequence,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..streaming import RelayHub
    from ..streaming.run_event_writer import RunEventWriter
    from ._stream_replay import ReplayFrame, ResumePosition

logger = logging.getLogger(__name__)

__all__ = [
    "ThreadStreamRequest",
    "build_thread_stream_response",
    "offered_resume_cursor",
]

_UNRECORDED_REASON = "The run failed; no reason was recorded"
"""Stands in for a failed run whose durable row holds a condition and no reason.

Says what is true of the RECORD rather than inventing an account of the failure,
so a client is never handed a diagnosis nothing observed.
"""

_FOREIGN_RUN_REASON = "resume_cursor_foreign_run"

_IDLE_BEAT: Final = object()
"""Stands in for a queued event when the heartbeat interval elapses instead.

A private object no producer can put on a queue, so the live loop can tell
"nothing arrived in time" from any event that did without a second return
value or an exception crossing a phase boundary.
"""


@dataclass(frozen=True, slots=True)
class ThreadStreamRequest:
    """One viewer's request for a run's progress stream, and what serves it.

    A parameter object rather than a long keyword list: these values travel
    together from the route into a response body that outlives the request
    scope, and splitting them across call sites is what made the builder's
    signature grow past what a reader can hold.

    *session_factory* is what the body reads authority through, in sessions of
    its own that close as soon as each read is done, because the body outlives
    the request scope. *resume_cursor* is the id a reconnecting viewer last
    received, already resolved from the request by :func:`offered_resume_cursor`;
    it is carried into the body rather than acted on at the edge, because a
    cursor this run cannot honour is answered with a typed frame on a 200
    stream, not an HTTP error - the client that sends one is an ``EventSource``
    that would otherwise see only a failed connection. *replay_writer* is the
    gateway's seated recorder, read rather than created: it holds the newest
    frames the replay table does not have yet, so a resume taken between an
    allocation and its flush still sees them. A caller with none - a host
    embedding this stream without the relay - serves the table alone.
    *not_found_detail* lets a caller's 404 speak its own resource vocabulary.
    """

    thread_id: str
    aggregator: RelayHub
    session_factory: async_sessionmaker[AsyncSession]
    resume_cursor: str | None = None
    replay_writer: RunEventWriter | None = None
    not_found_detail: str = "Thread not found"


def offered_resume_cursor(header: str | None, query: str | None) -> str | None:
    """Return the resumption cursor a request offers, or ``None`` for none.

    The ``Last-Event-ID`` header is what a conforming SSE client re-sends by
    itself, so it wins; the query parameter exists because the browser
    ``EventSource`` constructor cannot set a header, and a caller driving
    resumption by hand needs some way in. An empty value on either is no
    cursor: a client whose stored id is the empty string sends no position.
    """
    for offered in (header, query):
        if offered is not None and (cursor := offered.strip()):
            return cursor
    return None


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
    """Narrow a queued item to the relayed wire mapping the gateway enqueues."""
    if isinstance(item, dict):
        return cast("dict[str, object]", item)
    return None


def _snapshot_frame(thread_id: str, status: str) -> bytes:
    """The first frame of every stream: where the run stood at attachment."""
    return transport_frame(StreamFrameKind.STREAM_SNAPSHOT, thread_id, status=status)


def _backpressure_frame(thread_id: str, dropped: int) -> bytes:
    """Tell the consumer its own queue overflowed and by how much.

    A drop was reported only to the operator's log, so a viewer's history lost
    entries while still reading as a complete account of the run. This is the
    bounded resynchronization indication that replaces that silence: it names the
    cause and the count, and the consumer's remedy is always the same - re-read
    run-status, which is the authority these frames never were.
    """
    return transport_frame(
        StreamFrameKind.PROGRESS_DROPPED,
        thread_id,
        reason="backpressure",
        dropped_count=dropped,
    )


def _replay_gap_frame(thread_id: str, reason: str, first_sequence: int | None) -> bytes:
    """Say that a resume is short, and where the stream picks up again.

    The same bounded resynchronization indication as a backpressure drop, with
    the same remedy - re-read run-status - because the consequence for the
    consumer is the same: its history of this run has a hole in it. It carries
    no id of its own; the position a client resumes from is the next retained
    frame, not the notice that something before it is missing.
    """
    fields: dict[str, object] = {"reason": reason}
    if first_sequence is not None:
        fields["first_sequence"] = first_sequence
    return transport_frame(StreamFrameKind.PROGRESS_DROPPED, thread_id, **fields)


def _rejection_frame(thread_id: str, reason: str) -> bytes:
    """Close a stream that cannot be served, in the client's own vocabulary."""
    return transport_frame(StreamFrameKind.STREAM_REJECTED, thread_id, reason=reason)


def _terminal_replay_frames(thread_id: str, state: _DurableRunState) -> Iterator[bytes]:
    """Replay the durable error and terminal in the same order as live delivery.

    A condition without a recorded reason gets a truthful fallback message;
    the already ended run cannot be retried from this frame.
    """
    if state.status == ThreadStatus.FAILED.value and (
        state.failure_reason or state.provider_condition
    ):
        yield transport_frame(
            ServerEventType.ERROR,
            thread_id,
            code=state.provider_condition or ProviderCondition.UNKNOWN.value,
            message=state.failure_reason or _UNRECORDED_REASON,
            recoverable=False,
        )
    terminal: dict[str, object] = {"status": state.status, "replay": True}
    if state.failure_reason:
        terminal["error_detail"] = state.failure_reason
    yield transport_frame(StreamFrameKind.THREAD_TERMINAL, thread_id, **terminal)


def _replay_frame_bytes(thread_id: str, frame: ReplayFrame) -> bytes:
    """Encode one retained frame exactly as its live delivery was encoded.

    Including the id: a replayed frame is retained by definition, so the
    position it names is one the next reconnect can resume from too.
    """
    return encode_sse_frame(
        frame.body,
        event=frame.event_type or None,
        thread_id=thread_id,
        sequence=frame.sequence,
    )


class _ThreadStream:
    """One viewer's attachment to a run, served as an ordered run of SSE frames.

    Holds what the phases share and nothing else: the registry id this viewer
    occupies a slot under, the moment it was admitted, the de-duplication mark
    that the replay and the live loop both move, and the flag that says a
    terminal has already been served. Each phase below is one step of the fixed
    order, and the shared mark is why they are methods rather than free
    functions threading four values between them.
    """

    __slots__ = ("_client_id", "_closed", "_highest_emitted", "_request", "_start_time")

    def __init__(self, request: ThreadStreamRequest) -> None:
        self._request = request
        self._client_id = f"sse-{uuid4()}"
        self._start_time = 0.0
        # The highest sequence this connection may treat as already held. It is
        # what makes the early subscription safe: the queue collects frames
        # while the replay reads them, so the same sequence can arrive twice
        # and only the first delivery counts.
        #
        # It starts at zero and is raised only by the replay, which clamps the
        # client's cursor to a position the run has actually produced. Taking
        # the cursor on trust instead let a client silence its own stream: a
        # resume at a number the run had never reached dropped every live frame
        # at or below it, which is every frame the run would ever send.
        self._highest_emitted = 0
        self._closed = False

    @property
    def _thread_id(self) -> str:
        return self._request.thread_id

    @property
    def _aggregator(self) -> RelayHub:
        return self._request.aggregator

    async def frames(self) -> AsyncGenerator[bytes]:
        """Every frame this viewer is served, in order, from cursor to close."""
        cursor = self._request.resume_cursor
        resume = None if cursor is None else resume_position(cursor, self._thread_id)
        if cursor is not None and resume is None:
            yield self._cursor_refusal()
            return
        queue = self._attach()
        if queue is None:
            yield _rejection_frame(self._thread_id, "stream_limit_exceeded")
            return
        async for frame in self._serve(resume, queue):
            yield frame

    def release(self) -> None:
        """Give the registry slot back, whether or not one was ever taken.

        Unregistering is a pop, so releasing an id that never registered - a
        refused cursor, or a registration that lost the capacity race - removes
        nothing and disturbs no other viewer.
        """
        self._aggregator.remove_subscriber(self._client_id)

    def _cursor_refusal(self) -> bytes:
        """Refuse a cursor this run cannot honour, before anything is attached.

        A cursor this stream cannot honour is a property of the request alone,
        and replaying another run's history to satisfy it would be worse than
        refusing: the caller would receive frames of a run it never asked
        about, under ids it would then resume from.
        """
        logger.warning(
            "Refused SSE stream for thread %s: resumption cursor names "
            "another run or no position at all",
            self._thread_id,
            extra={
                "client_id": self._client_id,
                "thread_id": self._thread_id,
                "action": "stream_resume_refused",
            },
        )
        return _rejection_frame(self._thread_id, _FOREIGN_RUN_REASON)

    def _attach(self) -> asyncio.Queue[Any] | None:
        """Take one of the gateway's bounded stream slots, or ``None`` at capacity.

        The route refuses at capacity before the thread lookup, but that check
        and this registration are separated by the response-start boundary: the
        body does not run until the client begins reading it. A concurrent
        stream can take the last slot in between, so the registry's own refusal
        is authoritative, and the caller learns of it as a terminal frame
        rather than a connection that dies mid-response.
        """
        try:
            queue = self._aggregator.add_subscriber(self._client_id)
        except StreamSubscriptionError:
            logger.warning(
                "Refused SSE stream for thread %s: subscriber registry at capacity",
                self._thread_id,
                extra={
                    "client_id": self._client_id,
                    "thread_id": self._thread_id,
                    "action": "stream_refused",
                },
            )
            return None
        self._start_time = time.monotonic()
        return queue

    async def _serve(
        self, resume: ResumePosition | None, queue: asyncio.Queue[Any]
    ) -> AsyncGenerator[bytes]:
        """Snapshot, replay, then either the durable terminal or the live loop."""
        self._aggregator.subscribe(self._client_id, [self._thread_id])

        # Authority is read only now. Before, it was read first and the
        # subscription attached after, so an outcome relayed in between reached
        # neither: the read was too early to see it and the queue too late to
        # receive it, and the viewer heartbeated over a run that had ended.
        state = await _read_durable_state(
            self._request.session_factory, self._thread_id
        )
        if state is None:
            # The run existed when the route answered and does not now.
            yield _rejection_frame(self._thread_id, "run_not_found")
            return

        yield _snapshot_frame(self._thread_id, state.status)

        if resume is not None:
            async for frame in self._replayed(resume):
                yield frame
        if self._closed:
            return

        if state.terminal:
            for frame in _terminal_replay_frames(self._thread_id, state):
                yield frame
            return

        async for frame in self._live(queue):
            yield frame

    async def _replayed(self, resume: ResumePosition) -> AsyncGenerator[bytes]:
        """Serve what the retained window holds, and say once when it is short."""
        window = await replay_window(
            session_factory=self._request.session_factory,
            writer=self._request.replay_writer,
            thread_id=self._thread_id,
            resume=resume,
        )
        self._highest_emitted = window.dedup_floor
        if window.gap_reason is not None:
            # Exactly one notice, ahead of the frames it qualifies, so
            # everything after it is contiguous. A short replay is never
            # presented as a complete one.
            self._log_resume_gap(window.gap_reason)
            yield _replay_gap_frame(
                self._thread_id, window.gap_reason, window.first_sequence
            )
        for frame in window.frames:
            yield _replay_frame_bytes(self._thread_id, frame)
            self._highest_emitted = frame.sequence
            if frame.event_type == StreamFrameKind.THREAD_TERMINAL:
                # The run ended inside the replayed window. Closing on the
                # retained frame rather than on the durable terminal keeps the
                # terminal's own sequence in the delivered set, so the union
                # across both connections has no hole at its last position.
                self._closed = True
                return

    def _log_resume_gap(self, reason: str) -> None:
        """Record which of the two short-replay reasons this resume took."""
        logger.info(
            "Resume of run %s is short: %s",
            self._thread_id,
            reason,
            extra={
                "thread_id": self._thread_id,
                "client_id": self._client_id,
                "action": "stream_resume_gap",
                "reason": reason,
            },
        )

    async def _live(self, queue: asyncio.Queue[Any]) -> AsyncGenerator[bytes]:
        """Relay queued events until the run ends, beating while it is idle.

        The resynchronization notice leads every turn, idle or not, so a drop
        is disclosed before whatever the consumer is handed next.
        """
        while not self._closed:
            item = await self._next_item(queue)
            for frame in self._resync():
                yield frame
            for frame in await self._turn_frames(item):
                yield frame

    async def _next_item(self, queue: asyncio.Queue[Any]) -> object:
        """The next queued event, or the idle sentinel when the beat elapses first."""
        try:
            return await asyncio.wait_for(
                queue.get(), timeout=settings.stream_heartbeat_interval_seconds
            )
        except TimeoutError:
            return _IDLE_BEAT

    async def _turn_frames(self, item: object) -> list[bytes]:
        """What one turn of the live loop emits after its resynchronization notice."""
        if item is _IDLE_BEAT:
            return await self._idle_frames()
        live = self._live_frame(item)
        return [] if live is None else [live]

    async def _idle_frames(self) -> list[bytes]:
        """An idle beat: the terminal a run settled to unheard, else a heartbeat.

        An idle beat is where a run that ended without this viewer hearing
        about it is caught. The relay fans out before it persists, so a
        terminal delivered in that gap belongs to neither side; re-reading here
        bounds how long such a stream can heartbeat over a finished run to one
        beat, rather than forever.
        """
        settled = await _read_durable_state(
            self._request.session_factory, self._thread_id
        )
        if settled is not None and settled.terminal:
            self._closed = True
            return list(_terminal_replay_frames(self._thread_id, settled))
        # Epoch seconds, the encoding every relayed progress frame carries, so
        # one stream holds one timestamp form.
        return [
            transport_frame(
                ServerEventType.HEARTBEAT,
                self._thread_id,
                timestamp=time.time(),
                server_uptime_seconds=time.monotonic() - self._start_time,
            )
        ]

    def _live_frame(self, item: object) -> bytes | None:
        """Encode one queued event, or ``None`` when this viewer is not served it.

        Every queued item is a relayed worker payload, already projected onto
        the positive progress allowlist at the relay seam. The encode boundary
        re-applies the allowlist, so a forbidden body cannot cross even if that
        projection were bypassed.
        """
        payload = _queue_progress_payload(item)
        if payload is None:
            return None

        # Read per frame rather than once at attachment: a run reaches its
        # numbering on its first relayed batch, which can land after a viewer
        # has already subscribed and been handed its snapshot.
        sequence = (
            retained_sequence(payload)
            if replay_is_served(self._aggregator, self._thread_id)
            else None
        )
        if sequence is not None:
            if sequence <= self._highest_emitted:
                # Already delivered: by the replay, by this connection, or - up
                # to the clamped resume floor - by the connection this one
                # continues, whose position the replay confirmed against what
                # the run had produced. The mark therefore never names a
                # sequence the run has not reached, so a live frame is dropped
                # only when it is genuinely a repeat, and the terminal - the
                # newest frame a run ever sends - is never one.
                return None
            self._highest_emitted = sequence

        event_type = payload.get("type")
        if event_type == StreamFrameKind.THREAD_TERMINAL:
            self._closed = True
        return encode_sse_frame(
            payload,
            event=str(event_type) if isinstance(event_type, str) else None,
            thread_id=self._thread_id,
            sequence=sequence,
        )

    def _resync(self) -> Iterator[bytes]:
        """Emit one backpressure notice covering everything dropped since the last."""
        dropped = self._aggregator.take_dropped_count(self._client_id)
        if dropped:
            logger.warning(
                "Stream %s lost %d events to backpressure on thread %s",
                self._client_id,
                dropped,
                self._thread_id,
                extra={
                    "client_id": self._client_id,
                    "thread_id": self._thread_id,
                    "action": "stream_backpressure_resync",
                    "dropped": dropped,
                },
            )
            yield _backpressure_frame(self._thread_id, dropped)


async def _stream_thread_events(request: ThreadStreamRequest) -> AsyncGenerator[bytes]:
    """Yield thread-scoped events from the shared subscriber queue as SSE.

    The phases and the cleanup guard open together, deliberately. The client
    holds one of the gateway's bounded stream slots from the moment the attach
    phase returns a queue, so every phase after it must sit inside the
    ``finally`` that gives the slot back - a raise between the two would strand
    the registration for the life of the process.
    """
    stream = _ThreadStream(request)
    try:
        async for frame in stream.frames():
            yield frame
    finally:
        stream.release()


async def build_thread_stream_response(
    request: ThreadStreamRequest, *, db: AsyncSession
) -> StreamingResponse:
    """Build the SSE ``StreamingResponse`` for a thread, or raise a 404.

    The single code path behind the versioned ``/v1/runs/{run_id}/stream`` verb
    (a run id is the thread id).

    *db* answers the one question that must be settled before the response
    starts - does this run exist - and is the caller's request-scoped session.
    Everything the body itself reads from travels in *request*, which outlives
    that scope.
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
    limit = domain_config.max_stream_connections
    if limit > 0 and request.aggregator.subscriber_count() >= limit:
        raise HTTPException(
            status_code=503,
            detail=("Gateway is at its progress-stream connection limit; retry later"),
            headers={"Retry-After": "5"},
        )

    thread = await get_thread(db, request.thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=request.not_found_detail)

    return StreamingResponse(
        _stream_thread_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
