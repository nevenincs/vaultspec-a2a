"""Persistence for the bounded per-run progress replay log.

The gateway stamps each outgoing progress frame with a durable per-run
sequence and appends it here, behind the fan-out; a reconnecting viewer is
then served the rows after the cursor it last received. Nothing is
reconstructed from these rows - they are the frames a subscriber was already
handed - and they expire by their own retention rather than with any
checkpoint.

The store binds a session factory rather than taking a caller's session, and
that is the point of the shape. Every operation here opens its own session and
closes it before returning, so a replay read cannot hold a pooled connection
for the life of a stream, which is how a handful of viewers once exhausted the
pool. Binding the APPLICATION session factory also makes the engine
structural: these statements never touch the checkpointer's connection, which
belongs to LangGraph and carries conversation state rather than progress
frames.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import CursorResult, Delete, Insert, delete, func, select

from ..thread.enums import TERMINAL_STATUS_VALUES
from .models import RunEventModel, ThreadModel
from .session import begin_write_transaction

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import (
        AsyncConnection,
        AsyncEngine,
        AsyncSession,
        async_sessionmaker,
    )

__all__ = ["RunEventRecord", "RunEventStore"]


@dataclass(frozen=True, slots=True)
class RunEventRecord:
    """One already-projected progress frame, as the replay log stores it.

    ``created_at`` is the moment the sequence was ALLOCATED, not the moment the
    row was flushed, so the age bound measures when the frame was produced.
    """

    thread_id: str
    sequence: int
    event_type: str
    payload_json: str
    created_at: datetime
    trace_id: str | None = None
    span_id: str | None = None

    def as_row(self) -> dict[str, object]:
        """Return this record as the column mapping an insert binds."""
        return {
            "thread_id": self.thread_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "payload_json": self.payload_json,
            "created_at": self.created_at,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


def _idempotent_insert(dialect: str) -> Insert:
    """Return an INSERT for *dialect* that ignores a row this log already holds.

    A flush that failed partway leaves its earlier rows durable, and the retry
    carries the whole batch again. A plain INSERT would then fail forever on
    the rows that landed, so a run's replay would never recover from one bad
    flush. Conflict-ignore is what makes the composite primary key an
    idempotency guard rather than a permanent refusal: the stored row and the
    retried row are the same frame under the same number, so keeping the
    stored one loses nothing.

    The construct is dialect-specific in SQLAlchemy, so it is selected from the
    bound dialect rather than guessed; both backends this service ships
    implement it.
    """
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return sqlite_insert(RunEventModel).on_conflict_do_nothing()
    from sqlalchemy.dialects.postgresql import insert as postgres_insert

    return postgres_insert(RunEventModel).on_conflict_do_nothing()


def _trim_statement(thread_id: str, window: int) -> Delete:
    """Build the delete that keeps only a run's newest *window* rows.

    The floor is the smallest sequence among the newest *window*, taken
    through a derived table because a bare ``LIMIT`` is not a scalar. A run
    holding fewer rows than the window yields its own smallest sequence as the
    floor, so the strict comparison matches nothing and the statement is a
    no-op rather than a mistake.
    """
    keep = (
        select(RunEventModel.sequence)
        .where(RunEventModel.thread_id == thread_id)
        .order_by(RunEventModel.sequence.desc())
        .limit(window)
        .subquery()
    )
    floor = select(func.min(keep.c.sequence)).scalar_subquery()
    return delete(RunEventModel).where(
        RunEventModel.thread_id == thread_id,
        RunEventModel.sequence < floor,
    )


def _dialect_of(session: AsyncSession) -> str:
    """Return the dialect name the session's engine speaks."""
    bind = cast("AsyncEngine | AsyncConnection | None", session.bind)
    if bind is None:
        msg = "a run-event session must be bound to an engine"
        raise RuntimeError(msg)
    return bind.dialect.name


@dataclass(frozen=True, slots=True)
class RunEventStore:
    """The application-engine reads and writes of the replay log."""

    session_factory: async_sessionmaker[AsyncSession]

    async def append(
        self, records: Sequence[RunEventRecord], *, window: int | None = None
    ) -> int:
        """Append *records* as one statement, trimming each run in the same batch.

        Returns the number of records offered. A row the log already holds is
        counted as offered and left alone; see :func:`_idempotent_insert`.

        *window*, when given, caps each touched run at its newest N rows inside
        the same transaction, so the bound is applied by the writer that
        breached it rather than by a later pass that may never run.
        """
        if not records:
            return 0
        async with self.session_factory() as session:
            await begin_write_transaction(session)
            await session.execute(
                _idempotent_insert(_dialect_of(session)),
                [record.as_row() for record in records],
            )
            if window is not None:
                for thread_id in dict.fromkeys(record.thread_id for record in records):
                    await session.execute(_trim_statement(thread_id, window))
            await session.commit()
        return len(records)

    async def read_after(
        self, *, thread_id: str, after_sequence: int, limit: int
    ) -> list[RunEventRecord]:
        """Return up to *limit* retained frames strictly after *after_sequence*.

        Ordered by sequence, and bounded: a cursor far behind a long run must
        not load the whole window into one response body. The session closes
        before this returns, so the pooled connection is back in the pool
        before the caller writes a single frame to the wire.
        """
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        RunEventModel.thread_id,
                        RunEventModel.sequence,
                        RunEventModel.event_type,
                        RunEventModel.payload_json,
                        RunEventModel.created_at,
                        RunEventModel.trace_id,
                        RunEventModel.span_id,
                    )
                    .where(
                        RunEventModel.thread_id == thread_id,
                        RunEventModel.sequence > after_sequence,
                    )
                    .order_by(RunEventModel.sequence)
                    .limit(limit)
                )
            ).all()
        return [RunEventRecord(*row) for row in rows]

    async def high_water_mark(self, thread_id: str) -> int | None:
        """Return the greatest sequence retained for *thread_id*, or ``None``.

        ``None`` means the log holds nothing for this run, which is a
        different answer from zero: a run with no retained rows has no window
        to resume from, and the caller decides what to do about that.
        """
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(func.max(RunEventModel.sequence)).where(
                        RunEventModel.thread_id == thread_id
                    )
                )
            ).scalar_one()

    async def settled_sequence(self, thread_id: str) -> int | None:
        """Return the cursor captured on *thread_id* when it settled.

        Read here rather than through the thread repository because it is the
        second half of ONE question - where this run's numbering stands -
        whose first half is :meth:`high_water_mark`. A caller seeding an
        allocator asks both against the same store and must not have to reach
        for two of them.
        """
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(ThreadModel.last_sequence).where(ThreadModel.id == thread_id)
                )
            ).scalar_one_or_none()

    async def trim_to_window(self, thread_id: str, window: int) -> int:
        """Keep *thread_id*'s newest *window* rows, delete the rest, count them."""
        async with self.session_factory() as session:
            await begin_write_transaction(session)
            result = cast(
                "CursorResult[Any]",
                await session.execute(_trim_statement(thread_id, window)),
            )
            await session.commit()
            return result.rowcount

    async def delete_for_runs_settled_before(self, cutoff: datetime) -> int:
        """Delete every retained frame of a run that settled before *cutoff*.

        The companion bound to :meth:`delete_produced_before`, and not a
        duplicate of it. A frame is almost always produced before its run
        settles, so the age bound usually reaches these rows first; what this
        statement adds is the run whose LAST frame arrived after the terminal
        - a late relay, a settlement racing the fan-out - whose row is young
        on a run nobody will resume. A settled run is read from the
        application's own threads table; no checkpoint is touched.
        """
        async with self.session_factory() as session:
            await begin_write_transaction(session)
            settled = (
                select(ThreadModel.id)
                .where(
                    ThreadModel.status.in_(TERMINAL_STATUS_VALUES),
                    ThreadModel.updated_at < cutoff,
                )
                .scalar_subquery()
            )
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    delete(RunEventModel).where(RunEventModel.thread_id.in_(settled))
                ),
            )
            await session.commit()
            return result.rowcount

    async def delete_produced_before(self, cutoff: datetime) -> int:
        """Delete every retained frame produced before *cutoff*, and count them.

        Bounded by the frame's own allocation stamp, which is what keeps this
        log's age retention independent of any checkpoint's: nothing here
        reads, or is read by, the settled-checkpoint prune.
        """
        async with self.session_factory() as session:
            await begin_write_transaction(session)
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    delete(RunEventModel).where(RunEventModel.created_at < cutoff)
                ),
            )
            await session.commit()
            return result.rowcount
