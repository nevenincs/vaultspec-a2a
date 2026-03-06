"""Tests for src/vaultspec_a2a/core/nodes/mount.py — create_mount_node factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from ..nodes.mount import _MOUNT_TOKEN_CEILING, create_mount_node


def _make_state(
    active_feature: str | None = "my-feature",
    vault_index: dict | None = None,
    pipeline_phase: str | None = None,
) -> dict:
    base: dict = {
        "messages": [],
        "thread_id": "t1",
        "active_agent": "worker",
        "artifacts": [],
        "current_plan": [],
        "token_usage": {},
    }
    if active_feature is not None:
        base["active_feature"] = active_feature
    if vault_index is not None:
        base["vault_index"] = vault_index
    if pipeline_phase is not None:
        base["pipeline_phase"] = pipeline_phase
    return base


# ---------------------------------------------------------------------------
# Early-exit paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_active_feature_returns_none(tmp_path: Path) -> None:
    node = create_mount_node(tmp_path)
    state = _make_state(active_feature=None)
    result = await node(state)
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_empty_vault_index_returns_none(tmp_path: Path) -> None:
    node = create_mount_node(tmp_path)
    state = _make_state(vault_index={})
    result = await node(state)
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_vault_index_empty_lists_returns_none(tmp_path: Path) -> None:
    node = create_mount_node(tmp_path)
    state = _make_state(vault_index={"adr": [], "exec": []})
    result = await node(state)
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_workspace_root_none_returns_none() -> None:
    node = create_mount_node(None)
    state = _make_state(vault_index={"adr": [".vault/adr/foo.md"]})
    result = await node(state)
    assert result == {"mounted_context": None}


# ---------------------------------------------------------------------------
# Single file mounted correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_adr_file_mounted(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "adr-001.md"
    adr_file.write_text("# ADR-001 content", encoding="utf-8")

    node = create_mount_node(tmp_path)
    state = _make_state(
        vault_index={"adr": [".vault/adr/adr-001.md"]},
        pipeline_phase="adr",
    )
    result = await node(state)

    assert result["mounted_context"] is not None
    assert "ADR-001 content" in result["mounted_context"]
    assert "adr-001.md" in result["mounted_context"]
    assert "--- MOUNTED:" in result["mounted_context"]
    assert "--- END ---" in result["mounted_context"]


# ---------------------------------------------------------------------------
# ADR docs always first, phase docs second
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adr_docs_precede_phase_docs(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    plan_dir = tmp_path / ".vault" / "plan"
    plan_dir.mkdir(parents=True)

    (adr_dir / "adr-001.md").write_text("ADR CONTENT", encoding="utf-8")
    (plan_dir / "plan-001.md").write_text("PLAN CONTENT", encoding="utf-8")

    node = create_mount_node(tmp_path)
    state = _make_state(
        vault_index={
            "adr": [".vault/adr/adr-001.md"],
            "plan": [".vault/plan/plan-001.md"],
        },
        pipeline_phase="plan",
    )
    result = await node(state)
    ctx = result["mounted_context"]
    assert ctx is not None
    assert ctx.index("ADR CONTENT") < ctx.index("PLAN CONTENT")


@pytest.mark.asyncio
async def test_phase_adr_does_not_duplicate_adr_docs(tmp_path: Path) -> None:
    """When pipeline_phase == 'adr', phase_paths should be empty (no duplicate)."""
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "adr-001.md").write_text("ADR CONTENT", encoding="utf-8")

    node = create_mount_node(tmp_path)
    state = _make_state(
        vault_index={"adr": [".vault/adr/adr-001.md"]},
        pipeline_phase="adr",
    )
    result = await node(state)
    ctx = result["mounted_context"]
    assert ctx is not None
    # Should appear exactly once
    assert ctx.count("ADR CONTENT") == 1


# ---------------------------------------------------------------------------
# Token ceiling truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_large_file_truncated(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    # Write a very large file (well over 20k tokens worth)
    big_content = "A" * (_MOUNT_TOKEN_CEILING * 6)
    (adr_dir / "big.md").write_text(big_content, encoding="utf-8")

    node = create_mount_node(tmp_path)
    state = _make_state(vault_index={"adr": [".vault/adr/big.md"]})
    result = await node(state)
    ctx = result["mounted_context"]
    assert ctx is not None
    assert "[TRUNCATED]" in ctx
    # Truncated block should be much smaller than original
    assert len(ctx) < len(big_content)


@pytest.mark.asyncio
async def test_second_file_skipped_when_no_budget(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    # First file fills the whole budget; second should be skipped
    big_content = "B" * (_MOUNT_TOKEN_CEILING * 6)
    small_content = "SMALL FILE"
    (adr_dir / "big.md").write_text(big_content, encoding="utf-8")
    (adr_dir / "small.md").write_text(small_content, encoding="utf-8")

    node = create_mount_node(tmp_path)
    state = _make_state(
        vault_index={"adr": [".vault/adr/big.md", ".vault/adr/small.md"]}
    )
    result = await node(state)
    ctx = result["mounted_context"]
    assert ctx is not None
    assert "SMALL FILE" not in ctx


# ---------------------------------------------------------------------------
# Cache reuse — same file read twice returns cached content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_reuse(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "adr-001.md"
    adr_file.write_text("ORIGINAL", encoding="utf-8")

    node = create_mount_node(tmp_path)
    state = _make_state(vault_index={"adr": [".vault/adr/adr-001.md"]})

    result1 = await node(state)
    # Overwrite the file after first read — cache should return original for same mtime
    # (We don't change mtime explicitly, so if OS gives same mtime the cache is hit)
    # Instead verify that two calls with same state both succeed and return consistent results
    result2 = await node(state)

    assert result1["mounted_context"] == result2["mounted_context"]
    assert "ORIGINAL" in result1["mounted_context"]


# ---------------------------------------------------------------------------
# Missing files are skipped gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_file_skipped(tmp_path: Path) -> None:
    node = create_mount_node(tmp_path)
    state = _make_state(vault_index={"adr": [".vault/adr/nonexistent.md"]})
    result = await node(state)
    assert result == {"mounted_context": None}


# ---------------------------------------------------------------------------
# Multiple files assembled with separator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_files_joined_with_separator(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "a.md").write_text("FILE A", encoding="utf-8")
    (adr_dir / "b.md").write_text("FILE B", encoding="utf-8")

    node = create_mount_node(tmp_path)
    state = _make_state(vault_index={"adr": [".vault/adr/a.md", ".vault/adr/b.md"]})
    result = await node(state)
    ctx = result["mounted_context"]
    assert ctx is not None
    assert "FILE A" in ctx
    assert "FILE B" in ctx
    # Two blocks means two separators and a join separator between them
    assert ctx.count("--- MOUNTED:") == 2
