"""What a reconnecting viewer's resume can be served, and what it cannot.

One question, answered away from the stream that asks it: given the position a
client offers, which retained frames exist after it, and is that window a
complete answer. The stream body beside this module decides what to emit; this
module decides what there is to emit, which is the part that reads the cursor,
the retention table and the unflushed ring.

Nothing here writes a frame or touches a subscriber. The answers come back as
plain values - a position, a window, a reason the window is short - so the
stream's own phases stay about ordering and the de-duplication mark.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from ..control.config import settings
from ..database.run_event_repository import RunEventStore, retained_high_water_mark
from ._replay_writer_seat import replay_writer_seat

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..database.run_event_repository import RunEventRecord
    from ..streaming import RelayHub
    from ..streaming.run_event_writer import RunEventWriter

logger = logging.getLogger(__name__)

__all__ = [
    "RESUME_WINDOW_START",
    "ReplayFrame",
    "ReplayWindow",
    "ResumePosition",
    "replay_is_served",
    "replay_window",
    "resume_position",
    "retained_after",
    "retained_sequence",
    "run_stream_resumability",
]

RESUME_WINDOW_START = "-"
"""The cursor meaning "from the start of whatever is still retained".

A client with no position of its own - a fresh viewer that wants the recent
history, or one whose stored id has expired - asks for the window rather than
guessing a number.
"""

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
class ResumePosition:
    """Where in a run's retained window a reconnecting viewer wants to restart."""

    after_sequence: int
    #: True for the window-start sentinel, which claims no position of its own.
    #: The difference matters to gap honesty: a window that starts later than a
    #: NUMBERED cursor asked for lost frames, whereas a window is exactly what
    #: the sentinel asked for.
    from_window_start: bool


def resume_position(cursor: str, thread_id: str) -> ResumePosition | None:
    """Return the position *cursor* names on this run, or ``None`` if it names none.

    ``None`` is the refusal case and covers more than a cursor from another
    run: a value that is not a position at all cannot be honoured either, and
    serving such a request as though it had no cursor would hand the caller a
    live-only stream while it believed it had resumed. Both answers are the
    same to the caller - this stream will not replay from what you sent.
    """
    if cursor == RESUME_WINDOW_START:
        return ResumePosition(after_sequence=0, from_window_start=True)
    run_id, separator, decimal = cursor.rpartition(":")
    if not separator or run_id != thread_id:
        return None
    if not decimal.isascii() or not decimal.isdigit():
        return None
    if len(decimal) > _MAX_CURSOR_DIGITS:
        return None
    return ResumePosition(after_sequence=int(decimal), from_window_start=False)


def replay_is_served(aggregator: RelayHub, thread_id: str) -> bool:
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


async def run_stream_resumability(app: Any, db: AsyncSession, thread_id: str) -> bool:
    """Whether this run's stream can be resumed from the id its frames carry.

    Both halves of the posture, because either alone misreports it. The
    switch governs the whole mechanism; the retained rows say whether THIS
    run has a window behind it, which a run that has produced nothing - or
    one whose window has expired - does not. The writer's unflushed ring
    counts as retained: a resume taken in that interval reads it, so
    answering false there would understate a capability the stream has.

    Read off the retained window rather than this gateway's numbering, unlike
    :func:`replay_is_served`, because a resume is served from that window: a
    gateway that never numbered the run - a second process, or this one after
    a restart - still reads the table, and still serves what it holds.

    Probed on the caller's own session rather than through a factory of its
    own. Run-status is the hottest read on the gateway and it already holds a
    pooled connection; opening a second one beside it for an additive
    boolean halved how many of these calls an engine could serve at once,
    and on a small pool that is the difference between answering and waiting.

    A store that cannot answer reports false, which is the safe direction:
    a client told it cannot resume loses nothing but an optimisation, while
    one told it can and then refused has already thrown away its position.
    """
    if not settings.stream_replay_enabled:
        return False
    writer = replay_writer_seat(app)
    if writer is not None and writer.pending(thread_id):
        return True
    try:
        return (await retained_high_water_mark(db, thread_id)) is not None
    except Exception:
        logger.warning(
            "Could not read the replay window of run %s for run-status",
            thread_id,
            exc_info=True,
            extra={"thread_id": thread_id, "action": "run_event_replay_failed"},
        )
        return False


def retained_sequence(payload: dict[str, object]) -> int | None:
    """Return the durable number a served frame carries, if it carries one."""
    sequence = payload.get("sequence")
    if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0:
        return sequence
    return None


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    """One retained frame, decoded back into the body a subscriber was handed."""

    sequence: int
    event_type: str
    body: dict[str, object]


def _decoded(record: RunEventRecord) -> ReplayFrame | None:
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
    return ReplayFrame(
        sequence=record.sequence,
        event_type=record.event_type,
        body=cast("dict[str, object]", body),
    )


async def retained_after(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    writer: RunEventWriter | None,
    thread_id: str,
    after_sequence: int,
) -> list[ReplayFrame]:
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
class ReplayWindow:
    """What a resume can actually be served, and what it costs to say so."""

    frames: list[ReplayFrame]
    #: ``None`` when the window answers the cursor completely. Otherwise the
    #: one reason this resume is short, emitted once before the frames.
    gap_reason: str | None = None
    first_sequence: int | None = None
    #: The highest sequence this stream may treat as already delivered before
    #: it emits anything. Never above a position the run has actually
    #: produced, which is what keeps a client's own claim from silencing the
    #: live stream: a cursor is a request, not evidence that the run ever
    #: reached it.
    dedup_floor: int = 0


def _contiguous_tail(frames: list[ReplayFrame]) -> list[ReplayFrame]:
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


async def replay_window(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    writer: RunEventWriter | None,
    thread_id: str,
    resume: ResumePosition,
) -> ReplayWindow:
    """Read what this resume can be served, and classify what it cannot.

    Three honest answers, and the difference between them is the whole point
    of the window being reported at all. A complete window carries no notice.
    A window that starts later than the cursor asked for - because retention
    trimmed the rest, or because a frame was delivered but never written -
    carries ``replay_window_exceeded`` and the first sequence it can serve. A
    replay that cannot be read at all, because the feature is off, the store
    refused, or the cursor names a position this run has never reached,
    carries ``replay_unavailable``: the consumer learns that the stream from
    here is live-only rather than being left to assume it resumed.
    """
    if not settings.stream_replay_enabled:
        return ReplayWindow([], _REPLAY_UNAVAILABLE)
    try:
        frames = await retained_after(
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
        return ReplayWindow([], _REPLAY_UNAVAILABLE)

    if not frames:
        return await _empty_replay_window(
            session_factory=session_factory,
            writer=writer,
            thread_id=thread_id,
            resume=resume,
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
    # Frames exist after the cursor, so the run has passed it and the client's
    # claim to hold everything up to it is one the window just corroborated.
    floor = resume.after_sequence
    if complete:
        return ReplayWindow(served, dedup_floor=floor)
    return ReplayWindow(
        served, _REPLAY_WINDOW_EXCEEDED, served[0].sequence, dedup_floor=floor
    )


async def _empty_replay_window(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    writer: RunEventWriter | None,
    thread_id: str,
    resume: ResumePosition,
) -> ReplayWindow:
    """Classify a resume with nothing after its cursor.

    Three cases wear the same empty answer and must not be reported the same
    way. A client at the head of the window has missed nothing, and telling it
    otherwise would send a resynchronization notice on every ordinary
    reconnect. A run with nothing retained at all cannot serve a resume from
    any position, and saying nothing there would present a live-only stream as
    a resumed one. A cursor ABOVE the run's high-water mark is the third: it
    names a position this run has never produced, so there is nothing between
    it and the live stream either to serve or to resume from.

    That third case takes ``replay_unavailable`` rather than
    ``replay_window_exceeded``, and the choice is the vocabulary's own.
    ``replay_window_exceeded`` says "frames you asked for are gone, the
    replay restarts HERE" and carries the first sequence it serves; neither
    half is true when no frame was ever lost and none can be named. What the
    consumer actually has to learn is that its position cannot be honoured
    and the stream from here is live-only, which is exactly what
    ``replay_unavailable`` says.

    The de-duplication floor is clamped to the mark in every case. A stream
    that trusted the cursor instead dropped every live frame at or below a
    number the client invented, and a cursor far above the run silenced the
    stream completely.
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
        return ReplayWindow([], _REPLAY_UNAVAILABLE)
    # The ring holds what the table does not have yet, so the run's mark is
    # the higher of the two rather than the durable one alone.
    held = [record.sequence for record in writer.pending(thread_id)] if writer else []
    if retained is not None:
        held.append(retained)
    if not held:
        return ReplayWindow([], _REPLAY_UNAVAILABLE)
    mark = max(held)
    if resume.after_sequence > mark:
        logger.info(
            "Resume of run %s names position %d, past its highest produced %d",
            thread_id,
            resume.after_sequence,
            mark,
            extra={
                "thread_id": thread_id,
                "action": "stream_resume_ahead_of_run",
                "sequence": resume.after_sequence,
            },
        )
        return ReplayWindow([], _REPLAY_UNAVAILABLE, dedup_floor=mark)
    return ReplayWindow([], dedup_floor=min(resume.after_sequence, mark))
