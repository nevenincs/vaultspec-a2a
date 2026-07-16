"""Tests for graph.tools.task_queue (revised contract).

The mark-complete tool is exercised through the real ``SqlTaskQueuePort``
adapter backed by real in-memory aiosqlite — no mocks, no fakes. The tool
follows the revised contract: a single ``@tool`` returning
``Command(update=...)`` carrying the ``current_task_id`` advance and a
``ToolMessage`` keyed by the injected ``tool_call_id``. The pure render helper
is tested directly.
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from langchain_core.messages import ToolMessage
from langgraph.types import Command
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


def _tool_call(task_id: str, call_id: str = "call_1") -> dict[str, Any]:
    """Build a LangChain ToolCall dict for the mark-complete tool.

    Invoking the tool with this dict injects ``tool_call_id`` (``call_id``) via
    ``InjectedToolCallId`` and returns the tool's ``Command``.
    """
    return {
        "name": "mark_task_complete",
        "args": {"task_id": task_id},
        "id": call_id,
        "type": "tool_call",
    }


async def _mark_complete(tool: Any, task_id: str, call_id: str = "call_1") -> Command:
    """Invoke the mark-complete tool and assert it returned a Command."""
    command = await tool.ainvoke(_tool_call(task_id, call_id))
    assert isinstance(command, Command)
    return command


def _update(command: Command) -> dict[str, Any]:
    """Return the Command's update mapping, asserting it is a dict."""
    update = command.update
    assert isinstance(update, dict)
    return update


def _tool_message(command: Command) -> ToolMessage:
    """Extract the single ToolMessage from a mark-complete Command update."""
    messages = _update(command)["messages"]
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, ToolMessage)
    return message


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
    tool = create_mark_task_complete_tool(port, seeded_thread)

    command = await _mark_complete(tool, "SBI-002", "call_next")
    assert _update(command)["current_task_id"] == "SBI-003"
    message = _tool_message(command)
    assert message.content == "Task SBI-002 marked complete. Next task: SBI-003."
    assert message.tool_call_id == "call_next"


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
    tool = create_mark_task_complete_tool(port, thread_id)

    command = await _mark_complete(tool, "F-001")
    assert _update(command)["current_task_id"] is None
    assert (
        _tool_message(command).content
        == "Task F-001 marked complete. No further pending tasks."
    )


@pytest.mark.asyncio
async def test_tool_reports_not_found_for_missing_task(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool = create_mark_task_complete_tool(port, seeded_thread)

    command = await _mark_complete(tool, "NOPE-1")
    # A no-op transition leaves current_task_id untouched (key absent) and only
    # surfaces the acknowledgement ToolMessage.
    assert "current_task_id" not in _update(command)
    assert _tool_message(command).content == "Task NOPE-1 not found or not in_progress."


@pytest.mark.asyncio
async def test_tool_rejects_pending_task(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool = create_mark_task_complete_tool(port, seeded_thread)

    command = await _mark_complete(tool, "SBI-003")
    assert "current_task_id" not in _update(command)
    assert (
        _tool_message(command).content == "Task SBI-003 not found or not in_progress."
    )


@pytest.mark.asyncio
async def test_tool_recomplete_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession], seeded_thread: str
) -> None:
    port = SqlTaskQueuePort(session_factory)
    tool = create_mark_task_complete_tool(port, seeded_thread)

    first = await _mark_complete(tool, "SBI-002", "call_a")
    second = await _mark_complete(tool, "SBI-002", "call_b")
    assert _update(first)["current_task_id"] == "SBI-003"
    assert _update(second)["current_task_id"] == "SBI-003"
    assert (
        _tool_message(first).content
        == "Task SBI-002 marked complete. Next task: SBI-003."
    )
    assert (
        _tool_message(second).content
        == "Task SBI-002 marked complete. Next task: SBI-003."
    )
