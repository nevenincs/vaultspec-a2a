"""A thread under deletion disappears from product reads but not from cleanup.

The deletion saga marks a thread ``deleting`` before it removes any store
state, and the thread must stay hidden from the product's list and run-status
reads for the whole teardown - otherwise a client can observe, and try to act
on, a thread that is being dismantled. It must remain directly readable so the
cleanup coordinator can drive the saga to completion.

These drive the real services against a real SQLite database - no mocks - and
assert on what each read surfaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...control.repositories import create_deletion_saga
from ...control.thread_service import list_threads_service
from ...control.thread_state_service import build_thread_state
from ...database import create_thread, get_thread
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("deleting-visibility-db")
    materialize_schema(Path(case_dir / "test.db"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _seed_deleting_thread(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str
) -> None:
    async with session_factory() as session:
        await create_thread(session, thread_id=thread_id, status=ThreadStatus.COMPLETED)
        await create_deletion_saga(session, thread_id=thread_id, manifest=[])
        await session.commit()


@pytest.mark.asyncio
async def test_deleting_thread_is_absent_from_the_product_list(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A deleting thread is excluded from the list and the total count."""
    async with session_factory() as session:
        await create_thread(session, thread_id="live", status=ThreadStatus.COMPLETED)
        await session.commit()
    await _seed_deleting_thread(session_factory, "gone")

    async with session_factory() as session:
        result = await list_threads_service(session, checkpointer=InMemorySaver())

    ids = [summary.thread_id for summary in result.threads]
    assert ids == ["live"]
    assert result.total == 1


@pytest.mark.asyncio
async def test_deleting_thread_status_filter_is_still_hidden(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Even an explicit deleting status filter surfaces nothing from the product."""
    await _seed_deleting_thread(session_factory, "gone")

    async with session_factory() as session:
        result = await list_threads_service(
            session,
            status_filter=ThreadStatus.DELETING,
            checkpointer=InMemorySaver(),
        )

    assert result.threads == []
    assert result.total == 0


@pytest.mark.asyncio
async def test_run_lookup_reports_a_deleting_thread_as_absent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The run-status read treats a deleting thread as not found."""
    await _seed_deleting_thread(session_factory, "gone")

    async with session_factory() as session:
        state = await build_thread_state(
            session,
            thread_id="gone",
            aggregator=EventAggregator(),
            checkpointer=InMemorySaver(),
        )

    assert state is None


@pytest.mark.asyncio
async def test_cleanup_can_still_read_a_deleting_thread_directly(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The deleting thread remains directly readable for the cleanup coordinator."""
    await _seed_deleting_thread(session_factory, "gone")

    async with session_factory() as session:
        thread = await get_thread(session, "gone")

    assert thread is not None
    assert thread.status == ThreadStatus.DELETING.value
