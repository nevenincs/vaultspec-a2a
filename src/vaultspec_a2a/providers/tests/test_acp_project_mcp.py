"""Unit tests for the run-workspace MCP projection channel.

Real filesystem, no mocks: the module reads and writes real ``.mcp.json`` files.
Bridge specs come through the production builder seam
(``build_authoring_stdio_mcp_servers``), so the projected file is asserted against
the same shape the isolated home admits. Covers the marked-entry MERGE model: a
run's declared surface is added ALONGSIDE a project's own ``.mcp.json`` and cleanup
removes exactly what it added, restoring the pre-merge state.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pytest

from ...authoring import AgentTool, CatalogSnapshot
from .._acp_authoring import AuthoringToolBinding, build_authoring_stdio_mcp_servers
from .._acp_project_mcp import (
    PROJECTION_MARKER_KEY,
    ProjectionRefusedError,
    cleanup_projected_mcp,
    enumerate_ancestor_mcp_names,
    project_declared_mcp,
    projected_declared_names,
)

if TYPE_CHECKING:
    from pathlib import Path


def _rag_spec() -> dict:
    return {
        "name": "vaultspec-rag",
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
    }


def _bridge_specs(
    *, bearer: str = "SECRET-BEARER", actor: str = "SECRET-ACTOR"
) -> list[dict]:
    binding = AuthoringToolBinding(
        snapshot=CatalogSnapshot(
            schema_version="authoring.semantic_tools.v1",
            tools=(
                AgentTool(
                    name="read_context",
                    description="read",
                    input_schema={"type": "object"},
                    risk_tier="read_only",
                    permission_requirement="auto_permitted",
                    idempotency_required=False,
                    commands=("read_context",),
                ),
            ),
        ),
        engine_base_url="http://127.0.0.1:8767",
        run_id="run-proj",
        bearer_token=bearer,
        actor_token=actor,
    )
    return build_authoring_stdio_mcp_servers(binding)


def _write_mcp(directory: Path, names: list[str]) -> None:
    servers = {n: {"type": "stdio", "command": "x"} for n in names}
    (directory / ".mcp.json").write_text(
        json.dumps({"mcpServers": servers}), encoding="utf-8"
    )


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- ancestor enumeration (unchanged upstream deny composition) ------------


def test_enumerate_ancestor_walks_every_level_to_root(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = a / "b"
    c = b / "c"
    c.mkdir(parents=True)
    _write_mcp(tmp_path, ["root-srv"])
    _write_mcp(a, ["a-srv"])
    _write_mcp(c, ["c-srv"])
    names = enumerate_ancestor_mcp_names(c)
    assert {"root-srv", "a-srv", "c-srv"} <= set(names)
    assert names == sorted(names)


def test_enumerate_ancestor_best_effort(tmp_path: Path) -> None:
    assert enumerate_ancestor_mcp_names(None) == []
    d = tmp_path / "empty"
    d.mkdir()
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    assert "root-srv" not in enumerate_ancestor_mcp_names(d)


def test_deny_set_is_ancestor_enumeration_minus_declared(tmp_path: Path) -> None:
    _write_mcp(tmp_path, ["foreign-srv", "vaultspec-rag"])
    run_ws = tmp_path / "run"
    run_ws.mkdir()
    declared = set(projected_declared_names([_rag_spec()]))
    enumerated = set(enumerate_ancestor_mcp_names(run_ws))
    deny = enumerated - declared
    assert "foreign-srv" in deny
    assert "vaultspec-rag" not in deny  # declared -> surfaced, never denied


# --- absent file: create then remove ---------------------------------------


def test_project_creates_absent_file_with_entry_marker_and_placeholders(
    tmp_path: Path,
) -> None:
    specs = [_rag_spec(), *_bridge_specs(bearer="SECRET-BEARER", actor="SECRET-ACTOR")]
    path = project_declared_mcp(tmp_path, specs)
    assert path is not None
    assert path == tmp_path / ".mcp.json"
    content = _read(path)
    assert set(content["mcpServers"]) == {"vaultspec-rag", "vaultspec-authoring"}
    marker = content[PROJECTION_MARKER_KEY]
    # Entry-level marker: the added names, and an absent pre-merge base.
    assert marker["added"] == ["vaultspec-authoring", "vaultspec-rag"]
    assert marker["base_absent"] is True
    assert marker["base_fingerprint"] is None
    # Bridge env carries placeholders, NEVER the real tokens (they ride spawn env).
    text = path.read_text(encoding="utf-8")
    assert "${VAULTSPEC_AUTHORING_BEARER}" in text
    assert "SECRET-BEARER" not in text
    assert "SECRET-ACTOR" not in text


def test_cleanup_of_created_file_restores_absent_state(tmp_path: Path) -> None:
    path = project_declared_mcp(tmp_path, [_rag_spec()])
    assert path is not None and path.exists()
    cleanup_projected_mcp(path)
    assert not path.exists()
    cleanup_projected_mcp(None)  # None-safe


def test_project_returns_none_when_nothing_declared(tmp_path: Path) -> None:
    assert project_declared_mcp(tmp_path, []) is None
    assert not (tmp_path / ".mcp.json").exists()


# --- merge into a real project .mcp.json -----------------------------------


def test_merge_preserves_project_servers_and_cleanup_restores_original(
    tmp_path: Path,
) -> None:
    foreign = {
        "mcpServers": {"user-srv": {"type": "stdio", "command": "x"}},
        "_vaultspecManaged": ["user-srv"],
    }
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(foreign), encoding="utf-8")

    projected = project_declared_mcp(tmp_path, [_rag_spec()])
    assert projected == path
    content = _read(path)
    # BOTH surfaces present: the project's own AND the declared bridge/harness set.
    assert set(content["mcpServers"]) == {"user-srv", "vaultspec-rag"}
    # Non-mcpServers project keys are preserved through the merge.
    assert content["_vaultspecManaged"] == ["user-srv"]
    marker = content[PROJECTION_MARKER_KEY]
    assert marker["added"] == ["vaultspec-rag"]
    assert marker["base_absent"] is False
    assert marker["base_fingerprint"] is not None

    cleanup_projected_mcp(path)
    # The file survives and is restored to the original project config (content).
    assert path.exists()
    assert _read(path) == foreign


# --- name collision: loud refusal ------------------------------------------


def test_project_refuses_on_server_name_collision(tmp_path: Path) -> None:
    foreign = {"mcpServers": {"vaultspec-rag": {"type": "stdio", "command": "x"}}}
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(foreign), encoding="utf-8")
    with pytest.raises(ProjectionRefusedError, match="collide"):
        project_declared_mcp(tmp_path, [_rag_spec()])
    # The foreign file is untouched.
    assert _read(path) == foreign


def test_project_refuses_unparseable_file(tmp_path: Path) -> None:
    path = tmp_path / ".mcp.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ProjectionRefusedError, match="unparseable"):
        project_declared_mcp(tmp_path, [_rag_spec()])
    assert path.read_text(encoding="utf-8") == "{not valid json"


# --- crash-residue re-projection: idempotent -------------------------------


def test_reprojection_over_own_absent_residue_is_idempotent(tmp_path: Path) -> None:
    first = project_declared_mcp(tmp_path, [_rag_spec()])
    assert first is not None
    # Simulate a crash: the projected file remains, no cleanup ran.
    second = project_declared_mcp(tmp_path, [_rag_spec()])
    assert second is not None
    content = _read(second)
    assert set(content["mcpServers"]) == {"vaultspec-rag"}
    assert content[PROJECTION_MARKER_KEY]["added"] == ["vaultspec-rag"]
    assert content[PROJECTION_MARKER_KEY]["base_absent"] is True
    # Cleanup after the idempotent re-projection still restores absent.
    cleanup_projected_mcp(second)
    assert not second.exists()


def test_reprojection_over_own_foreign_residue_restores_foreign(
    tmp_path: Path,
) -> None:
    foreign = {"mcpServers": {"user-srv": {"type": "stdio", "command": "x"}}}
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(foreign), encoding="utf-8")

    project_declared_mcp(tmp_path, [_rag_spec()])
    # Crash residue: re-project without cleanup. Must recover the original foreign
    # base (not double-count) and carry the foreign pre-merge state forward.
    project_declared_mcp(tmp_path, [_rag_spec()])
    content = _read(path)
    assert set(content["mcpServers"]) == {"user-srv", "vaultspec-rag"}
    assert content[PROJECTION_MARKER_KEY]["base_absent"] is False

    cleanup_projected_mcp(path)
    assert path.exists()
    assert _read(path) == foreign


# --- mid-run user edit survives cleanup ------------------------------------


def test_mid_run_user_added_entry_survives_cleanup(tmp_path: Path) -> None:
    path = project_declared_mcp(tmp_path, [_rag_spec()])
    assert path is not None
    # A user adds their own server into our projected file mid-run.
    content = _read(path)
    content["mcpServers"]["user-mid-run"] = {"type": "stdio", "command": "y"}
    path.write_text(json.dumps(content), encoding="utf-8")

    cleanup_projected_mcp(path)
    # The file is NOT deleted (foreign entry present) and the user's entry survives;
    # only our added entry and the marker are gone.
    assert path.exists()
    after = _read(path)
    assert set(after["mcpServers"]) == {"user-mid-run"}
    assert PROJECTION_MARKER_KEY not in after


# --- legacy whole-file marker (one transition release) ---------------------


def test_legacy_true_marker_cleanup_removes_whole_file(tmp_path: Path) -> None:
    path = tmp_path / ".mcp.json"
    legacy = {
        "mcpServers": {"vaultspec-rag": {"type": "stdio", "command": "x"}},
        PROJECTION_MARKER_KEY: True,
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    cleanup_projected_mcp(path)
    assert not path.exists()


def test_cleanup_never_touches_foreign_file(tmp_path: Path) -> None:
    foreign = {"mcpServers": {"user-srv": {"type": "stdio", "command": "x"}}}
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(foreign), encoding="utf-8")
    cleanup_projected_mcp(path)
    assert path.exists()
    assert _read(path) == foreign


# --- reserved-name mid-run edit: defined behavior --------------------------


def test_user_entry_under_reserved_projected_name_is_removed_at_cleanup(
    tmp_path: Path,
) -> None:
    """A user re-purposing one of our reserved projected names mid-run - not a
    new foreign key, the SAME key we added, with the user's own value swapped
    in - is popped as ours at cleanup regardless of fingerprint enforcement.

    Fingerprint enforcement protects the STRUCTURE of the other keys the
    marker's ``added`` list does not name; it cannot detect a same-named key's
    value changing underneath it (popping by name is value-agnostic), so this
    is defined, reserved-namespace behavior, not a gap the fingerprint closes.
    """
    foreign = {"mcpServers": {"user-srv": {"type": "stdio", "command": "x"}}}
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(foreign), encoding="utf-8")

    projected = project_declared_mcp(tmp_path, [_rag_spec()])
    assert projected == path

    # The user re-purposes our reserved "vaultspec-rag" name mid-run with
    # their own entry - same key, different value; no other key touched.
    content = _read(path)
    content["mcpServers"]["vaultspec-rag"] = {
        "type": "stdio",
        "command": "user-owned",
    }
    path.write_text(json.dumps(content), encoding="utf-8")

    cleanup_projected_mcp(path)
    after = _read(path)
    assert "vaultspec-rag" not in after["mcpServers"]
    assert after["mcpServers"] == {"user-srv": {"type": "stdio", "command": "x"}}
    assert PROJECTION_MARKER_KEY not in after


# --- fingerprint enforcement: hand-desynced marker -------------------------


def test_cleanup_skips_inversion_when_recovered_base_fingerprint_mismatches(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A hand-edit to the foreign base's OTHER keys (not our reserved name)
    without updating the marker desyncs the recorded fingerprint - cleanup
    must skip inversion entirely rather than trust the now-stale added-list,
    leaving the file exactly as found and logging the desync."""
    foreign = {"mcpServers": {"user-srv": {"type": "stdio", "command": "x"}}}
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(foreign), encoding="utf-8")

    project_declared_mcp(tmp_path, [_rag_spec()])
    content = _read(path)
    # Hand-edit the foreign base's structure (rename the foreign server) WITHOUT
    # touching the marker - desyncs the recorded base_fingerprint.
    content["mcpServers"]["user-srv-renamed"] = content["mcpServers"].pop("user-srv")
    path.write_text(json.dumps(content), encoding="utf-8")
    before_cleanup = _read(path)

    with caplog.at_level(logging.WARNING):
        cleanup_projected_mcp(path)

    assert _read(path) == before_cleanup
    assert any(
        "fingerprint" in record.getMessage() for record in caplog.records
    )


def test_reprojection_over_desynced_crash_residue_refuses_via_full_collision_check(
    tmp_path: Path,
) -> None:
    """Re-projection over a crash residue whose base has been hand-edited since
    (desyncing the marker's recorded fingerprint) must not trust the stale
    added-list to recover the base; it falls back to the FULL current server
    set, so re-declaring a name already present (even one we added before)
    collides and refuses rather than silently reusing an unverifiable slot."""
    foreign = {"mcpServers": {"user-srv": {"type": "stdio", "command": "x"}}}
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(foreign), encoding="utf-8")

    project_declared_mcp(tmp_path, [_rag_spec()])
    # Crash: no cleanup ran. Hand-edit the crashed file's foreign base
    # structure without updating the marker, desyncing base_fingerprint.
    content = _read(path)
    content["mcpServers"]["user-srv-renamed"] = content["mcpServers"].pop("user-srv")
    path.write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(ProjectionRefusedError, match="collide"):
        project_declared_mcp(tmp_path, [_rag_spec()])
    # Untouched: the refusal must not have written anything.
    after = _read(path)
    assert "user-srv-renamed" in after["mcpServers"]
    assert "vaultspec-rag" in after["mcpServers"]
