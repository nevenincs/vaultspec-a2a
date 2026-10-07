"""Deletion saga repository: the durable row behind a cross-store thread delete.

One row per deleting thread holds the cleanup manifest and the per-item result
ledger as opaque JSON, plus the claim marker that lets one cleanup pass drive
it at a time. What the manifest and ledger mean, when an item is abandoned and
how the saga ends belong to ``control``, and the claim's lease duration is
declared with the other lease durations; this module holds the queries and
conditional writes they stand on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from .models import ThreadDeletionSagaModel

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from sqlalchemy import CursorResult, Result
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "claim_deletion_saga_row",
    "get_deletion_saga_row",
    "insert_deletion_saga_row",
    "lock_deletion_saga_row",
    "read_cleanup_ledger",
    "release_deletion_saga_claim",
    "remove_deletion_saga_row",
    "swap_cleanup_ledger",
]


def _rows_matched(result: Result[Any]) -> int:
    """Return how many rows a conditional write matched.

    Both conditional writes here decide on the match count, and a DML execution
    always yields a cursor result; only the declared return type of
    ``Session.execute`` is the wider ``Result``.
    """
    return cast("CursorResult[Any]", result).rowcount


async def get_deletion_saga_row(
    session: AsyncSession, thread_id: str
) -> ThreadDeletionSagaModel | None:
    """Return one thread's saga row, or ``None`` when it has none."""
    return await session.get(ThreadDeletionSagaModel, thread_id)


async def lock_deletion_saga_row(
    session: AsyncSession, thread_id: str
) -> ThreadDeletionSagaModel | None:
    """Return one thread's saga row under a write lock held until the transaction ends.

    Taken so a settlement check and the row removal that follows it cannot
    straddle a concurrent write to the ledger.
    """
    return await session.get(ThreadDeletionSagaModel, thread_id, with_for_update=True)


async def insert_deletion_saga_row(
    session: AsyncSession,
    *,
    thread_id: str,
    manifest_json: str,
    result_json: str,
) -> tuple[ThreadDeletionSagaModel, bool]:
    """Insert one thread's saga row, or return the row a concurrent insert won.

    The flag is ``True`` when this call created the row. When a concurrent
    request created it between the caller's read and this insert, the pending
    work of this transaction is discarded and the winner's row is returned
    with ``False``; an integrity failure with no winner's row to return is the
    caller's to see.
    """
    row = ThreadDeletionSagaModel(
        thread_id=thread_id,
        manifest_json=manifest_json,
        result_json=result_json,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.get(ThreadDeletionSagaModel, thread_id)
        if existing is None:
            raise
        return existing, False
    return row, True


async def claim_deletion_saga_row(
    session: AsyncSession,
    thread_id: str,
    *,
    now: datetime,
    lease: timedelta,
) -> tuple[ThreadDeletionSagaModel, bool] | None:
    """Stamp the claim on one saga row and report whether this call won it.

    Returns ``None`` when the thread has no saga row. The claim is a single
    conditional update that matches only a row nobody holds or whose claim is
    older than *lease*, so of any number of concurrent callers exactly one
    matches. The row is re-read rather than taken from the identity map, so the
    returned copy reflects who actually holds the claim.
    """
    claim = await session.execute(
        update(ThreadDeletionSagaModel)
        .where(
            ThreadDeletionSagaModel.thread_id == thread_id,
            or_(
                ThreadDeletionSagaModel.claimed_at.is_(None),
                ThreadDeletionSagaModel.claimed_at < now - lease,
            ),
        )
        .values(claimed_at=now, updated_at=now)
        .execution_options(synchronize_session="fetch")
    )
    row = await session.get(ThreadDeletionSagaModel, thread_id, populate_existing=True)
    if row is None:
        return None
    return row, _rows_matched(claim) == 1


async def release_deletion_saga_claim(
    session: AsyncSession, row: ThreadDeletionSagaModel, *, released_at: datetime
) -> None:
    """Clear the claim on a locked saga row, leaving every other column as it is."""
    row.claimed_at = None
    row.updated_at = released_at
    await session.flush()


async def read_cleanup_ledger(session: AsyncSession, thread_id: str) -> str | None:
    """Return one saga's serialized result ledger, or ``None`` when it has none.

    The select takes the row lock where the backend honours it, so on Postgres
    contention serialises. SQLAlchemy's SQLite dialect silently discards ``FOR
    UPDATE``, so correctness rests on :func:`swap_cleanup_ledger`, which holds on
    both.
    """
    return (
        await session.execute(
            select(ThreadDeletionSagaModel.result_json)
            .where(ThreadDeletionSagaModel.thread_id == thread_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def swap_cleanup_ledger(
    session: AsyncSession,
    thread_id: str,
    *,
    witnessed: str,
    replacement: str,
    updated_at: datetime,
) -> bool:
    """Replace a saga's result ledger only while it still holds *witnessed*.

    Every item's result lives in one serialized blob, so a plain read followed
    by a write is a lost update whenever two passes advance concurrently. The
    update therefore matches only while the ledger still holds the exact bytes
    the caller read, and ``False`` says a concurrent write got there first and
    the caller must rebuild on what it left.
    """
    swap = await session.execute(
        update(ThreadDeletionSagaModel)
        .where(
            ThreadDeletionSagaModel.thread_id == thread_id,
            ThreadDeletionSagaModel.result_json == witnessed,
        )
        .values(result_json=replacement, updated_at=updated_at)
        .execution_options(synchronize_session="fetch")
    )
    return _rows_matched(swap) == 1


async def remove_deletion_saga_row(
    session: AsyncSession, row: ThreadDeletionSagaModel
) -> None:
    """Delete one saga row."""
    await session.delete(row)
    await session.flush()
