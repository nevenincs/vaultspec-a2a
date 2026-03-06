"""Tests for src/vaultspec_a2a/core/nodes/mount.py — create_mount_node."""

from __future__ import annotations

import pytest

from pathlib import Path

from ..mount import create_mount_node


def _make_queue_file(tmp_path: Path, feature: str = "feat") -> Path:
    """Write a minimal queue markdown file with multiple rows."""
    queue_dir = tmp_path / ".vault" / "plan"
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_file = queue_dir / f"{feature}-queue.md"
    queue_file.write_text(
        "# Queue\n\n"
        "| task_id | status | description |\n"
        "|---------|--------|-------------|\n"
        "| T-001 | in_progress | First task |\n"
        "| T-002 | pending | Second task |\n"
        "| T-003 | pending | Third task |\n"
        "| T-004 | pending | Fourth task |\n",
        encoding="utf-8",
    )
    return queue_file


def _make_state(
    *,
    workspace_root: Path,
    feature: str = "feat",
    phase: str | None = "exec",
    current_task_id: str | None = "T-001",
) -> dict:
    queue_path = f".vault/plan/{feature}-queue.md"
    return {
        "messages": [],
        "thread_id": "test-thread",
        "active_feature": feature,
        "pipeline_phase": phase,
        "current_task_id": current_task_id,
        "vault_index": {
            "adr": [queue_path],
            "plan": [queue_path],
            "exec": [queue_path],
            "research": [queue_path],
        },
    }


# ---------------------------------------------------------------------------
# Phase gate: exec/plan phase — queue content is filtered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_filtered_in_exec_phase(tmp_path: Path) -> None:
    """In exec phase, queue content is trimmed to current + next 2 pending rows."""
    _make_queue_file(tmp_path)
    node = create_mount_node(tmp_path)
    state = _make_state(workspace_root=tmp_path, phase="exec", current_task_id="T-001")
    result = await node(state)

    ctx = result["mounted_context"]
    assert ctx is not None
    assert "T-001" in ctx
    assert "T-002" in ctx
    assert "T-003" in ctx
    # T-004 is the 4th row — beyond current + next 2, so filtered out
    assert "T-004" not in ctx


@pytest.mark.asyncio
async def test_queue_filtered_in_plan_phase(tmp_path: Path) -> None:
    """In plan phase, same filtering applies as exec phase."""
    _make_queue_file(tmp_path)
    node = create_mount_node(tmp_path)
    state = _make_state(workspace_root=tmp_path, phase="plan", current_task_id="T-001")
    result = await node(state)

    ctx = result["mounted_context"]
    assert ctx is not None
    assert "T-004" not in ctx


# ---------------------------------------------------------------------------
# Phase gate: research phase — queue files NOT filtered (full content)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_not_filtered_in_research_phase(tmp_path: Path) -> None:
    """In research phase, queue files are included unfiltered (all rows present)."""
    _make_queue_file(tmp_path)
    node = create_mount_node(tmp_path)
    state = _make_state(workspace_root=tmp_path, phase="research", current_task_id="T-001")
    result = await node(state)

    ctx = result["mounted_context"]
    assert ctx is not None
    # All rows must be present — no filtering applied outside plan/exec phases
    assert "T-001" in ctx
    assert "T-002" in ctx
    assert "T-003" in ctx
    assert "T-004" in ctx


@pytest.mark.asyncio
async def test_queue_not_filtered_when_phase_is_none(tmp_path: Path) -> None:
    """When pipeline_phase is None, queue files are included unfiltered."""
    _make_queue_file(tmp_path)
    node = create_mount_node(tmp_path)
    state = _make_state(workspace_root=tmp_path, phase=None, current_task_id="T-001")
    result = await node(state)

    ctx = result["mounted_context"]
    assert ctx is not None
    assert "T-004" in ctx


# ---------------------------------------------------------------------------
# workspace_root=None → mounted_context is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mount_node_no_workspace_root_returns_none() -> None:
    """mount_node returns mounted_context=None when workspace_root is None."""
    node = create_mount_node(None)
    state = _make_state(workspace_root=Path("/tmp"), phase="exec")
    result = await node(state)
    assert result["mounted_context"] is None


# ---------------------------------------------------------------------------
# No active_feature → mounted_context is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mount_node_no_active_feature_returns_none(tmp_path: Path) -> None:
    """mount_node returns mounted_context=None when active_feature is absent."""
    _make_queue_file(tmp_path)
    node = create_mount_node(tmp_path)
    state = _make_state(workspace_root=tmp_path, phase="exec")
    state["active_feature"] = None
    result = await node(state)
    assert result["mounted_context"] is None
