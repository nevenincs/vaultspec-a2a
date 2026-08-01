"""Guard: no role of a document-authoring preset may write to the filesystem.

Document-authoring presets move documents through the authoring bridge only.
A role in one of those presets that carries ``filesystem_write = true`` can put
bytes on disk outside the ledgered path, which is the one thing the document
pipeline is built to prevent.

Two design choices matter here, because a weaker guard would pass forever while
the violation ships:

*Roles are derived, never listed.* The preset set comes from
``discover_team_preset_ids`` and each preset's roles from its loaded
``TeamConfig.workers``, resolved through the production ``load_agent_config``.
A hardcoded roster of persona names is precisely the seam that cannot see a
NEW role being added to an existing preset - which is the failure mode this
guard exists to catch. Add a plan-author role to a document preset tomorrow and
these assertions pick it up with no edit here.

*"Panel-exposed" is spelled as document-touching.* The product has no
"panel-exposed" flag yet, so the guard uses the two production predicates that
follow the CONTENT: ``is_document_authoring_topology`` (the ``research_adr``
phase machine) and ``is_document_authoring_role`` (every persona role that puts
vault-document content into the world, phase machine or solo editing lane). A
solo document-editing preset on the ``pipeline`` topology is therefore covered by
the ROLE signal - the blind spot this file previously named is closed in the
predicate, not by naming a preset here, so the guard still cannot be defeated by
adding a preset. Coder-lane presets (``vaultspec-solo-coder``) and the mock
certification fixtures match neither signal, keep their write capability
legitimately, and are outside this guard;
``test_coder_lane_is_outside_the_guard`` pins that exemption so it stays a
decision rather than an accident.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...authoring.contract import (
    is_document_authoring_role,
    is_document_authoring_topology,
)
from ...team.team_config import (
    discover_team_preset_ids,
    load_agent_config,
    load_team_config,
)

if TYPE_CHECKING:
    from pathlib import Path


def _document_preset_roles(
    workspace_root: Path | None = None,
) -> dict[str, list[str]]:
    """Map every document-authoring preset id to its declared role agent ids.

    Uses the production discovery and loader so the guard sees exactly what a
    run would see, including any workspace-local preset or override.

    A preset qualifies two independent ways, and either is enough:

    * its topology is document-authoring, or
    * any of its roles declares a vault-document persona role.

    The second signal is what covers the solo lanes. Topology alone would miss a
    document role in a preset of some other topology - the pipeline-topology
    doc-editor, or a plan-author dropped into a pipeline - which would move
    document bytes with the guard looking the other way.
    """
    roles: dict[str, list[str]] = {}
    for preset_id in sorted(discover_team_preset_ids(workspace_root)):
        team = load_team_config(preset_id, workspace_root=workspace_root)
        role_ids = [worker.agent_id for worker in team.workers]
        carries_document_role = any(
            is_document_authoring_role(
                load_agent_config(role_id, workspace_root=workspace_root).role
            )
            for role_id in role_ids
        )
        if is_document_authoring_topology(team.topology.type) or carries_document_role:
            roles[preset_id] = role_ids
    return roles


def _write_enabled_roles(
    workspace_root: Path | None = None,
) -> dict[str, list[str]]:
    """Map each document-authoring preset to the roles that may write to disk.

    An empty mapping is the compliant state.
    """
    offenders: dict[str, list[str]] = {}
    for preset_id, role_ids in _document_preset_roles(workspace_root).items():
        writers = [
            role_id
            for role_id in role_ids
            if load_agent_config(
                role_id, workspace_root=workspace_root
            ).capabilities.filesystem_write
        ]
        if writers:
            offenders[preset_id] = writers
    return offenders


def test_document_authoring_presets_are_discovered() -> None:
    """The guard observes real presets carrying real roles.

    Without this, an empty discovery would make the write-denial assertion pass
    vacuously - a guard that cannot fail because it inspects nothing.
    """
    roles = _document_preset_roles()

    assert roles, (
        "No document-authoring preset was discovered; the write-denial guard "
        "would pass without inspecting anything."
    )
    for preset_id, role_ids in roles.items():
        assert role_ids, f"Document preset {preset_id!r} declares no roles."


def test_no_document_preset_role_may_write() -> None:
    """Every role of every document-authoring preset is write-denied."""
    offenders = _write_enabled_roles()

    assert not offenders, (
        "Document-authoring preset roles must not carry filesystem_write=true; "
        "documents move only through the authoring bridge. Offending "
        f"preset -> roles: {offenders}"
    )


def test_guard_detects_a_write_enabled_role(tmp_path: Path) -> None:
    """A write-enabled role in a document preset is actually caught.

    Proves the guard can fail. A workspace-local agent override shadows the
    bundled persona through the real two-level discovery order, reproducing the
    feared change - a document-pipeline role that may write - without touching
    the shared preset tree. The victim role is derived, not named, so this stays
    honest as the roster changes.
    """
    roles = _document_preset_roles()
    preset_id, role_ids = min(roles.items())
    victim = role_ids[0]
    assert load_agent_config(victim).capabilities.filesystem_write is False, (
        f"Precondition: {victim!r} is expected to be write-denied on the real tree."
    )

    agents_dir = tmp_path / ".vaultspec" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / f"{victim}.toml").write_text(
        f"""
[agent]
id = "{victim}"
display_name = "Write Enabled Override"
role = "researcher"
description = "Workspace override that switches the role's write capability on."

[agent.persona]
system_prompt = "You are a write-enabled override used to prove the guard fails."

[agent.capabilities]
filesystem_read = true
filesystem_write = true
terminal = false
""",
        encoding="utf-8",
    )

    offenders = _write_enabled_roles(tmp_path)

    assert preset_id in offenders, (
        f"Guard missed a write-enabled role in {preset_id!r}; offenders={offenders}"
    )
    assert victim in offenders[preset_id]


def test_coder_lane_is_outside_the_guard() -> None:
    """Coder-lane presets keep write capability and are exempt by topology.

    The exemption is carried by the production topology predicate rather than a
    name check, so it cannot silently widen to a document preset.
    """
    coder_team = load_team_config("vaultspec-solo-coder")

    assert not is_document_authoring_topology(coder_team.topology.type)
    assert "vaultspec-solo-coder" not in _document_preset_roles()
    assert any(
        load_agent_config(worker.agent_id).capabilities.filesystem_write
        for worker in coder_team.workers
    ), "Coder lane is expected to retain write capability; exemption is meaningful."


def test_solo_document_editing_lane_is_inside_the_guard() -> None:
    """The pipeline-topology doc-editor is covered by the ROLE signal.

    Its topology is ``pipeline`` (so the topology signal is silent) and it is
    nonetheless a document lane whose only sanctioned write path is the authoring
    bridge. Asserting membership here pins that the widened role predicate is what
    admits it, and that widening it back would be caught rather than silent.
    """
    editor = load_team_config("vaultspec-doc-editor")

    assert not is_document_authoring_topology(editor.topology.type)
    assert any(
        is_document_authoring_role(load_agent_config(worker.agent_id).role)
        for worker in editor.workers
    )
    assert "vaultspec-doc-editor" in _document_preset_roles()
    assert "vaultspec-doc-editor" not in _write_enabled_roles()
