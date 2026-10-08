"""SQLite write transactions against real concurrent connections.

A deferred transaction that reads and then writes fails at once with ``database
is locked`` when another connection commits between the two, however long
``busy_timeout`` is. ``begin_write_transaction`` exists for that case; these
tests hold both halves of the claim against the production engine posture (WAL,
``busy_timeout``, SQLAlchemy-owned ``BEGIN``) on a real file.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ...conftest import SqlitePosture
from ..session import begin_write_transaction

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


pytestmark = pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)


@pytest_asyncio.fixture(autouse=True)
async def _rows_table(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Give the store the bare table these proofs contend over."""
    async with session_factory() as db:
        await db.execute(text("CREATE TABLE rows (id INTEGER PRIMARY KEY)"))
        await db.commit()


async def _commit_row(session: AsyncSession) -> float:
    started = time.monotonic()
    await session.execute(text("INSERT INTO rows DEFAULT VALUES"))
    await session.commit()
    return time.monotonic() - started


async def _row_count(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return (await session.execute(text("SELECT count(*) FROM rows"))).scalar_one()


@pytest.mark.asyncio
async def test_deferred_read_then_write_fails_on_a_sibling_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as reader, session_factory() as sibling:
        await reader.execute(text("SELECT count(*) FROM rows"))
        await _commit_row(sibling)

        started = time.monotonic()
        with pytest.raises(OperationalError, match="database is locked"):
            await reader.execute(text("INSERT INTO rows DEFAULT VALUES"))
        # Refused without consulting busy_timeout: the hazard is not a slow
        # lock, it is one no amount of waiting resolves.
        assert time.monotonic() - started < 1.0
        await reader.rollback()


@pytest.mark.asyncio
async def test_write_transaction_makes_a_sibling_wait_instead_of_failing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as writer, session_factory() as sibling:
        await begin_write_transaction(writer)
        await writer.execute(text("SELECT count(*) FROM rows"))

        contender = asyncio.create_task(_commit_row(sibling))
        await asyncio.sleep(0.3)
        assert not contender.done(), "the sibling must queue behind the write lock"

        await writer.execute(text("INSERT INTO rows DEFAULT VALUES"))
        await writer.commit()
        waited = await asyncio.wait_for(contender, timeout=5.0)

    assert waited >= 0.3
    assert await _row_count(session_factory) == 2


@pytest.mark.asyncio
async def test_write_mode_ends_with_its_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session, session_factory() as sibling:
        await begin_write_transaction(session)
        await session.execute(text("INSERT INTO rows DEFAULT VALUES"))
        await session.commit()

        # The next transaction on the same session is an ordinary deferred
        # read again: a sibling commits past it without waiting.
        await session.execute(text("SELECT count(*) FROM rows"))
        await asyncio.wait_for(_commit_row(sibling), timeout=1.0)
        await session.rollback()

    assert await _row_count(session_factory) == 2


@pytest.mark.asyncio
async def test_write_transaction_refuses_a_session_already_in_a_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(text("SELECT count(*) FROM rows"))
        with pytest.raises(RuntimeError, match="none open"):
            await begin_write_transaction(session)
