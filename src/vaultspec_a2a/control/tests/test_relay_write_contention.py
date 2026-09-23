"""Relay handlers must wait for a concurrent writer, never fail on it.

A relay handler reads the run before it writes its projection. On SQLite a
transaction begun deferred cannot make that upgrade once another connection has
committed in between: the write is refused immediately with ``database is
locked`` and ``busy_timeout`` is never consulted. These tests run the production
handler against the production engine posture - write-ahead logging, the
configured busy timeout, SQLAlchemy-owned ``BEGIN`` - on a real file, with a
real second connection holding the write lock.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import create_thread
from ...database.models import Base, ThreadExecutionStateModel, ThreadModel
from ...database.session import begin_write_transaction, configure_sqlite_engine
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..event_handlers import _handle_execution_state_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

_THREAD_ID = "relay-contention-run"


@pytest_asyncio.fixture
async def sessions(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'relay.db'}")
    configure_sqlite_engine(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as db:
            await create_thread(
                db,
                write_authority=make_test_write_authority(),
                thread_id=_THREAD_ID,
                status=ThreadStatus.RUNNING,
            )
            await db.commit()
        yield factory
    finally:
        await engine.dispose()


def _projection(checkpoint_id: str) -> dict[str, object]:
    return {
        "type": "execution_state_projection",
        "checkpoint_id": checkpoint_id,
        "next_nodes": ["supervisor"],
        "task_count": 1,
    }


@pytest.mark.asyncio
async def test_execution_state_relay_waits_out_a_concurrent_writer(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as sibling:
        await begin_write_transaction(sibling)
        await sibling.execute(select(ThreadModel.id))
        sibling_thread = await sibling.get(ThreadModel, _THREAD_ID)
        assert sibling_thread is not None
        sibling_thread.last_sequence = 41
        await sibling.flush()

        started = time.monotonic()
        relay = asyncio.create_task(
            _handle_execution_state_event(
                _THREAD_ID,
                _projection("checkpoint-1"),
                session_factory=sessions,
            )
        )
        await asyncio.sleep(0.3)
        assert not relay.done(), "the relay must queue behind the held write lock"

        await sibling.commit()
        await asyncio.wait_for(relay, timeout=5.0)

    assert time.monotonic() - started >= 0.3
    async with sessions() as db:
        projection = await db.get(ThreadExecutionStateModel, _THREAD_ID)
        thread = await db.get(ThreadModel, _THREAD_ID)
    assert projection is not None
    assert projection.checkpoint_id == "checkpoint-1"
    # The sibling's own write survived: the relay waited for it rather than
    # racing it.
    assert thread is not None
    assert thread.last_sequence == 41


@pytest.mark.asyncio
async def test_concurrent_execution_state_relays_all_persist(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await asyncio.gather(
        *(
            _handle_execution_state_event(
                _THREAD_ID,
                _projection(f"checkpoint-{index}"),
                session_factory=sessions,
            )
            for index in range(8)
        )
    )
    async with sessions() as db:
        projection = await db.get(ThreadExecutionStateModel, _THREAD_ID)
    assert projection is not None
    assert projection.checkpoint_id is not None
