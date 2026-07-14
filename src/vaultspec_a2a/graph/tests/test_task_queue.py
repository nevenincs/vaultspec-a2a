"""Tests for graph.tools.task_queue (ADR R5).

The mark-complete tool is exercised through the real ``SqlTaskQueuePort``
adapter backed by real in-memory aiosqlite — no mocks, no fakes. The pure
render helper is tested directly.
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

from ...database import create_thread, seed_task_queue
from ...database.models import Base
from ...worker.task_queue_port import SqlTaskQueuePort
from ..protocols import QueueEntryView
from ..tools.task_queue import create_mark_task_complete_tool, render_queue_view

_FEATURE = "sdd-blackboard-integration"

_ENTRIES = [
    {"task_key": "SBI-001", "description": "Add fields", "status": "completed"},
    {"task_key": "SBI-002", "description": "Anchoring", "status": "in_progress"},
    {"task_key": "SBI-003", "description": "Mount node", "status": "pending"},
    {"task_key": "SBI-004", "description": "Queue inject", "status": "pending"},
]


# ---------------------------------------------------------------------------
# render_queue_view — pure logic
# ---------------------------------------------------------------------------


def test_render_returns_empty_string_for_no_entries() -> None:
    assert render_queue_view(_FEATURE, []) == ""


def test_render_includes_header_and_rows() -> None:
    entries = [
        QueueEntryView("SBI-002", "in_progress", "Anchoring"),
        QueueEntryView("SBI-003", "pending", "Mount node"),
    ]
    result = render_queue_view(_FEATURE, entries)
    assert f"## Task Queue -- {_FEATURE}" in result
    assert "| Task | Status | Description |" in result
    assert "| SBI-002 | in_progress | Anchoring |" in result
    assert "| SBI-003 | pending | Mount node |" in result


def test_render_row_order_is_preserved() -> None:
    entries = [
        QueueEntryView("SBI-002", "in_progress", "Anchoring"),
        QueueEntryView("SBI-003", "pending", "Mount node"),
    ]
    result = render_queue_view(_FEATURE, entries)
    assert result.index("SBI-002") < result.index("SBI-003")


# ---------------------------------------------------------------------------
# mark-complete tool — real port over real SQLite
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Fresh in-memory async engine with all tables created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Async session factory bound to the in-memory engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def seeded_thread(session_factory: async_sessionmaker[AsyncSession]) -> str:
    """Create a thread with a seeded queue; return the thread id."""
    async with session_factory() as session:
        thread = await create_thread(session, title="Queue thread")
        await seed_task_queue(
            session, thread_id=thread.id, feature_tag=_FEATURE, entries=_ENTRIES
        )
        await session.commit()
        return thread.id


@pytest.mark.asyncio
async def test_tool_completes_and_reports_next_task(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool_fn, _drain = create_mark_task_complete_tool(port, seeded_thread)

    result = await tool_fn("SBI-002")
    assert result == "Task SBI-002 marked complete. Next task: SBI-003."


@pytest.mark.asyncio
async def test_tool_reports_no_further_tasks_when_drained(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
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
        thread_id = thread.id

    port = SqlTaskQueuePort(session_factory)
    tool_fn, _drain = create_mark_task_complete_tool(port, thread_id)

    result = await tool_fn("F-001")
    assert result == "Task F-001 marked complete. No further pending tasks."


@pytest.mark.asyncio
async def test_tool_reports_not_found_for_missing_task(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool_fn, _drain = create_mark_task_complete_tool(port, seeded_thread)

    result = await tool_fn("NOPE-1")
    assert result == "Task NOPE-1 not found or not in_progress."


@pytest.mark.asyncio
async def test_tool_rejects_pending_task(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool_fn, _drain = create_mark_task_complete_tool(port, seeded_thread)

    result = await tool_fn("SBI-003")
    assert result == "Task SBI-003 not found or not in_progress."


@pytest.mark.asyncio
async def test_tool_recomplete_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool_fn, _drain = create_mark_task_complete_tool(port, seeded_thread)

    first = await tool_fn("SBI-002")
    second = await tool_fn("SBI-002")
    assert first == "Task SBI-002 marked complete. Next task: SBI-003."
    assert second == "Task SBI-002 marked complete. Next task: SBI-003."


@pytest.mark.asyncio
async def test_drain_returns_next_task_id_after_completion(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool_fn, drain_fn = create_mark_task_complete_tool(port, seeded_thread)

    await tool_fn("SBI-002")
    updates = drain_fn()
    assert updates == {"current_task_id": "SBI-003"}


@pytest.mark.asyncio
async def test_drain_clears_after_call(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool_fn, drain_fn = create_mark_task_complete_tool(port, seeded_thread)

    await tool_fn("SBI-002")
    drain_fn()
    assert drain_fn() == {}


@pytest.mark.asyncio
async def test_drain_empty_when_no_tool_called(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    _tool_fn, drain_fn = create_mark_task_complete_tool(port, seeded_thread)

    assert drain_fn() == {}


@pytest.mark.asyncio
async def test_drain_reports_none_when_queue_drained(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        thread = await create_thread(session, title="single-drain")
        await seed_task_queue(
            session,
            thread_id=thread.id,
            feature_tag=_FEATURE,
            entries=[
                {"task_key": "F-001", "description": "only", "status": "in_progress"}
            ],
        )
        await session.commit()
        thread_id = thread.id

    port = SqlTaskQueuePort(session_factory)
    tool_fn, drain_fn = create_mark_task_complete_tool(port, thread_id)

    await tool_fn("F-001")
    assert drain_fn() == {"current_task_id": None}
