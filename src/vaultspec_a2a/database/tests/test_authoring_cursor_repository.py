"""Tests for the authoring lifecycle-cursor repository (ADR R3, P03.S07).

Real in-memory aiosqlite, no mocks. Covers the unset-cursor default, first
write creating the singleton row, monotonic advance, and rejection of a
backwards write (a stale replay must not rewind the durable cursor).
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .. import get_authoring_cursor, set_authoring_cursor
from ..models import Base


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Fresh in-memory async engine with all tables created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Fresh async session per test."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


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
async def test_cursor_survives_new_session(engine: AsyncEngine) -> None:
    """A committed cursor is durable across sessions - the restart-survival unit."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as first:
        await set_authoring_cursor(first, last_seq=42)
        await first.commit()
    async with factory() as second:
        assert await get_authoring_cursor(second) == 42
