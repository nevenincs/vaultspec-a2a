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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..session import begin_write_transaction, configure_sqlite_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def sessions(
    runtime_dir: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{runtime_dir / 'writes.db'}")
    configure_sqlite_engine(engine)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE rows (id INTEGER PRIMARY KEY)"))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _commit_row(session: AsyncSession) -> float:
    started = time.monotonic()
    await session.execute(text("INSERT INTO rows DEFAULT VALUES"))
    await session.commit()
    return time.monotonic() - started


async def _row_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return (await session.execute(text("SELECT count(*) FROM rows"))).scalar_one()


@pytest.mark.asyncio
async def test_deferred_read_then_write_fails_on_a_sibling_commit(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as reader, sessions() as sibling:
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
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as writer, sessions() as sibling:
        await begin_write_transaction(writer)
        await writer.execute(text("SELECT count(*) FROM rows"))

        contender = asyncio.create_task(_commit_row(sibling))
        await asyncio.sleep(0.3)
        assert not contender.done(), "the sibling must queue behind the write lock"

        await writer.execute(text("INSERT INTO rows DEFAULT VALUES"))
        await writer.commit()
        waited = await asyncio.wait_for(contender, timeout=5.0)

    assert waited >= 0.3
    assert await _row_count(sessions) == 2


@pytest.mark.asyncio
async def test_write_mode_ends_with_its_transaction(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session, sessions() as sibling:
        await begin_write_transaction(session)
        await session.execute(text("INSERT INTO rows DEFAULT VALUES"))
        await session.commit()

        # The next transaction on the same session is an ordinary deferred
        # read again: a sibling commits past it without waiting.
        await session.execute(text("SELECT count(*) FROM rows"))
        await asyncio.wait_for(_commit_row(sibling), timeout=1.0)
        await session.rollback()

    assert await _row_count(sessions) == 2


@pytest.mark.asyncio
async def test_write_transaction_refuses_a_session_already_in_a_transaction(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        await session.execute(text("SELECT count(*) FROM rows"))
        with pytest.raises(RuntimeError, match="none open"):
            await begin_write_transaction(session)
