"""Unit tests for the run-workspace MCP projection channel.

Real filesystem, no mocks: the module reads and writes real ``.mcp.json`` files.
Bridge specs come through the production builder seam
(``build_authoring_stdio_mcp_servers``), so the projected file is asserted against
the same shape the isolated home admits.
"""

from __future__ import annotations

import json
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


# --- ancestor enumeration -------------------------------------------------


def test_enumerate_ancestor_walks_every_level_to_root(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = a / "b"
    c = b / "c"
    c.mkdir(parents=True)
    _write_mcp(tmp_path, ["root-srv"])
    _write_mcp(a, ["a-srv"])
    _write_mcp(c, ["c-srv"])
    names = enumerate_ancestor_mcp_names(c)
    # Union across the cwd and every ancestor to the filesystem root (b has none).
    assert {"root-srv", "a-srv", "c-srv"} <= set(names)
    assert names == sorted(names)


def test_enumerate_ancestor_best_effort(tmp_path: Path) -> None:
    assert enumerate_ancestor_mcp_names(None) == []
    d = tmp_path / "empty"
    d.mkdir()
    # No .mcp.json anywhere under tmp_path's created dirs contributes names.
    (tmp_path / ".mcp.json").write_text("{not json", encoding="utf-8")
    # Malformed ancestor file contributes nothing rather than raising.
    assert "root-srv" not in enumerate_ancestor_mcp_names(d)


# --- projection write -----------------------------------------------------


def test_project_writes_declared_with_marker_and_placeholders(tmp_path: Path) -> None:
    specs = [_rag_spec(), *_bridge_specs(bearer="SECRET-BEARER", actor="SECRET-ACTOR")]
    path = project_declared_mcp(tmp_path, specs)
    assert path == tmp_path / ".mcp.json"
    content = json.loads(path.read_text(encoding="utf-8"))
    assert content[PROJECTION_MARKER_KEY] is True
    servers = content["mcpServers"]
    # Declared harness server + the authoring bridge, nothing else.
    assert set(servers) == {"vaultspec-rag", "vaultspec-authoring"}
    # Bridge env carries placeholders, NEVER the real tokens (they ride spawn env).
    text = path.read_text(encoding="utf-8")
    assert "${VAULTSPEC_AUTHORING_BEARER}" in text
    assert "SECRET-BEARER" not in text
    assert "SECRET-ACTOR" not in text


def test_project_returns_none_when_nothing_declared(tmp_path: Path) -> None:
    # No harness server and no bridge -> nothing to project, workspace untouched.
    assert project_declared_mcp(tmp_path, []) is None
    assert not (tmp_path / ".mcp.json").exists()


def test_project_refuses_foreign_mcp_json(tmp_path: Path) -> None:
    foreign = {"mcpServers": {"user-srv": {"type": "stdio", "command": "x"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(foreign), encoding="utf-8")
    with pytest.raises(ProjectionRefusedError, match="marker"):
        project_declared_mcp(tmp_path, [_rag_spec()])
    # The foreign file is untouched.
    assert json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8")) == foreign


def test_project_overwrites_own_marked_file(tmp_path: Path) -> None:
    project_declared_mcp(tmp_path, [_rag_spec()])
    # A second projection replaces our own prior file without refusal.
    path = project_declared_mcp(tmp_path, [_rag_spec(), *_bridge_specs()])
    assert path is not None
    servers = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"vaultspec-rag", "vaultspec-authoring"}


# --- deny-set composition -------------------------------------------------


def test_deny_set_is_ancestor_enumeration_minus_declared(tmp_path: Path) -> None:
    # An ancestor declares a foreign server AND (adversarially) a name equal to a
    # declared one; the caller's deny set is enumerated - declared, so the declared
    # name is never denied while the foreign one is.
    _write_mcp(tmp_path, ["foreign-srv", "vaultspec-rag"])
    run_ws = tmp_path / "run"
    run_ws.mkdir()
    specs = [_rag_spec()]
    declared = set(projected_declared_names(specs))
    enumerated = set(enumerate_ancestor_mcp_names(run_ws))
    deny = enumerated - declared
    assert "foreign-srv" in deny
    assert "vaultspec-rag" not in deny  # declared -> surfaced, never denied


# --- cleanup --------------------------------------------------------------


def test_cleanup_removes_only_our_marked_file(tmp_path: Path) -> None:
    path = project_declared_mcp(tmp_path, [_rag_spec()])
    assert path is not None and path.exists()
    cleanup_projected_mcp(path)
    assert not path.exists()
    # A foreign file at the same path is never removed by cleanup.
    foreign = {"mcpServers": {}}
    path.write_text(json.dumps(foreign), encoding="utf-8")
    cleanup_projected_mcp(path)
    assert path.exists()
    cleanup_projected_mcp(None)  # None-safe
