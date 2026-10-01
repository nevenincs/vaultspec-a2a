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

A reconnecting viewer may offer the id it last received as a resumption cursor,
and the snapshot still leads: the retained frames after the cursor follow it,
and only then does the stream go live. The subscription is attached before any
of that, which is what makes the handover seamless and also what makes the
de-duplication below necessary.
"""

from __future__ import annotations

import asyncio
import json
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
from ..database.run_event_repository import RunEventStore
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

    from ..database.run_event_repository import RunEventRecord
    from ..streaming.aggregator import EventAggregator
    from ..streaming.run_event_writer import RunEventWriter

logger = logging.getLogger(__name__)

__all__ = ["build_thread_stream_response", "offered_resume_cursor"]

_UNRECORDED_REASON = "The run failed; no reason was recorded"
"""Stands in for a failed run whose durable row holds a condition and no reason.

Says what is true of the RECORD rather than inventing an account of the failure,
so a client is never handed a diagnosis nothing observed.
"""

RESUME_WINDOW_START = "-"
"""The cursor meaning "from the start of whatever is still retained".

A client with no position of its own - a fresh viewer that wants the recent
history, or one whose stored id has expired - asks for the window rather than
guessing a number.
"""

_FOREIGN_RUN_REASON = "resume_cursor_foreign_run"

#: A resume served from later than it asked for, because the frames between
#: are no longer retained - trimmed by the window bound, or delivered live and
#: lost before they were written.
_REPLAY_WINDOW_EXCEEDED = "replay_window_exceeded"

#: A resume that could not be read at all: the feature is off, the store
#: refused, or this run has nothing retained to resume from.
_REPLAY_UNAVAILABLE = "replay_unavailable"

#: An int64 sequence is at most nineteen digits. A longer run of digits names
#: no position this log could hold, and parsing it would be work done on behalf
#: of a caller that cannot be served.
_MAX_CURSOR_DIGITS = 19


@dataclass(frozen=True, slots=True)
class _ResumePosition:
    """Where in a run's retained window a reconnecting viewer wants to restart."""

    after_sequence: int
    #: True for the window-start sentinel, which claims no position of its own.
    #: The difference matters to gap honesty: a window that starts later than a
    #: NUMBERED cursor asked for lost frames, whereas a window is exactly what
    #: the sentinel asked for.
    from_window_start: bool


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


def _resume_position(cursor: str, thread_id: str) -> _ResumePosition | None:
    """Return the position *cursor* names on this run, or ``None`` if it names none.

    ``None`` is the refusal case and covers more than a cursor from another
    run: a value that is not a position at all cannot be honoured either, and
    serving such a request as though it had no cursor would hand the caller a
    live-only stream while it believed it had resumed. Both answers are the
    same to the caller - this stream will not replay from what you sent.
    """
    if cursor == RESUME_WINDOW_START:
        return _ResumePosition(after_sequence=0, from_window_start=True)
    run_id, separator, decimal = cursor.rpartition(":")
    if not separator or run_id != thread_id:
        return None
    if not decimal.isascii() or not decimal.isdigit():
        return None
    if len(decimal) > _MAX_CURSOR_DIGITS:
        return None
    return _ResumePosition(after_sequence=int(decimal), from_window_start=False)


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


def _replay_gap_frame(thread_id: str, reason: str, first_sequence: int | None) -> bytes:
    """Say that a resume is short, and where the stream picks up again.

    The same bounded resynchronization indication as a backpressure drop, with
    the same remedy - re-read run-status - because the consequence for the
    consumer is the same: its history of this run has a hole in it. It carries
    no id of its own; the position a client resumes from is the next retained
    frame, not the notice that something before it is missing.
    """
    frame: dict[str, object] = {
        "type": "progress_dropped",
        "event_type": "progress_dropped",
        "thread_id": thread_id,
        "reason": reason,
    }
    if first_sequence is not None:
        frame["first_sequence"] = first_sequence
    return encode_sse_frame(frame, event="progress_dropped", thread_id=thread_id)


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


@dataclass(frozen=True, slots=True)
class _ReplayFrame:
    """One retained frame, decoded back into the body a subscriber was handed."""

    sequence: int
    event_type: str
    body: dict[str, object]


def _decoded(record: RunEventRecord) -> _ReplayFrame | None:
    """Decode one retained row, or ``None`` when its body is not a frame.

    A row this gateway wrote is a JSON object by construction, so ``None``
    here means the stored bytes are no longer what was written. Dropping the
    row rather than raising keeps one damaged frame from costing the whole
    resume; the window it leaves behind is then discontiguous, which the
    caller reports instead of papering over.
    """
    try:
        body = json.loads(record.payload_json)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        logger.warning(
            "Retained progress frame %d of run %s is not a decodable frame body",
            record.sequence,
            record.thread_id,
            extra={
                "thread_id": record.thread_id,
                "sequence": record.sequence,
                "action": "run_event_row_undecodable",
            },
        )
        return None
    return _ReplayFrame(
        sequence=record.sequence,
        event_type=record.event_type,
        body=cast("dict[str, object]", body),
    )


async def _retained_after(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    writer: RunEventWriter | None,
    thread_id: str,
    after_sequence: int,
) -> list[_ReplayFrame]:
    """Return the run's retained frames after *after_sequence*, oldest first.

    The two sources are unioned BY SEQUENCE, never concatenated. A flush does
    not empty the ring - it only moves the mark of what the table already
    holds - so for any window that has been written the ring and the rows name
    the same frames, and appending one to the other would hand a resuming
    client every one of them twice. A flush landing between the two reads
    widens the overlap rather than changing its nature, so the union is
    correct under any interleaving and the read needs no lock.

    The durable read is bounded by the retention window, which is the most the
    table can hold for one run; the ring contributes the newest frames the
    table does not have yet. The session closes before this returns, so no
    pooled connection is held for the life of the stream.
    """
    store = RunEventStore(session_factory)
    merged: dict[int, RunEventRecord] = {
        record.sequence: record
        for record in await store.read_after(
            thread_id=thread_id,
            after_sequence=after_sequence,
            limit=settings.stream_replay_window_events,
        )
    }
    if writer is not None:
        for record in writer.pending(thread_id):
            if record.sequence > after_sequence:
                merged.setdefault(record.sequence, record)
    return [
        frame
        for sequence in sorted(merged)
        if (frame := _decoded(merged[sequence])) is not None
    ]


@dataclass(frozen=True, slots=True)
class _ReplayWindow:
    """What a resume can actually be served, and what it costs to say so."""

    frames: list[_ReplayFrame]
    #: ``None`` when the window answers the cursor completely. Otherwise the
    #: one reason this resume is short, emitted once before the frames.
    gap_reason: str | None = None
    first_sequence: int | None = None


def _contiguous_tail(frames: list[_ReplayFrame]) -> list[_ReplayFrame]:
    """Return the longest run of consecutive sequences ending at the newest frame.

    A hole in the middle of a retained window is possible even though nothing
    deletes from the middle: a ring that overflows, or a run evicted from the
    writer's cache, loses frames that were delivered live before they were
    ever written. Serving the frames on both sides of such a hole and
    reporting only the first of them would describe a window that starts late
    while quietly skipping a position inside it. Starting after the last hole
    keeps one rule the consumer can rely on - after the notice below, every
    sequence is consecutive - at the cost of frames that are older than a gap
    the consumer is being told about anyway.
    """
    for index in range(len(frames) - 1, 0, -1):
        if frames[index].sequence != frames[index - 1].sequence + 1:
            return frames[index:]
    return frames


async def _replay_window(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    writer: RunEventWriter | None,
    thread_id: str,
    resume: _ResumePosition,
) -> _ReplayWindow:
    """Read what this resume can be served, and classify what it cannot.

    Three honest answers, and the difference between them is the whole point
    of the window being reported at all. A complete window carries no notice.
    A window that starts later than the cursor asked for - because retention
    trimmed the rest, or because a frame was delivered but never written -
    carries ``replay_window_exceeded`` and the first sequence it can serve. A
    replay that cannot be read at all, because the feature is off or the store
    refused, carries ``replay_unavailable``: the consumer learns that the
    stream from here is live-only rather than being left to assume it resumed.
    """
    if not settings.stream_replay_enabled:
        return _ReplayWindow([], _REPLAY_UNAVAILABLE)
    try:
        frames = await _retained_after(
            session_factory=session_factory,
            writer=writer,
            thread_id=thread_id,
            after_sequence=resume.after_sequence,
        )
    except Exception:
        logger.warning(
            "Could not read the replay window of run %s; its resume is served "
            "live-only",
            thread_id,
            exc_info=True,
            extra={"thread_id": thread_id, "action": "run_event_replay_failed"},
        )
        return _ReplayWindow([], _REPLAY_UNAVAILABLE)

    if not frames:
        return await _empty_replay_window(
            session_factory=session_factory, writer=writer, thread_id=thread_id
        )

    served = _contiguous_tail(frames)
    # A numbered cursor claims a position, so a window that does not continue
    # from it lost frames. The window-start sentinel claims none, so only a
    # hole INSIDE what is retained - which is what trimming the tail above
    # removes - is a loss it has to be told about.
    complete = (
        len(served) == len(frames)
        if resume.from_window_start
        else served[0].sequence == resume.after_sequence + 1
    )
    if complete:
        return _ReplayWindow(served)
    return _ReplayWindow(served, _REPLAY_WINDOW_EXCEEDED, served[0].sequence)


async def _empty_replay_window(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    writer: RunEventWriter | None,
    thread_id: str,
) -> _ReplayWindow:
    """Classify a resume with nothing after its cursor.

    Two cases wear the same empty answer and must not be reported the same
    way. A client at the head of the window has missed nothing, and telling it
    otherwise would send a resynchronization notice on every ordinary
    reconnect. A run with nothing retained at all cannot serve a resume from
    any position, and saying nothing there would present a live-only stream as
    a resumed one.
    """
    store = RunEventStore(session_factory)
    try:
        retained = await store.high_water_mark(thread_id)
    except Exception:
        logger.warning(
            "Could not read the replay high-water mark of run %s",
            thread_id,
            exc_info=True,
            extra={"thread_id": thread_id, "action": "run_event_replay_failed"},
        )
        return _ReplayWindow([], _REPLAY_UNAVAILABLE)
    held = retained is not None or bool(writer and writer.pending(thread_id))
    return _ReplayWindow([]) if held else _ReplayWindow([], _REPLAY_UNAVAILABLE)


def _replay_frame_bytes(thread_id: str, frame: _ReplayFrame) -> bytes:
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
    resume_cursor: str | None = None,
    replay_writer: RunEventWriter | None = None,
) -> AsyncGenerator[bytes]:
    """Yield thread-scoped events from the shared subscriber queue as SSE."""
    client_id = f"sse-{uuid4()}"
    resume: _ResumePosition | None = None
    if resume_cursor is not None:
        resume = _resume_position(resume_cursor, thread_id)
        if resume is None:
            # Refused before anything is registered or read. A cursor this
            # stream cannot honour is a property of the request alone, and
            # replaying another run's history to satisfy it would be worse
            # than refusing: the caller would receive frames of a run it never
            # asked about, under ids it would then resume from.
            logger.warning(
                "Refused SSE stream for thread %s: resumption cursor names "
                "another run or no position at all",
                thread_id,
                extra={
                    "client_id": client_id,
                    "thread_id": thread_id,
                    "action": "stream_resume_refused",
                },
            )
            yield _rejection_frame(thread_id, _FOREIGN_RUN_REASON)
            return
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

        # The highest sequence this connection has delivered. It starts at the
        # client's own cursor, because everything at or below that it already
        # holds, and it is what makes the subscription attached above safe: the
        # queue was collecting frames while the replay below read them, so the
        # same sequence can arrive twice and only the first delivery counts.
        highest_emitted = resume.after_sequence if resume is not None else 0

        if resume is not None:
            window = await _replay_window(
                session_factory=session_factory,
                writer=replay_writer,
                thread_id=thread_id,
                resume=resume,
            )
            if window.gap_reason is not None:
                # Exactly one notice, ahead of the frames it qualifies, so
                # everything after it is contiguous. A short replay is never
                # presented as a complete one.
                logger.info(
                    "Resume of run %s is short: %s",
                    thread_id,
                    window.gap_reason,
                    extra={
                        "thread_id": thread_id,
                        "client_id": client_id,
                        "action": "stream_resume_gap",
                        "reason": window.gap_reason,
                    },
                )
                yield _replay_gap_frame(
                    thread_id, window.gap_reason, window.first_sequence
                )
            for frame in window.frames:
                yield _replay_frame_bytes(thread_id, frame)
                highest_emitted = frame.sequence
                if frame.event_type == "thread_terminal":
                    # The run ended inside the replayed window. Closing on the
                    # retained frame rather than on the durable terminal below
                    # keeps the terminal's own sequence in the delivered set,
                    # so the union across both connections has no hole at its
                    # last position.
                    return

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
            if sequence is not None:
                if sequence <= highest_emitted:
                    # Already delivered - by the replay above, or by this
                    # connection. A terminal can never be dropped here: the
                    # mark only passes a sequence this stream has emitted, and
                    # emitting a terminal returns.
                    continue
                highest_emitted = sequence
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
    resume_cursor: str | None = None,
    replay_writer: RunEventWriter | None = None,
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

    *resume_cursor* is the id a reconnecting viewer last received, already
    resolved from the request by :func:`offered_resume_cursor`. It is carried
    into the body rather than acted on here: a cursor this run cannot honour is
    answered with a typed frame on a 200 stream, not an HTTP error, because the
    client that sends one is an ``EventSource`` that would otherwise see only a
    failed connection.

    *replay_writer* is the gateway's seated recorder, read rather than created:
    it holds the newest frames the replay table does not have yet, so a resume
    taken between an allocation and its flush still sees them. A caller with
    none - a host embedding this stream without the relay - serves the table
    alone.
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
            resume_cursor=resume_cursor,
            replay_writer=replay_writer,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
