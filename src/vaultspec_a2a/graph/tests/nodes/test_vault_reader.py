"""Tests for graph.nodes.vault_reader -- create_mount_node."""

from __future__ import annotations

from pathlib import Path

import pytest

from ...nodes.vault_reader import create_mount_node


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


@pytest.mark.asyncio
async def test_mount_node_returns_none_when_workspace_root_is_none() -> None:
    mount = create_mount_node(None)
    result = await mount(_make_state())
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_mount_node_returns_none_when_no_active_feature() -> None:
    mount = create_mount_node(Path("/tmp/ws"))
    result = await mount(_make_state(active_feature=None))
    assert result == {"mounted_context": None}


@pytest.mark.asyncio
async def test_mount_node_returns_content_for_adr_files(tmp_path: Path) -> None:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    adr_file = adr_dir / "my-feature-adr.md"
    adr_file.write_text("# ADR\n\nDecision text.", encoding="utf-8")

    mount = create_mount_node(tmp_path)
    state = _make_state(
        vault_index={"adr": [".vault/adr/my-feature-adr.md"]},
    )
    result = await mount(state)
    assert result["mounted_context"] is not None
    assert "Decision text." in result["mounted_context"]
