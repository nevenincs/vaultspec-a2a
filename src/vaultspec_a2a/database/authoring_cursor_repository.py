"""Persistence for the engine authoring lifecycle-stream cursor.

The verdict subscriber reads ``get_authoring_cursor`` before opening the engine
SSE stream and calls ``set_authoring_cursor`` after durably processing each
lifecycle event, so a gateway restart resumes from the last-seen sequence. The
cursor is monotonic: ``set_authoring_cursor`` never moves it backwards, which
keeps a stale write from forcing a replay storm.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .models import AuthoringEventCursorModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DEFAULT_SUBSCRIBER_ID",
    "get_authoring_cursor",
    "set_authoring_cursor",
]

logger = logging.getLogger(__name__)

# The single verdict-subscriber identity. Kept as a constant (rather than an
# arbitrary caller string) so the row is a stable singleton per deployment.
DEFAULT_SUBSCRIBER_ID = "authoring-verdict"

_MAX_ADVANCE_ATTEMPTS = 3
"""Creation-race retries before an advance reports contention.

An attempt is only ever consumed by a concurrent writer that created the
singleton row first, and the row it committed is then visible, so the retry
after a lost creation resolves against it. The bound exists so a row that keeps
vanishing surfaces as a loud failure rather than an unbounded spin.
"""


async def get_authoring_cursor(
    session: AsyncSession,
    *,
    subscriber_id: str = DEFAULT_SUBSCRIBER_ID,
) -> int:
    """Return the last durably-processed outbox sequence, or ``0`` if unset."""
    row = await session.get(AuthoringEventCursorModel, subscriber_id)
    return row.last_seq if row is not None else 0


async def set_authoring_cursor(
    session: AsyncSession,
    *,
    last_seq: int,
    subscriber_id: str = DEFAULT_SUBSCRIBER_ID,
) -> int:
    """Advance the cursor to ``last_seq`` (monotonic) and return the stored value.

    A value at or below the current cursor is a no-op advance: the stored
    sequence never regresses. The caller owns the transaction boundary and must
    commit.

    Monotonicity holds in SQL, not in Python, because a read-compare-write over
    an ORM snapshot is a lost update. A session that loaded the row at ``10``
    before another process committed ``15`` still computes ``12 > 10`` and
    issues an UPDATE unconditional on the live value, rewinding the durable
    cursor and replaying every verdict between the two - the exact replay storm
    the cursor exists to prevent. ``expire_on_commit=False`` on the session
    factory widens that window, since instances stay populated after a commit.
    The write is therefore guarded by ``last_seq < :target``, so a stale advance
    matches no row and the committed high-water mark stands.

    A guarded write that matches nothing is ambiguous - the row may be absent,
    or already at or beyond the target - and the two outcomes return different
    values, so the stored sequence is re-read from the database with
    ``populate_existing`` rather than taken from the identity map, which the
    guarded UPDATE deliberately does not touch when it matches nothing.

    An absent row is inserted inside a SAVEPOINT. Two processes can both witness
    the absence where the backend does not serialise their writes, and the loser
    takes an ``IntegrityError`` on the ``subscriber_id`` primary key; rolling
    back only the savepoint leaves the caller's transaction usable, and the
    retry resolves against the row the winner committed.
    """
    target = max(last_seq, 0)
    for _ in range(_MAX_ADVANCE_ATTEMPTS):
        await session.execute(
            update(AuthoringEventCursorModel)
            .where(
                AuthoringEventCursorModel.subscriber_id == subscriber_id,
                AuthoringEventCursorModel.last_seq < target,
            )
            .values(last_seq=target)
            .execution_options(synchronize_session=False)
        )
        stored = await session.get(
            AuthoringEventCursorModel, subscriber_id, populate_existing=True
        )
        if stored is not None:
            return stored.last_seq
        try:
            async with session.begin_nested():
                session.add(
                    AuthoringEventCursorModel(
                        subscriber_id=subscriber_id, last_seq=target
                    )
                )
                await session.flush()
        except IntegrityError:
            logger.debug(
                "Authoring cursor creation for %s lost a race; resolving against "
                "the committed row",
                subscriber_id,
            )
            continue
        return target
    msg = (
        f"Could not advance the authoring cursor for {subscriber_id!r} to "
        f"{target} after {_MAX_ADVANCE_ATTEMPTS} attempts"
    )
    raise RuntimeError(msg)
