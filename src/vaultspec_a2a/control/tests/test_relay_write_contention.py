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

from ...conftest import SqlitePosture
from ...database import create_thread
from ...database.models import ThreadExecutionStateModel, ThreadModel
from ...database.session import begin_write_transaction
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus
from ..event_handlers import _handle_execution_state_event
from ..thread_service import archive_thread

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_THREAD_ID = "relay-contention-run"


pytestmark = pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)


@pytest_asyncio.fixture(autouse=True)
async def _running_thread(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Seed the one running thread both contending writers relay to."""
    async with session_factory() as db:
        await create_thread(
            db,
            write_authority=make_test_write_authority(),
            thread_id=_THREAD_ID,
            status=ThreadStatus.RUNNING,
        )
        await db.commit()


def _projection(checkpoint_id: str) -> dict[str, object]:
    return {
        "type": "execution_state_projection",
        "checkpoint_id": checkpoint_id,
        "next_nodes": ["supervisor"],
        "task_count": 1,
    }


@pytest.mark.asyncio
async def test_execution_state_relay_waits_out_a_concurrent_writer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as sibling:
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
                session_factory=session_factory,
            )
        )
        await asyncio.sleep(0.3)
        assert not relay.done(), "the relay must queue behind the held write lock"

        await sibling.commit()
        await asyncio.wait_for(relay, timeout=5.0)

    assert time.monotonic() - started >= 0.3
    async with session_factory() as db:
        projection = await db.get(ThreadExecutionStateModel, _THREAD_ID)
        thread = await db.get(ThreadModel, _THREAD_ID)
    assert projection is not None
    assert projection.checkpoint_id == "checkpoint-1"
    # The sibling's own write survived: the relay waited for it rather than
    # racing it.
    assert thread is not None
    assert thread.last_sequence == 41


@pytest.mark.asyncio
@pytest.mark.parametrize("run_id", ["missing-run", _THREAD_ID])
async def test_a_refused_archive_releases_the_write_lock_before_returning(
    session_factory: async_sessionmaker[AsyncSession], run_id: str
) -> None:
    """A refusal writes nothing, so it must not keep the lock while its session lives.

    ``missing-run`` is refused as unknown and the seeded RUNNING run as not
    archivable. The refused session stays open while a sibling writes: if it
    still held the write lock, the sibling would wait out the whole busy timeout
    instead of committing at once.
    """
    async with session_factory() as db:
        result = await archive_thread(db, run_id)
        assert not result.archived
        assert not db.in_transaction()

        async def _sibling_write() -> None:
            async with session_factory() as sibling:
                await begin_write_transaction(sibling)
                sibling_thread = await sibling.get(ThreadModel, _THREAD_ID)
                assert sibling_thread is not None
                sibling_thread.last_sequence = 7
                await sibling.commit()

        await asyncio.wait_for(_sibling_write(), timeout=1.0)


@pytest.mark.asyncio
async def test_concurrent_execution_state_relays_all_persist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await asyncio.gather(
        *(
            _handle_execution_state_event(
                _THREAD_ID,
                _projection(f"checkpoint-{index}"),
                session_factory=session_factory,
            )
            for index in range(8)
        )
    )
    async with session_factory() as db:
        projection = await db.get(ThreadExecutionStateModel, _THREAD_ID)
    assert projection is not None
    assert projection.checkpoint_id is not None
