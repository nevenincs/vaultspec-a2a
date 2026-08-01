"""Tests for the bundled ``vaultspec-doc-editor`` solo document-editing preset.

Real TOML loading through the shipped loaders, no mocks. The preset is the panel's
single-document lane: one worker, the engine authoring bridge as its only write
path, and no filesystem-write capability anywhere in it.
"""

from __future__ import annotations

from ...team.team_config import (
    TopologyType,
    authoring_capability,
    discover_team_preset_ids,
    load_agent_config,
    load_team_config,
    supported_capabilities,
)

_PRESET = "vaultspec-doc-editor"


def test_preset_is_discoverable_and_not_a_mock() -> None:
    """The preset is served by the same discovery the presets-list verb reads."""
    assert _PRESET in discover_team_preset_ids()


def test_preset_resolves_to_a_single_worker_pipeline() -> None:
    """One worker, pipeline topology, no supervisor - the solo-coder shape."""
    cfg = load_team_config(_PRESET)
    assert cfg.id == _PRESET
    assert cfg.topology.type == TopologyType.PIPELINE
    assert [w.agent_id for w in cfg.workers] == ["vaultspec-doc-editor"]
    assert cfg.topology.order == ["vaultspec-doc-editor"]


def test_worker_carries_no_filesystem_write_capability() -> None:
    """The panel-exposed editor never writes files; the bridge is its only path.

    This is the deliberate divergence from the clone source: ``vaultspec-coder``
    carries ``filesystem_write = true`` for ordinary paths, and the doc-editor must
    not, so the universal ban holds for the document lane rather than being merely
    vault-scoped.
    """
    cfg = load_agent_config("vaultspec-doc-editor")
    assert cfg.capabilities.filesystem_write is False
    assert cfg.capabilities.terminal is False
    # It still reads: an editor that cannot read its target cannot edit it.
    assert cfg.capabilities.filesystem_read is True


def test_clone_source_divergence_is_real() -> None:
    """The doc-editor genuinely diverges from the coder it was cloned from.

    Asserted against the live coder preset rather than restated, so the day the
    coder lane's write capability changes this test states the relationship that
    actually holds instead of silently passing on a stale premise.
    """
    coder = load_agent_config("vaultspec-coder")
    editor = load_agent_config("vaultspec-doc-editor")
    assert coder.capabilities.filesystem_write is True
    assert editor.capabilities.filesystem_write is False


def test_preset_arms_the_authoring_bridge() -> None:
    """The harness declares the bridge, so the worker reaches the engine tools."""
    cfg = load_team_config(_PRESET)
    harness = cfg.effective_harness()
    assert harness is not None
    assert harness.authoring_bridge is True
    # No workspace authoring surface is required: authoring routes through the
    # engine, never the local .vault.
    assert harness.required_surfaces == []
    # Grounding is read-only by construction: the rag server composes no write verb.
    assert harness.mcp_servers == ["vaultspec-rag"]


def test_preset_is_a_coding_topology_so_the_bridge_is_legal() -> None:
    """The bridge is refused on document-authoring TOPOLOGIES, and this is not one.

    ``research_adr`` authors through the in-process graph submitter and the config
    validator rejects an armed harness on it; the solo editor is a pipeline, so its
    agent-initiated bridge is the sanctioned path. The preset loading at all above
    is the proof the validator agrees - this pins WHY.
    """
    cfg = load_team_config(_PRESET)
    assert cfg.is_document_authoring is False
    assert authoring_capability(cfg.topology.type) == "coding"
    # It gates no phase document of its own: the human reviews its proposal through
    # the existing three-verdict lane, so it declares no phase-machine capability.
    assert supported_capabilities(cfg.topology.type) == []
