"""End-to-end proof of the thread-list service against real stores.

The service assembles a page of thread summaries and, for each, folds in a
checkpoint read to decide the resumability facts it exposes. It had no direct
test, so its ordering, its partial-state policy, and its use of the bounded
checkpoint batch were unverified as a whole.

These drive the real service against a real SQLite database and a real awaitable
checkpointer - no mocks - and assert the page it returns.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import update

from ...control.thread_listing import list_threads_service
from ...database import ThreadModel, create_thread
from ...testing import settings_override
from ...tests._write_authority import make_test_write_authority
from ...thread.enums import RepairStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _Checkpointer:
    """A real awaitable checkpointer over an in-memory map."""

    def __init__(self, present: set[str], *, delay: float = 0.0) -> None:
        self._present = present
        self._delay = delay

    async def aget_tuple(self, config: dict[str, dict[str, str]]) -> object | None:
        if self._delay:
            await asyncio.sleep(self._delay)
        tid = config["configurable"]["thread_id"]
        if tid in self._present:
            return type(
                "_T", (), {"config": config, "checkpoint": {}, "metadata": {}}
            )()
        return None


async def _seed(
    session_factory: async_sessionmaker[AsyncSession], count: int
) -> list[str]:
    ids: list[str] = []
    async with session_factory() as session:
        for index in range(count):
            thread = await create_thread(
                session,
                write_authority=make_test_write_authority(),
                title=f"thread-{index}",
                thread_id=f"t{index:02d}",
                repair_status=RepairStatus.HEALTHY,
            )
            ids.append(thread.id)
            await session.commit()
            # Distinct creation instants so ordering is unambiguous.
            await asyncio.sleep(0.01)
    return ids


@pytest.mark.asyncio
async def test_the_page_is_ordered_newest_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Threads are listed most-recently-created first."""
    await _seed(session_factory, 4)

    async with session_factory() as session:
        result = await list_threads_service(session, checkpointer=None)

    returned = [summary.thread_id for summary in result.threads]
    assert returned == sorted(returned, reverse=True), returned
    assert result.total == 4


@pytest.mark.asyncio
async def test_a_verified_absent_checkpoint_does_not_degrade_the_thread(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A healthy thread whose checkpoint is genuinely absent stays healthy.

    Absence is a certain read, so it must not trip the checkpoint-unavailable
    degradation the uncertain path triggers.
    """
    await _seed(session_factory, 2)

    async with session_factory() as session:
        result = await list_threads_service(
            session, checkpointer=_Checkpointer(present=set())
        )

    assert all(
        s.repair_status != RepairStatus.CHECKPOINT_UNAVAILABLE.value
        for s in result.threads
    ), result.threads


@pytest.mark.asyncio
async def test_an_uncertain_checkpoint_degrades_the_thread(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A read the batch deadline cut off degrades to checkpoint-unavailable.

    A slow store and a tight deadline force the uncertain path for every thread,
    and the summary must report that uncertainty rather than a healthy state.
    """
    await _seed(session_factory, 6)

    with settings_override(thread_list_checkpoint_deadline_seconds=0.05):
        async with session_factory() as session:
            result = await list_threads_service(
                session, checkpointer=_Checkpointer(present=set(), delay=1.0)
            )

    assert any(
        s.repair_status == RepairStatus.CHECKPOINT_UNAVAILABLE.value
        for s in result.threads
    ), result.threads


@pytest.mark.asyncio
async def test_a_corrupt_repair_status_column_degrades_instead_of_failing_the_page(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One row with an out-of-vocabulary repair_status must not fail the page.

    Nothing in the schema enforces the column's vocabulary, so a legacy value
    or an out-of-band write can leave a string RepairStatus does not know.
    That row must degrade, not take the whole listing down with it.
    """
    await _seed(session_factory, 2)
    async with session_factory() as session:
        await session.execute(
            update(ThreadModel)
            .where(ThreadModel.id == "t00")
            .values(repair_status="not-a-real-status")
        )
        await session.commit()

    async with session_factory() as session:
        result = await list_threads_service(session, checkpointer=None)

    assert result.total == 2
    corrupted = next(s for s in result.threads if s.thread_id == "t00")
    assert corrupted.repair_status == RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value


@pytest.mark.asyncio
async def test_the_whole_list_stays_bounded_under_a_slow_store(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A page of slow-reading threads must not cost the per-read sum."""
    await _seed(session_factory, 10)

    with settings_override(thread_list_checkpoint_deadline_seconds=0.3):
        loop = asyncio.get_running_loop()
        started = loop.time()
        async with session_factory() as session:
            await list_threads_service(
                session, checkpointer=_Checkpointer(present=set(), delay=0.5)
            )
        elapsed = loop.time() - started

    assert elapsed < 2.0, f"list took {elapsed:.2f}s; not bounded by the batch deadline"
