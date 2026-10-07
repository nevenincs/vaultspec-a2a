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

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ...control.deletion_saga import create_deletion_saga
from ...control.thread_listing import list_threads_service
from ...control.thread_state_service import capture_thread_state
from ...database import create_thread, get_thread
from ...streaming import RelayHub
from ...testing import seed_journaled_thread
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _seed_deleting_thread(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str
) -> None:
    async with session_factory() as session:
        await seed_journaled_thread(
            session,
            thread_id=thread_id,
            status=ThreadStatus.COMPLETED,
            recovery_deadline_at=datetime(2100, 1, 1, tzinfo=UTC),
        )
        await create_deletion_saga(session, thread_id=thread_id, manifest=[])
        await session.commit()


@pytest.mark.asyncio
async def test_deleting_thread_is_absent_from_the_product_list(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A deleting thread is excluded from the list and the total count."""
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="live",
            status=ThreadStatus.COMPLETED,
        )
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
        capture = await capture_thread_state(
            session,
            thread_id="gone",
            aggregator=RelayHub(),
            checkpointer=InMemorySaver(),
        )

    state = capture.snapshot if capture is not None else None

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
