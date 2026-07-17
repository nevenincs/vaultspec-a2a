"""Unit tests for the per-run isolated CLI config home (ambient-MCP suppression).

Real filesystem, no mocks: the module writes a real directory and JSON file. The
live surfacing/suppression behavior on the real adapter is proven separately in
the P03.S14 exec record; these assert the isolation logic the harness relies on.
"""

from __future__ import annotations

import json

from .._acp_config_home import (
    cleanup_isolated_config_home,
    create_isolated_config_home,
    should_isolate_config_home,
)

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
    finally:
        cleanup_isolated_config_home(home)


def test_cleanup_is_idempotent_and_none_safe() -> None:
    cleanup_isolated_config_home(None)  # no raise
    home = create_isolated_config_home()
    cleanup_isolated_config_home(home)
    assert not home.exists()
    cleanup_isolated_config_home(home)  # second call on a gone dir: no raise
