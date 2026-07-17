"""Per-run isolated CLI config home for the Claude / Z.ai ACP path.

The spawned Claude Code CLI resolves its user-global configuration - the
``mcpServers`` it advertises and the operator account's connected remote MCP
servers - from ``CLAUDE_CONFIG_DIR`` (defaulting to ``~/.claude``). Left unset, a
worker inherits the operator's user-global MCP servers, INCLUDING any writable
one, plus the operator account's connected remote MCP servers, violating the
harness invariant that the spawned agent's MCP surface be exactly the declared
set (agent-harness-provisioning ADR).

This module redirects ``CLAUDE_CONFIG_DIR`` to a per-run directory carrying only
the onboarding flags the CLI needs to run non-interactively. Auth rides the
``CLAUDE_CODE_OAUTH_TOKEN`` / ``ANTHROPIC_AUTH_TOKEN`` env, so NO credential file
is written into the home and the operator's per-connector OAuth (which drives the
account's remote MCP connectors) is absent - suppressing those connectors as a
side effect. This is the ambient-MCP suppression the harness ADR requires,
independent of the surfacing outcome.

Empirically verified on adapter ``@agentclientprotocol/claude-agent-acp@0.59.0``
(vendored SDK 0.3.207): with a redirected home carrying only onboarding flags and
token-env auth, the operator's account connectors do not surface to the model.
The config-home population that makes declared read-only servers SURFACE is added
separately (P03.S14); this module owns the isolation.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

__all__ = [
    "cleanup_isolated_config_home",
    "create_isolated_config_home",
    "should_isolate_config_home",
]

logger = logging.getLogger(__name__)

# Minimal flags that keep the freshly-created config home from stalling the CLI
# on first-run onboarding / survey prompts in a non-interactive session.
_ONBOARDING_FLAGS: dict[str, object] = {
    "hasCompletedOnboarding": True,
    "hasCompletedClaudeInChromeOnboarding": True,
    "bypassPermissionsModeAccepted": True,
}

# Env names whose presence means auth is carried by the environment (token), so
# redirecting the config home away from the operator's ``~/.claude`` does not
# strand the run without credentials.
_ENV_AUTH_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")


def should_isolate_config_home(command: list[str], env: dict[str, str]) -> bool:
    """Return whether this spawn should get an isolated CLI config home.

    Only the Claude / Z.ai ``claude-agent-acp`` path uses ``CLAUDE_CONFIG_DIR``;
    the Gemini CLI path has its own ``GEMINI_CLI_HOME`` and is left untouched.
    Isolation is gated on env-carried auth: without a token in the environment the
    run would depend on the operator's ``~/.claude`` credentials, which the
    redirect removes - so a non-token run is left on the ambient home unchanged.
    """
    if not command:
        return False
    if Path(command[0]).stem.lower() == "gemini":
        return False
    return any(env.get(key, "").strip() for key in _ENV_AUTH_KEYS)


def create_isolated_config_home(
    mcp_servers: dict[str, dict[str, object]] | None = None,
) -> Path:
    """Create and return a fresh per-run ``CLAUDE_CONFIG_DIR``.

    The home always carries the onboarding flags. When *mcp_servers* is provided
    (P03.S14) they are written as the home's user-global ``mcpServers`` so the CLI
    SURFACES them to the model - the fallback the P02 re-probe made unconditional,
    since session-injected servers do not surface. Empty/None writes no servers, so
    the home performs suppression only. The caller sets ``CLAUDE_CONFIG_DIR`` to the
    returned path and MUST call :func:`cleanup_isolated_config_home` after the
    subprocess is reaped.
    """
    home = Path(tempfile.mkdtemp(prefix="vaultspec-acp-home-"))
    _write_config(home, mcp_servers=mcp_servers)
    logger.debug(
        "ACP isolated config home created at %s (surfacing %d server(s))",
        home,
        len(mcp_servers or {}),
    )
    return home


def _write_config(home: Path, mcp_servers: dict[str, dict[str, object]] | None) -> None:
    """Write the home's ``.claude.json`` with onboarding flags and optional servers."""
    config: dict[str, object] = dict(_ONBOARDING_FLAGS)
    if mcp_servers:
        config["mcpServers"] = mcp_servers
    (home / ".claude.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )


def cleanup_isolated_config_home(home: Path | None) -> None:
    """Best-effort removal of a per-run config home; never raises."""
    if home is None:
        return
    shutil.rmtree(home, ignore_errors=True)
