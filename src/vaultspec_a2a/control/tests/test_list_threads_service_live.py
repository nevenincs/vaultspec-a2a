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

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.thread_service import list_threads_service
from vaultspec_a2a.database import create_thread
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.thread.enums import RepairStatus


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("list-service-db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


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


async def _seed(session_factory, count: int) -> list[str]:
    ids: list[str] = []
    async with session_factory() as session:
        for index in range(count):
            thread = await create_thread(
                session,
                title=f"thread-{index}",
                thread_id=f"t{index:02d}",
                repair_status=RepairStatus.HEALTHY,
                execution_readiness="healthy",
            )
            ids.append(thread.id)
            await session.commit()
            # Distinct creation instants so ordering is unambiguous.
            await asyncio.sleep(0.01)
    return ids


@pytest.mark.asyncio
async def test_the_page_is_ordered_newest_first(session_factory) -> None:
    """Threads are listed most-recently-created first."""
    await _seed(session_factory, 4)

    async with session_factory() as session:
        result = await list_threads_service(session, checkpointer=None)

    returned = [summary.thread_id for summary in result.threads]
    assert returned == sorted(returned, reverse=True), returned
    assert result.total == 4


@pytest.mark.asyncio
async def test_a_verified_absent_checkpoint_does_not_degrade_the_thread(
    session_factory,
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
async def test_an_uncertain_checkpoint_degrades_the_thread(session_factory) -> None:
    """A read the batch deadline cut off degrades to checkpoint-unavailable.

    A slow store and a tight deadline force the uncertain path for every thread,
    and the summary must report that uncertainty rather than a healthy state.
    """
    await _seed(session_factory, 6)

    from vaultspec_a2a.domain_config import domain_config

    original = domain_config.thread_list_checkpoint_deadline_seconds
    domain_config.thread_list_checkpoint_deadline_seconds = 0.05
    try:
        async with session_factory() as session:
            result = await list_threads_service(
                session, checkpointer=_Checkpointer(present=set(), delay=1.0)
            )
    finally:
        domain_config.thread_list_checkpoint_deadline_seconds = original

    assert any(
        s.repair_status == RepairStatus.CHECKPOINT_UNAVAILABLE.value
        for s in result.threads
    ), result.threads


@pytest.mark.asyncio
async def test_the_whole_list_stays_bounded_under_a_slow_store(
    session_factory,
) -> None:
    """A page of slow-reading threads must not cost the per-read sum."""
    await _seed(session_factory, 10)

    from vaultspec_a2a.domain_config import domain_config

    original = domain_config.thread_list_checkpoint_deadline_seconds
    domain_config.thread_list_checkpoint_deadline_seconds = 0.3
    try:
        loop = asyncio.get_running_loop()
        started = loop.time()
        async with session_factory() as session:
            await list_threads_service(
                session, checkpointer=_Checkpointer(present=set(), delay=0.5)
            )
        elapsed = loop.time() - started
    finally:
        domain_config.thread_list_checkpoint_deadline_seconds = original

    assert elapsed < 2.0, f"list took {elapsed:.2f}s; not bounded by the batch deadline"
