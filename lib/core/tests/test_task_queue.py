"""Tests for lib/core/task_queue.py — create_mark_task_complete_tool and _filter_queue_content."""

from __future__ import annotations

from pathlib import Path

import pytest

from ..task_queue import _filter_queue_content, create_mark_task_complete_tool


_SAMPLE_QUEUE = """\
## Task Queue — sdd-blackboard-integration

| ID      | Status      | Title                             |
|---------|-------------|-----------------------------------|
| SBI-001 | completed   | Add 4 new fields to TeamState     |
| SBI-002 | in_progress | Implement build_anchoring_context |
| SBI-003 | pending     | Implement mount step node         |
| SBI-004 | pending     | Wire queue injection              |
| SBI-005 | pending     | Write audit tests                 |
"""


def _make_queue_file(tmp_path: Path, content: str = _SAMPLE_QUEUE) -> tuple[Path, Path]:
    """Create .vault/plan/sdd-blackboard-integration-queue.md under tmp_path."""
    plan_dir = tmp_path / ".vault" / "plan"
    plan_dir.mkdir(parents=True)
    queue_file = plan_dir / "sdd-blackboard-integration-queue.md"
    queue_file.write_text(content, encoding="utf-8")
    return tmp_path, queue_file


# ---------------------------------------------------------------------------
# _filter_queue_content
# ---------------------------------------------------------------------------


def test_filter_returns_header_and_current_task() -> None:
    result = _filter_queue_content(_SAMPLE_QUEUE, "SBI-002")
    assert "SBI-002" in result
    assert "in_progress" in result


def test_filter_includes_next_2_pending() -> None:
    result = _filter_queue_content(_SAMPLE_QUEUE, "SBI-002")
    assert "SBI-003" in result
    assert "SBI-004" in result


def test_filter_excludes_third_pending() -> None:
    result = _filter_queue_content(_SAMPLE_QUEUE, "SBI-002")
    assert "SBI-005" not in result


def test_filter_excludes_completed_rows() -> None:
    result = _filter_queue_content(_SAMPLE_QUEUE, "SBI-002")
    assert "SBI-001" not in result


def test_filter_retains_header_lines() -> None:
    result = _filter_queue_content(_SAMPLE_QUEUE, "SBI-002")
    assert "## Task Queue" in result
    assert "| ID" in result


def test_filter_no_current_task_shows_only_pending() -> None:
    result = _filter_queue_content(_SAMPLE_QUEUE, None)
    # No current task: just show next 2 pending
    assert "SBI-003" in result
    assert "SBI-004" in result
    assert "SBI-005" not in result
    assert "SBI-002" not in result


def test_filter_unknown_current_task_still_shows_pending() -> None:
    result = _filter_queue_content(_SAMPLE_QUEUE, "SBI-999")
    # Unknown task not in queue — just show pending rows
    assert "SBI-003" in result
    assert "SBI-004" in result


# ---------------------------------------------------------------------------
# create_mark_task_complete_tool — tool_fn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_task_complete_updates_file(tmp_path: Path) -> None:
    workspace, queue_file = _make_queue_file(tmp_path)
    tool_fn, drain_fn = create_mark_task_complete_tool(
        workspace, "sdd-blackboard-integration"
    )

    result = await tool_fn("SBI-002")
    assert "marked complete" in result.lower()

    updated = queue_file.read_text(encoding="utf-8")
    assert "| SBI-002 | completed" in updated
    assert "in_progress" not in updated


@pytest.mark.asyncio
async def test_mark_task_complete_returns_next_task(tmp_path: Path) -> None:
    workspace, _queue_file = _make_queue_file(tmp_path)
    tool_fn, drain_fn = create_mark_task_complete_tool(
        workspace, "sdd-blackboard-integration"
    )

    result = await tool_fn("SBI-002")
    assert "SBI-003" in result


@pytest.mark.asyncio
async def test_mark_task_complete_no_further_tasks(tmp_path: Path) -> None:
    content = """\
## Task Queue — feat

| ID      | Status      | Title  |
|---------|-------------|--------|
| F-001   | in_progress | Step 1 |
"""
    workspace, _queue_file = _make_queue_file(tmp_path, content)
    # rename to match feature_tag
    plan_dir = tmp_path / ".vault" / "plan"
    (plan_dir / "sdd-blackboard-integration-queue.md").unlink(missing_ok=True)
    (plan_dir / "feat-queue.md").write_text(content, encoding="utf-8")

    tool_fn, drain_fn = create_mark_task_complete_tool(workspace, "feat")
    result = await tool_fn("F-001")
    assert "no further" in result.lower()


@pytest.mark.asyncio
async def test_mark_task_complete_missing_file(tmp_path: Path) -> None:
    tool_fn, drain_fn = create_mark_task_complete_tool(tmp_path, "nonexistent-feature")
    result = await tool_fn("NF-001")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_mark_task_complete_task_not_found(tmp_path: Path) -> None:
    workspace, _queue_file = _make_queue_file(tmp_path)
    tool_fn, drain_fn = create_mark_task_complete_tool(
        workspace, "sdd-blackboard-integration"
    )

    result = await tool_fn("SBI-999")
    assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_mark_task_complete_wrong_status(tmp_path: Path) -> None:
    """Trying to complete a pending task (not in_progress) should fail."""
    workspace, _queue_file = _make_queue_file(tmp_path)
    tool_fn, drain_fn = create_mark_task_complete_tool(
        workspace, "sdd-blackboard-integration"
    )

    result = await tool_fn("SBI-003")  # SBI-003 is pending, not in_progress
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# drain pattern
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_returns_current_task_id(tmp_path: Path) -> None:
    workspace, _queue_file = _make_queue_file(tmp_path)
    tool_fn, drain_fn = create_mark_task_complete_tool(
        workspace, "sdd-blackboard-integration"
    )

    await tool_fn("SBI-002")
    updates = drain_fn()

    assert "current_task_id" in updates
    assert updates["current_task_id"] == "SBI-003"


@pytest.mark.asyncio
async def test_drain_clears_after_call(tmp_path: Path) -> None:
    workspace, _queue_file = _make_queue_file(tmp_path)
    tool_fn, drain_fn = create_mark_task_complete_tool(
        workspace, "sdd-blackboard-integration"
    )

    await tool_fn("SBI-002")
    drain_fn()  # First drain — clears
    updates2 = drain_fn()  # Second drain — should be empty

    assert updates2 == {}


@pytest.mark.asyncio
async def test_drain_empty_when_no_tool_called(tmp_path: Path) -> None:
    workspace, _queue_file = _make_queue_file(tmp_path)
    _tool_fn, drain_fn = create_mark_task_complete_tool(
        workspace, "sdd-blackboard-integration"
    )

    updates = drain_fn()
    assert updates == {}


@pytest.mark.asyncio
async def test_drain_merges_multiple_calls(tmp_path: Path) -> None:
    """Last write wins when tool called multiple times before drain."""
    content = """\
## Task Queue — feat

| ID    | Status      | Title  |
|-------|-------------|--------|
| F-001 | in_progress | Step 1 |
| F-002 | in_progress | Step 2 |
| F-003 | pending     | Step 3 |
"""
    plan_dir = tmp_path / ".vault" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "feat-queue.md").write_text(content, encoding="utf-8")

    tool_fn, drain_fn = create_mark_task_complete_tool(tmp_path, "feat")
    await tool_fn("F-001")
    await tool_fn("F-002")
    updates = drain_fn()

    # Last tool call wins — F-002 completion sets current_task_id = F-003
    assert updates.get("current_task_id") == "F-003"
