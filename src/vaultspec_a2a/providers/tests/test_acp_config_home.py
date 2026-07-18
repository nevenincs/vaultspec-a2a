"""Unit tests for the per-run isolated CLI config home (ambient-MCP suppression).

Real filesystem, no mocks: the module writes a real directory and JSON file. The
live surfacing/suppression behavior on the real adapter is proven separately in
the P03.S14 exec record; these assert the isolation logic the harness relies on.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ...authoring import AgentTool, CatalogSnapshot
from .._acp_authoring import (
    AuthoringToolBinding,
    build_authoring_stdio_mcp_servers,
    config_home_authoring_entry,
)
from .._acp_config_home import (
    cleanup_isolated_config_home,
    create_isolated_config_home,
    enumerate_workspace_mcp_names,
    isolation_required_but_absent,
    should_isolate_config_home,
)
from .._acp_mcp import config_home_mcp_servers

if TYPE_CHECKING:
    from pathlib import Path

_CLAUDE_NODE_CMD = [
    "node",
    "/x/node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js",
]
_GEMINI_CMD = ["gemini", "--experimental-acp"]


def test_isolate_gated_on_env_token_for_claude_path() -> None:
    assert should_isolate_config_home(
        _CLAUDE_NODE_CMD, {"CLAUDE_CODE_OAUTH_TOKEN": "t"}
    )
    assert should_isolate_config_home(_CLAUDE_NODE_CMD, {"ANTHROPIC_AUTH_TOKEN": "t"})


def test_no_isolation_without_env_token() -> None:
    # Without env-carried auth the run depends on the operator's ~/.claude
    # credentials; redirecting the home would strand it, so isolation is skipped.
    assert not should_isolate_config_home(_CLAUDE_NODE_CMD, {})
    assert not should_isolate_config_home(
        _CLAUDE_NODE_CMD, {"CLAUDE_CODE_OAUTH_TOKEN": ""}
    )


def test_no_isolation_for_gemini_path() -> None:
    # Gemini has its own GEMINI_CLI_HOME; CLAUDE_CONFIG_DIR does not apply.
    assert not should_isolate_config_home(_GEMINI_CMD, {"CLAUDE_CODE_OAUTH_TOKEN": "t"})


def test_no_isolation_for_empty_command() -> None:
    assert not should_isolate_config_home([], {"CLAUDE_CODE_OAUTH_TOKEN": "t"})


def test_created_home_carries_onboarding_flags_and_no_servers() -> None:
    home = create_isolated_config_home()
    try:
        cfg_path = home / ".claude.json"
        assert cfg_path.exists()
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # Onboarding flags present so the CLI runs non-interactively.
        assert cfg["hasCompletedOnboarding"] is True
        # Suppression: the isolated home carries NO inherited/declared servers.
        assert "mcpServers" not in cfg
        # Security contract: NO credential file, and the home is EXACTLY the
        # config file - nothing that could leak auth or ambient config.
        assert not (home / ".credentials.json").exists()
        assert {p.name for p in home.iterdir()} == {".claude.json", "settings.json"}
    finally:
        cleanup_isolated_config_home(home)
        assert not home.exists()


def test_created_home_surfaces_given_servers() -> None:
    servers = {
        "vaultspec-rag": {
            "type": "stdio",
            "command": "uvx",
            "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
        }
    }
    home = create_isolated_config_home(servers)
    try:
        cfg = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
        # Onboarding flags AND the declared server, so it surfaces as user-global.
        assert cfg["hasCompletedOnboarding"] is True
        assert cfg["mcpServers"] == servers
        # Security contract holds even when populated: no credential file, and
        # the home is EXACTLY the config file.
        assert not (home / ".credentials.json").exists()
        assert {p.name for p in home.iterdir()} == {".claude.json", "settings.json"}
    finally:
        cleanup_isolated_config_home(home)


def _stdio_bridge_specs(*, bearer: str, actor: str) -> list[dict]:
    """Real authoring stdio bridge specs via the production builder seam."""
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
        run_id="run-zero-secret",
        bearer_token=bearer,
        actor_token=actor,
    )
    return build_authoring_stdio_mcp_servers(binding)


def test_authoring_bridge_home_is_placeholder_only_no_secret_on_disk() -> None:
    """The composed home surfaces the bridge with ${VAR} placeholders, no tokens.

    Mirrors the exact composition ``AcpChatModel`` performs at the spawn seam:
    ``config_home_mcp_servers`` unioned with ``config_home_authoring_entry``,
    written by ``create_isolated_config_home``. Asserts the zero-secret-on-disk
    contract: the placeholder literals are present, the real bearer/actor values
    are absent, and the home is EXACTLY ``.claude.json``.
    """
    bearer = "TOTALLY-SECRET-BEARER"
    actor = "TOTALLY-SECRET-ACTOR"
    specs = _stdio_bridge_specs(bearer=bearer, actor=actor)

    surfacing = config_home_mcp_servers(specs)
    bridge_entry, bridge_env = config_home_authoring_entry(specs)
    surfacing.update(bridge_entry)

    home = create_isolated_config_home(surfacing)
    try:
        text = (home / ".claude.json").read_text(encoding="utf-8")
        # Placeholders present on disk.
        assert "${VAULTSPEC_AUTHORING_BEARER}" in text
        assert "${VAULTSPEC_AUTHORING_ACTOR_TOKEN}" in text
        # Real token values NEVER on disk - they ride the spawn env only.
        assert bearer not in text
        assert actor not in text
        assert bridge_env["VAULTSPEC_AUTHORING_BEARER"] == bearer
        assert bridge_env["VAULTSPEC_AUTHORING_ACTOR_TOKEN"] == actor
        # Home is exactly the config file: no credential/ambient leak.
        assert not (home / ".credentials.json").exists()
        assert {p.name for p in home.iterdir()} == {".claude.json", "settings.json"}
    finally:
        cleanup_isolated_config_home(home)


def test_enumerate_workspace_mcp_names_reads_and_sorts_servers(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"zeta": {}, "alpha": {}}}), encoding="utf-8"
    )
    assert enumerate_workspace_mcp_names(tmp_path) == ["alpha", "zeta"]


def test_enumerate_workspace_mcp_names_best_effort(tmp_path: Path) -> None:
    # No workspace, no file, malformed JSON, and a file lacking mcpServers all
    # yield [] rather than raising - isolation setup never fails on a workspace
    # artifact.
    assert enumerate_workspace_mcp_names(None) == []
    assert enumerate_workspace_mcp_names(tmp_path) == []
    (tmp_path / ".mcp.json").write_text("{not valid json", encoding="utf-8")
    assert enumerate_workspace_mcp_names(tmp_path) == []
    (tmp_path / ".mcp.json").write_text(json.dumps({"other": 1}), encoding="utf-8")
    assert enumerate_workspace_mcp_names(tmp_path) == []


def test_settings_always_disables_project_mcp_autoload() -> None:
    # Even with no workspace .mcp.json, the home refuses to auto-enable any
    # project-scoped server, so a workspace file that appears after enumeration
    # still cannot auto-load (TOCTOU-safe).
    home = create_isolated_config_home()
    try:
        settings = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert settings["enableAllProjectMcpServers"] is False
        assert "disabledMcpjsonServers" not in settings
    finally:
        cleanup_isolated_config_home(home)


def test_settings_pins_out_workspace_mcp(tmp_path: Path) -> None:
    # A workspace .mcp.json (e.g. a stray vaultspec-core install, the S20 vector)
    # is pinned OUT three ways: no autoload, disabled by name, and tool-denied.
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"vaultspec-core": {}, "evil": {}}}),
        encoding="utf-8",
    )
    home = create_isolated_config_home(workspace_root=tmp_path)
    try:
        settings = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert settings["enableAllProjectMcpServers"] is False
        assert settings["disabledMcpjsonServers"] == ["evil", "vaultspec-core"]
        deny = settings["permissions"]["deny"]
        assert "mcp__evil" in deny
        assert "mcp__vaultspec-core" in deny
    finally:
        cleanup_isolated_config_home(home)


def test_fail_loud_armed_claude_without_isolated_home() -> None:
    # The S20/none_detected case: an armed Claude/Z.ai run that reached spawn with
    # no isolated home must fail loud.
    assert isolation_required_but_absent(
        acp_family="claude",
        command=_CLAUDE_NODE_CMD,
        mcp_servers=[{"name": "vaultspec-rag"}],
        config_home=None,
    )


def test_no_fail_loud_when_isolated_home_present(tmp_path: Path) -> None:
    assert not isolation_required_but_absent(
        acp_family="claude",
        command=_CLAUDE_NODE_CMD,
        mcp_servers=[{"name": "vaultspec-rag"}],
        config_home=tmp_path,
    )


def test_no_fail_loud_when_not_armed() -> None:
    # A non-harness run carries no MCP surface to protect; isolation is optional.
    assert not isolation_required_but_absent(
        acp_family="claude",
        command=_CLAUDE_NODE_CMD,
        mcp_servers=[],
        config_home=None,
    )


def test_no_fail_loud_for_kimi_or_gemini_channel() -> None:
    # Kimi (inline --config isolation) and Gemini (own home) are out of the
    # CLAUDE_CONFIG_DIR channel, so the config-home fail-loud does not apply.
    assert not isolation_required_but_absent(
        acp_family="kimi",
        command=["kimi", "acp"],
        mcp_servers=[{"name": "x"}],
        config_home=None,
    )
    assert not isolation_required_but_absent(
        acp_family="claude",
        command=_GEMINI_CMD,
        mcp_servers=[{"name": "x"}],
        config_home=None,
    )


def test_cleanup_is_idempotent_and_none_safe() -> None:
    cleanup_isolated_config_home(None)  # no raise
    home = create_isolated_config_home()
    cleanup_isolated_config_home(home)
    assert not home.exists()
    cleanup_isolated_config_home(home)  # second call on a gone dir: no raise
