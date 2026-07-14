"""Persistence for the engine authoring lifecycle-stream cursor (ADR R3, P03.S07).

The verdict subscriber reads ``get_authoring_cursor`` before opening the engine
SSE stream and calls ``set_authoring_cursor`` after durably processing each
lifecycle event, so a gateway restart resumes from the last-seen sequence. The
cursor is monotonic: ``set_authoring_cursor`` never moves it backwards, which
keeps a stale write from forcing a replay storm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import AuthoringEventCursorModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DEFAULT_SUBSCRIBER_ID",
    "get_authoring_cursor",
    "set_authoring_cursor",
]

# The single verdict-subscriber identity. Kept as a constant (rather than an
# arbitrary caller string) so the row is a stable singleton per deployment.
DEFAULT_SUBSCRIBER_ID = "authoring-verdict"


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
    """
    row = await session.get(AuthoringEventCursorModel, subscriber_id)
    if row is None:
        row = AuthoringEventCursorModel(
            subscriber_id=subscriber_id, last_seq=max(last_seq, 0)
        )
        session.add(row)
        return row.last_seq
    if last_seq > row.last_seq:
        row.last_seq = last_seq
    return row.last_seq
