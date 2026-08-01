"""Unit tests for workspace-aware preset discovery and preset markers.

Real filesystem fixtures (tmp workspaces with real TOML), no mocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...team.team_config import (
    TopologyType,
    authoring_capability,
    discover_team_preset_ids,
    is_mock_preset,
    supported_capabilities,
)

if TYPE_CHECKING:
    from pathlib import Path

_BUNDLED_KNOWN = "mock-success-single"


def test_discover_includes_bundled_presets() -> None:
    ids = discover_team_preset_ids()
    assert _BUNDLED_KNOWN in ids


def test_discover_unions_workspace_local_presets(tmp_path: Path) -> None:
    teams_dir = tmp_path / ".vaultspec" / "teams"
    teams_dir.mkdir(parents=True)
    (teams_dir / "workspace-only-team.toml").write_text("[team]\n", encoding="utf-8")

    ids = discover_team_preset_ids(tmp_path)
    assert "workspace-only-team" in ids  # workspace-local
    assert _BUNDLED_KNOWN in ids  # bundled still present


def test_discover_ignores_missing_workspace_teams_dir(tmp_path: Path) -> None:
    # No .vaultspec/teams under tmp_path -> only bundled ids come back.
    ids = discover_team_preset_ids(tmp_path)
    assert _BUNDLED_KNOWN in ids
    assert "workspace-only-team" not in ids


def test_is_mock_preset_marks_mock_ids() -> None:
    assert is_mock_preset("mock-success-single") is True
    assert is_mock_preset("vaultspec-adr-research") is False


def test_authoring_capability_maps_topology() -> None:
    assert authoring_capability(TopologyType.RESEARCH_ADR) == "document_authoring"
    assert authoring_capability(TopologyType.STAR) == "coding"
    assert authoring_capability(TopologyType.PIPELINE) == "coding"


def test_research_adr_declares_all_three_document_outputs() -> None:
    """The served capability declaration names every document the topology gates.

    The declaration is the truth the dashboard renders, so it must list the plan
    document the third phase authors - a topology that gates three documents while
    declaring two would advertise a lie. Order is the pipeline order.
    """
    assert supported_capabilities(TopologyType.RESEARCH_ADR) == [
        "research_document",
        "architecture_decision",
        "plan_document",
    ]


def test_coder_topologies_declare_no_document_output() -> None:
    """Coder topologies author no vault document under this mission surface."""
    assert supported_capabilities(TopologyType.PIPELINE) == []
    assert supported_capabilities(TopologyType.STAR) == []
    assert supported_capabilities(TopologyType.PIPELINE_LOOP) == []
