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
from pydantic import TypeAdapter

from ...authoring import AgentTool, CatalogSnapshot
from ...thread.errors import ProjectionRefusedError
from .._acp_authoring import (
    AUTHORING_MCP_SERVER_NAME,
    AuthoringToolBinding,
    build_authoring_stdio_mcp_servers,
)
from .._acp_project_mcp import (
    PROJECTION_MARKER_KEY,
    _declared_home_entries,
    _split_projection,
    ambient_user_mcp_names,
    cleanup_confinement_settings,
    cleanup_projected_mcp,
    enumerate_ancestor_mcp_names,
    project_confinement_settings,
    project_declared_mcp,
)
from .._json_contract import JsonObject, JsonValue

if TYPE_CHECKING:
    from pathlib import Path


_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


def _rag_spec() -> JsonObject:
    return {
        "name": "vaultspec-rag",
        "type": "stdio",
        "command": "uvx",
        "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
    }


def _bridge_specs(
    *, bearer: str = "SECRET-BEARER", actor: str = "SECRET-ACTOR"
) -> list[JsonObject]:
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
    servers: JsonObject = {name: {"type": "stdio", "command": "x"} for name in names}
    payload: JsonObject = {"mcpServers": servers}
    (directory / ".mcp.json").write_text(json.dumps(payload), encoding="utf-8")


def _read(path: Path) -> JsonObject:
    return _JSON_OBJECT.validate_json(path.read_text(encoding="utf-8"))


def _object_field(document: JsonObject, name: str) -> JsonObject:
    value = document[name]
    assert isinstance(value, dict)
    return value


def _servers(document: JsonObject) -> JsonObject:
    return _object_field(document, "mcpServers")


def _marker(document: JsonObject) -> JsonObject:
    return _object_field(document, PROJECTION_MARKER_KEY)


def test_only_run_owned_specs_enter_the_projected_provider_tree(
    tmp_path: Path,
) -> None:
    """Audit lock: only run-owned launch specs enter the isolated provider tree.

    Every projected server is launched by the contained ACP provider root, so
    what a run declares is exactly what becomes a descendant. A foreign server in
    an ancestor ``.mcp.json`` is enumerated (so the caller can DENY it) but is
    never part of what this module projects, and this config-only module reaches
    no process-spawn primitive.
    """
    run_ws = tmp_path / "run-ws"
    run_ws.mkdir()
    _write_mcp(tmp_path, ["foreign-ancestor-srv"])

    declared = [_rag_spec(), *_bridge_specs()]
    run_owned = set(_declared_home_entries(declared))
    # Exactly the run-owned declared servers (harness + the run's authoring bridge).
    assert run_owned == {"vaultspec-rag", AUTHORING_MCP_SERVER_NAME}
    # The foreign ancestor server is enumerated for the caller's deny set, but is
    # NOT part of what enters the isolated provider tree.
    enumerated = set(enumerate_ancestor_mcp_names(run_ws))
    assert "foreign-ancestor-srv" in enumerated
    assert "foreign-ancestor-srv" not in run_owned

    from .. import _acp_project_mcp as mod

    for banned in (
        "subprocess",
        "Popen",
        "spawn_acp_process",
        "create_subprocess_exec",
        "ProcessContainment",
    ):
        assert not hasattr(mod, banned), f"projection module must not spawn ({banned})"


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
    declared = set(_declared_home_entries([_rag_spec()]))
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
    assert set(_servers(content)) == {"vaultspec-rag", "vaultspec-authoring"}
    marker = _marker(content)
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
    assert set(_servers(content)) == {"user-srv", "vaultspec-rag"}
    # Non-mcpServers project keys are preserved through the merge.
    assert content["_vaultspecManaged"] == ["user-srv"]
    marker = _marker(content)
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
    assert set(_servers(content)) == {"vaultspec-rag"}
    marker = _marker(content)
    assert marker["added"] == ["vaultspec-rag"]
    assert marker["base_absent"] is True
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
    assert set(_servers(content)) == {"user-srv", "vaultspec-rag"}
    assert _marker(content)["base_absent"] is False

    cleanup_projected_mcp(path)
    assert path.exists()
    assert _read(path) == foreign


# --- mid-run user edit survives cleanup ------------------------------------


def test_mid_run_user_added_entry_survives_cleanup(tmp_path: Path) -> None:
    path = project_declared_mcp(tmp_path, [_rag_spec()])
    assert path is not None
    # A user adds their own server into our projected file mid-run.
    content = _read(path)
    _servers(content)["user-mid-run"] = {"type": "stdio", "command": "y"}
    path.write_text(json.dumps(content), encoding="utf-8")

    cleanup_projected_mcp(path)
    # The file is NOT deleted (foreign entry present) and the user's entry survives;
    # only our added entry and the marker are gone.
    assert path.exists()
    after = _read(path)
    assert set(_servers(after)) == {"user-mid-run"}
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


def test_cleanup_warns_and_preserves_bytes_for_marker_missing_fingerprint(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A marker missing a required field is foreign data, not ``null``.

    Exercise the real filesystem boundary and preserve its exact bytes: a
    malformed marker cannot authorize removing a same-named foreign server.
    """
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {"foreign": {"type": "stdio", "command": "x"}},
                PROJECTION_MARKER_KEY: {"added": ["foreign"], "base_absent": False},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()

    with caplog.at_level(logging.WARNING):
        cleanup_projected_mcp(path)

    assert path.read_bytes() == before
    assert any("malformed" in record.getMessage() for record in caplog.records)


def test_reprojection_refuses_and_preserves_bytes_for_marker_missing_fingerprint(
    tmp_path: Path,
) -> None:
    """Malformed crash residue keeps every present server collision-protected."""
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "vaultspec-rag": {"type": "stdio", "command": "foreign"}
                },
                PROJECTION_MARKER_KEY: {
                    "added": ["vaultspec-rag"],
                    "base_absent": False,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()

    with pytest.raises(ProjectionRefusedError, match="collide"):
        project_declared_mcp(tmp_path, [_rag_spec()])

    assert path.read_bytes() == before


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
    _servers(content)["vaultspec-rag"] = {
        "type": "stdio",
        "command": "user-owned",
    }
    path.write_text(json.dumps(content), encoding="utf-8")

    cleanup_projected_mcp(path)
    after = _read(path)
    assert "vaultspec-rag" not in _servers(after)
    assert _servers(after) == {"user-srv": {"type": "stdio", "command": "x"}}
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
    servers = _servers(content)
    servers["user-srv-renamed"] = servers.pop("user-srv")
    path.write_text(json.dumps(content), encoding="utf-8")
    before_cleanup = _read(path)

    with caplog.at_level(logging.WARNING):
        cleanup_projected_mcp(path)

    assert _read(path) == before_cleanup
    assert any("fingerprint" in record.getMessage() for record in caplog.records)


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
    servers = _servers(content)
    servers["user-srv-renamed"] = servers.pop("user-srv")
    path.write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(ProjectionRefusedError, match="collide"):
        project_declared_mcp(tmp_path, [_rag_spec()])
    # Untouched: the refusal must not have written anything.
    after = _read(path)
    assert "user-srv-renamed" in _servers(after)
    assert "vaultspec-rag" in _servers(after)


def test_split_projection_is_one_decomposition_for_recovery_and_cleanup() -> None:
    """The shared split keeps the marker out of BOTH halves and copies both.

    Re-projection and cleanup each rebuild or drop the marker, so a marker
    surviving in ``other`` would be re-emitted stale. The copy matters because
    both callers strip or merge into the result.
    """
    parsed: JsonObject = {
        "mcpServers": {"project-own": {"command": "x"}},
        "someOtherKey": {"kept": True},
        PROJECTION_MARKER_KEY: {"added": ["project-own"], "base_absent": False},
    }
    servers, other = _split_projection(parsed)

    assert servers == {"project-own": {"command": "x"}}
    assert other == {"someOtherKey": {"kept": True}}
    assert PROJECTION_MARKER_KEY not in other
    assert PROJECTION_MARKER_KEY not in servers

    servers.pop("project-own")
    other.pop("someOtherKey")
    assert _servers(parsed) == {"project-own": {"command": "x"}}
    assert parsed["someOtherKey"] == {"kept": True}


@pytest.mark.parametrize("servers_value", [None, [], "mcpServers", 7])
def test_split_projection_treats_a_non_mapping_server_block_as_empty(
    servers_value: JsonValue,
) -> None:
    """A file naming no usable ``mcpServers`` has no servers, and never raises."""
    parsed: JsonObject = {"mcpServers": servers_value, "keep": 1}
    servers, other = _split_projection(parsed)
    assert servers == {}
    assert other == {"keep": 1}


def test_cleanup_preserves_other_top_level_keys_through_the_shared_split(
    tmp_path: Path,
) -> None:
    """Behaviour proof that both call sites still round-trip non-server keys."""
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps({"$schema": "https://example.invalid/mcp", "mcpServers": {}}),
        encoding="utf-8",
    )
    written = project_declared_mcp(tmp_path, [_rag_spec()])
    assert written is not None
    projected = json.loads(written.read_text(encoding="utf-8"))
    assert projected["$schema"] == "https://example.invalid/mcp"

    cleanup_projected_mcp(written)
    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored == {"$schema": "https://example.invalid/mcp", "mcpServers": {}}


# ---------------------------------------------------------------------------
# Confinement settings (run-workspace .claude/settings.local.json)
# ---------------------------------------------------------------------------


def test_confinement_settings_enable_declared_and_deny_the_rest(
    tmp_path: Path,
) -> None:
    """Declared names are enabled; ancestor and ambient names are pinned out."""
    _write_mcp(tmp_path, ["ancestor-server"])
    run_ws = tmp_path / "run"
    run_ws.mkdir()
    ambient = tmp_path / ".claude.json"
    ambient.write_text(
        json.dumps({"mcpServers": {"operator-global": {"command": "x"}}}),
        encoding="utf-8",
    )

    path = project_confinement_settings(run_ws, [_rag_spec()])
    assert path is not None
    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["enableAllProjectMcpServers"] is False
    assert settings["enabledMcpjsonServers"] == ["vaultspec-rag"]
    assert "ancestor-server" in settings["disabledMcpjsonServers"]
    assert "mcp__ancestor-server" in settings["permissions"]["deny"]
    # The declared name is never denied.
    assert "vaultspec-rag" not in settings.get("disabledMcpjsonServers", [])
    assert "mcp__vaultspec-rag" not in settings["permissions"]["deny"]
    # The ambient user-global enumeration is injectable and feeds the deny set.
    assert ambient_user_mcp_names(ambient) == ["operator-global"]


def test_confinement_settings_deny_the_ambient_user_global_names(
    tmp_path: Path,
) -> None:
    """The ambient user-global surface reaches the deny set via the enumerator."""
    names = ambient_user_mcp_names(tmp_path / "missing.json")
    assert names == []  # absent file contributes nothing
    ambient = tmp_path / ".claude.json"
    ambient.write_text(
        json.dumps({"mcpServers": {"writable-global": {}, "another": {}}}),
        encoding="utf-8",
    )
    assert ambient_user_mcp_names(ambient) == ["another", "writable-global"]


def test_confinement_settings_written_only_for_an_armed_run(tmp_path: Path) -> None:
    """A run with nothing declared leaves the workspace untouched."""
    assert project_confinement_settings(tmp_path, []) is None
    assert not (tmp_path / ".claude").exists()


def test_confinement_settings_merge_over_the_workspace_own_settings(
    tmp_path: Path,
) -> None:
    """A workspace's own settings survive the merge and are restored at cleanup.

    Observed live: a real run workspace carries its own ``settings.local.json``
    with a WebFetch domain allowlist the run's web grounding depends on.
    Replacing it would break the run; refusing would refuse the normative case.
    The confinement policy merges OVER it and cleanup restores it exactly.
    """
    _write_mcp(tmp_path, ["ancestor-server"])
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    own = settings_dir / "settings.local.json"
    original = {
        "permissions": {
            "allow": ["WebFetch(domain:api.github.com)", "WebSearch"],
            "deny": ["Bash"],
        },
        "someForeignKey": True,
    }
    own.write_text(json.dumps(original), encoding="utf-8")

    path = project_confinement_settings(tmp_path, [_rag_spec()])
    assert path == own
    merged = json.loads(own.read_text(encoding="utf-8"))
    # The workspace's own policy survives the merge...
    assert merged["someForeignKey"] is True
    assert "WebSearch" in merged["permissions"]["allow"]
    assert "Bash" in merged["permissions"]["deny"]
    # ...with the confinement policy layered on top.
    assert merged["enableAllProjectMcpServers"] is False
    assert merged["enabledMcpjsonServers"] == ["vaultspec-rag"]
    assert "mcp__ancestor-server" in merged["permissions"]["deny"]

    cleanup_confinement_settings(path)
    assert json.loads(own.read_text(encoding="utf-8")) == original


def test_confinement_cleanup_never_touches_a_markerless_file(tmp_path: Path) -> None:
    """A settings file without our marker is foreign and is left untouched."""
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    foreign = settings_dir / "settings.local.json"
    foreign.write_text(
        json.dumps({"permissions": {"deny": ["Bash"]}}), encoding="utf-8"
    )
    cleanup_confinement_settings(foreign)
    assert json.loads(foreign.read_text(encoding="utf-8")) == {
        "permissions": {"deny": ["Bash"]}
    }


def test_confinement_settings_overwrite_own_crash_residue(tmp_path: Path) -> None:
    """A marker-carrying file from a crashed run is ours to rewrite."""
    first = project_confinement_settings(tmp_path, [_rag_spec()])
    assert first is not None  # crash here: no cleanup runs
    second = project_confinement_settings(tmp_path, [_rag_spec()])
    assert second == first
    settings = json.loads(second.read_text(encoding="utf-8"))
    assert settings["enabledMcpjsonServers"] == ["vaultspec-rag"]


def test_confinement_cleanup_removes_file_and_empty_dir(tmp_path: Path) -> None:
    """Cleanup restores the workspace to its pre-run shape."""
    path = project_confinement_settings(tmp_path, [_rag_spec()])
    assert path is not None
    cleanup_confinement_settings(path)
    assert not path.exists()
    assert not (tmp_path / ".claude").exists()
    cleanup_confinement_settings(path)  # idempotent, None-safe below
    cleanup_confinement_settings(None)
