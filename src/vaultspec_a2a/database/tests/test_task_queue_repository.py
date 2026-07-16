"""Tests for the database-backed task-queue repository.

Real in-memory aiosqlite, no mocks. Covers seeding, the injectable queue
view (current + horizon selection), the idempotent mark-complete transition,
feature-tag validation, and cascade delete with the owning thread.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...thread.enums import TaskQueueStatus
from .. import (
    create_thread,
    delete_thread,
    get_queue_view,
    mark_task_complete,
    seed_task_queue,
)
from ..models import Base, TaskQueueEntryModel

_FEATURE = "sdd-blackboard-integration"

_ENTRIES: list[dict[str, object]] = [
    {"task_key": "SBI-001", "description": "Add fields", "status": "completed"},
    {"task_key": "SBI-002", "description": "Anchoring", "status": "in_progress"},
    {"task_key": "SBI-003", "description": "Mount node", "status": "pending"},
    {"task_key": "SBI-004", "description": "Queue inject", "status": "pending"},
    {"task_key": "SBI-005", "description": "Audit tests", "status": "pending"},
]


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


async def _seed_thread(
    session: AsyncSession, entries: list[dict[str, object]] = _ENTRIES
) -> str:
    """Create a thread and seed its task queue; return the thread id."""
    thread = await create_thread(session, title="Queue thread")
    await seed_task_queue(
        session, thread_id=thread.id, feature_tag=_FEATURE, entries=entries
    )
    await session.commit()
    return thread.id


class TestSeed:
    @pytest.mark.asyncio
    async def test_seed_persists_rows_with_ordered_positions(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        stmt = (
            select(TaskQueueEntryModel)
            .where(TaskQueueEntryModel.thread_id == thread_id)
            .order_by(TaskQueueEntryModel.position)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        assert [r.task_key for r in rows] == [
            "SBI-001",
            "SBI-002",
            "SBI-003",
            "SBI-004",
            "SBI-005",
        ]
        assert [r.position for r in rows] == [0, 1, 2, 3, 4]
        assert all(r.feature_tag == _FEATURE for r in rows)

    @pytest.mark.asyncio
    async def test_seed_rejects_traversal_feature_tag(
        self, session: AsyncSession
    ) -> None:
        thread = await create_thread(session, title="bad-feature")
        for bad in ("", "a/b", "a\\b", "..", "x..y"):
            with pytest.raises(ValueError, match="Invalid feature_tag"):
                await seed_task_queue(
                    session,
                    thread_id=thread.id,
                    feature_tag=bad,
                    entries=[{"task_key": "T-1", "description": "d"}],
                )

    @pytest.mark.asyncio
    async def test_seed_requires_task_key_and_description(
        self, session: AsyncSession
    ) -> None:
        thread = await create_thread(session, title="missing-fields")
        with pytest.raises(ValueError, match="task_key"):
            await seed_task_queue(
                session,
                thread_id=thread.id,
                feature_tag=_FEATURE,
                entries=[{"description": "no key"}],
            )
        with pytest.raises(ValueError, match="description"):
            await seed_task_queue(
                session,
                thread_id=thread.id,
                feature_tag=_FEATURE,
                entries=[{"task_key": "T-1"}],
            )

    @pytest.mark.asyncio
    async def test_seed_stores_plan_references(self, session: AsyncSession) -> None:
        thread = await create_thread(session, title="refs")
        created = await seed_task_queue(
            session,
            thread_id=thread.id,
            feature_tag=_FEATURE,
            entries=[
                {
                    "task_key": "R-1",
                    "description": "with refs",
                    "plan_changeset_id": "cs-abc",
                    "plan_step_key": "S07",
                }
            ],
        )
        assert created[0].plan_changeset_id == "cs-abc"
        assert created[0].plan_step_key == "S07"


class TestQueueView:
    @pytest.mark.asyncio
    async def test_view_current_first_then_next_two_pending(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        view = await get_queue_view(session, thread_id, "SBI-002", horizon=2)
        keys = [e.task_key for e in view]
        assert keys == ["SBI-002", "SBI-003", "SBI-004"]

    @pytest.mark.asyncio
    async def test_view_excludes_third_pending_at_horizon(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        view = await get_queue_view(session, thread_id, "SBI-002", horizon=2)
        assert "SBI-005" not in [e.task_key for e in view]

    @pytest.mark.asyncio
    async def test_view_excludes_completed_rows(self, session: AsyncSession) -> None:
        thread_id = await _seed_thread(session)
        view = await get_queue_view(session, thread_id, "SBI-002", horizon=10)
        assert "SBI-001" not in [e.task_key for e in view]

    @pytest.mark.asyncio
    async def test_view_no_current_shows_only_pending(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        view = await get_queue_view(session, thread_id, None, horizon=2)
        keys = [e.task_key for e in view]
        assert keys == ["SBI-003", "SBI-004"]

    @pytest.mark.asyncio
    async def test_view_unknown_current_still_shows_pending(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        view = await get_queue_view(session, thread_id, "SBI-999", horizon=2)
        keys = [e.task_key for e in view]
        assert keys == ["SBI-003", "SBI-004"]

    @pytest.mark.asyncio
    async def test_view_empty_for_unknown_thread(self, session: AsyncSession) -> None:
        view = await get_queue_view(session, "no-such-thread", None, horizon=2)
        assert view == []


class TestMarkComplete:
    @pytest.mark.asyncio
    async def test_completes_in_progress_and_reports_next(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        result = await mark_task_complete(session, thread_id, "SBI-002")
        await session.commit()
        assert result.found is True
        assert result.did_complete is True
        assert result.next_task_key == "SBI-003"

        # The transition landed: SBI-002 is now completed in the database.
        stmt = select(TaskQueueEntryModel).where(
            TaskQueueEntryModel.thread_id == thread_id,
            TaskQueueEntryModel.task_key == "SBI-002",
        )
        row = (await session.execute(stmt)).scalar_one()
        assert row.status == TaskQueueStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_no_further_pending_when_queue_drained(
        self, session: AsyncSession
    ) -> None:
        thread = await create_thread(session, title="single")
        await seed_task_queue(
            session,
            thread_id=thread.id,
            feature_tag=_FEATURE,
            entries=[
                {"task_key": "F-001", "description": "only", "status": "in_progress"}
            ],
        )
        await session.commit()
        result = await mark_task_complete(session, thread.id, "F-001")
        assert result.did_complete is True
        assert result.next_task_key is None

    @pytest.mark.asyncio
    async def test_missing_task_reports_not_found(self, session: AsyncSession) -> None:
        thread_id = await _seed_thread(session)
        result = await mark_task_complete(session, thread_id, "NOPE-1")
        assert result.found is False
        assert result.did_complete is False
        assert result.next_task_key is None

    @pytest.mark.asyncio
    async def test_pending_row_is_not_completable(self, session: AsyncSession) -> None:
        thread_id = await _seed_thread(session)
        result = await mark_task_complete(session, thread_id, "SBI-003")
        assert result.found is True
        assert result.did_complete is False
        assert result.next_task_key is None

    @pytest.mark.asyncio
    async def test_idempotent_recomplete_is_noop_success(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        first = await mark_task_complete(session, thread_id, "SBI-002")
        await session.commit()
        second = await mark_task_complete(session, thread_id, "SBI-002")
        await session.commit()
        assert first.did_complete is True
        assert second.did_complete is True
        assert second.found is True
        assert second.next_task_key == "SBI-003"


class TestCascadeDelete:
    @pytest.mark.asyncio
    async def test_delete_thread_removes_queue_entries(
        self, session: AsyncSession
    ) -> None:
        thread_id = await _seed_thread(session)
        deleted = await delete_thread(session, thread_id)
        await session.commit()
        assert deleted is True
        remaining = await get_queue_view(session, thread_id, "SBI-002", horizon=10)
        assert remaining == []
