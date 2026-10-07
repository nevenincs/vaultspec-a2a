"""Tests for the authoring lifecycle-cursor repository.

Real aiosqlite, no mocks. Covers the unset-cursor default, first write creating
the singleton row, monotonic advance, and rejection of a backwards write (a
stale replay must not rewind the durable cursor).

The concurrency tests run against a real file-backed database with two live
sessions, because the defects they pin - a stale ORM snapshot overwriting a
newer committed cursor, and two writers both creating the singleton row - only
exist when separate connections observe one another's commits. A private
``:memory:`` database gives each connection its own storage and so cannot
express either race.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...conftest import SqlitePosture
from .. import DEFAULT_SUBSCRIBER_ID, get_authoring_cursor, set_authoring_cursor
from ..models import AuthoringEventCursorModel

# ``expire_on_commit=False`` on the root factory mirrors the production one:
# retained post-commit attribute state is precisely what lets one session hold a
# cursor snapshot the database has already moved past. The longer driver lock
# wait keeps the serialised writers of the creation race waiting on SQLite's
# busy handler instead of failing the run on lock contention.
_RACING_WRITERS = pytest.mark.sqlite_engine(SqlitePosture.DRIVER, timeout=30)


@pytest.mark.asyncio
async def test_unset_cursor_defaults_to_zero(session: AsyncSession) -> None:
    assert await get_authoring_cursor(session) == 0


@pytest.mark.asyncio
async def test_first_write_creates_row_and_reads_back(session: AsyncSession) -> None:
    stored = await set_authoring_cursor(session, last_seq=7)
    await session.commit()
    assert stored == 7
    assert await get_authoring_cursor(session) == 7


@pytest.mark.asyncio
async def test_advance_moves_cursor_forward(session: AsyncSession) -> None:
    await set_authoring_cursor(session, last_seq=3)
    stored = await set_authoring_cursor(session, last_seq=10)
    await session.commit()
    assert stored == 10
    assert await get_authoring_cursor(session) == 10


@pytest.mark.asyncio
async def test_backwards_write_is_ignored(session: AsyncSession) -> None:
    await set_authoring_cursor(session, last_seq=20)
    stored = await set_authoring_cursor(session, last_seq=5)
    await session.commit()
    # A stale replay must not rewind the durable high-water cursor.
    assert stored == 20
    assert await get_authoring_cursor(session) == 20


@pytest.mark.asyncio
async def test_equal_write_is_a_noop(session: AsyncSession) -> None:
    await set_authoring_cursor(session, last_seq=12)
    stored = await set_authoring_cursor(session, last_seq=12)
    await session.commit()
    assert stored == 12


@pytest.mark.asyncio
async def test_cursor_survives_new_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A committed cursor is durable across sessions - the restart-survival unit."""
    async with session_factory() as first:
        await set_authoring_cursor(first, last_seq=42)
        await first.commit()
    async with session_factory() as second:
        assert await get_authoring_cursor(second) == 42


@pytest.mark.asyncio
@_RACING_WRITERS
async def test_lagging_session_cannot_rewind_a_concurrently_advanced_cursor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A write decided against a stale snapshot must not lower the stored cursor.

    The interleaving is the one a restart overlap, or two gateway processes on
    one file database, produces: the lagging session loads the cursor row, the
    leading session commits past it on its own connection, and the lagging
    session then writes a sequence that is ahead of what it read but behind what
    is stored. Deciding monotonicity in Python against the loaded snapshot
    accepts that write and issues an UPDATE unconditional on the live value,
    rewinding the cursor and silently replaying every verdict between the two.

    The lagging session keeps a reference to the entity it loaded, which is the
    state ``expire_on_commit=False`` exists to preserve and which pins the
    identity-map snapshot for the duration of the race. The repository must
    decide monotonicity against the database, not against whatever snapshot the
    caller's session happens to be holding, so the same call is also required to
    resynchronise that entity rather than leave the caller reading a value the
    database has already moved past.
    """
    async with session_factory() as seed:
        await set_authoring_cursor(seed, last_seq=10)
        await seed.commit()

    async with session_factory() as lagging, session_factory() as leading:
        # The lagging session loads the row at 10 and holds that snapshot open.
        snapshot = await lagging.get(AuthoringEventCursorModel, DEFAULT_SUBSCRIBER_ID)
        assert snapshot is not None
        assert snapshot.last_seq == 10

        # The leading session durably advances the cursor on its own connection.
        assert await set_authoring_cursor(leading, last_seq=15) == 15
        await leading.commit()

        stored = await set_authoring_cursor(lagging, last_seq=12)
        await lagging.commit()

        assert snapshot.last_seq == 15

    assert stored == 15
    async with session_factory() as reader:
        assert await get_authoring_cursor(reader) == 15


@pytest.mark.asyncio
@_RACING_WRITERS
async def test_concurrent_first_writers_converge_on_the_highest_sequence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Writers racing to create the singleton row all succeed and none regress.

    Every session starts with the row absent, so each one independently decides
    to create it; the primary key admits exactly one. Losing that race is an
    ordinary outcome of two processes starting together, so it must resolve
    against the winner's row rather than escaping as an unhandled integrity
    error, and the cursor must settle on the highest sequence any writer reached.
    """
    sequences = (4, 9, 2, 11, 7)

    async def advance(seq: int) -> int:
        async with session_factory() as db:
            stored = await set_authoring_cursor(db, last_seq=seq)
            await db.commit()
            return stored

    results = await asyncio.gather(*(advance(seq) for seq in sequences))

    for requested, stored in zip(sequences, results, strict=True):
        assert stored >= requested
    async with session_factory() as reader:
        assert await get_authoring_cursor(reader) == max(sequences)
