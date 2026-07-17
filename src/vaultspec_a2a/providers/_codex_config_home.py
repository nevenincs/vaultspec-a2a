"""Per-run isolated CODEX_HOME carrying the declared read-only MCP servers.

The structural analog of the Claude isolated config home (``_acp_config_home``),
expressed in Codex's native config shape. Codex resolves its MCP servers and
approval/sandbox config from ``CODEX_HOME`` (default ``~/.codex``); left on the
operator's home, a worker inherits every ambient ``[mcp_servers.*]`` block the
operator has (e.g. ``node_repl``, ``computer-use``), violating the harness
invariant that the agent's MCP surface be exactly the declared set.

This module builds a per-run, worker-owned ``CODEX_HOME`` whose ``config.toml``
carries EXACTLY the declared read-only harness servers as ``[mcp_servers.<name>]``
blocks. Codex auth is file-based (``auth.json``), so - unlike the Claude token-env
path - the base home's ``auth.json`` is copied in to preserve authentication;
nothing else is carried, so the operator's ambient MCP config is suppressed.

One registry (``_KNOWN_MCP_SERVERS``), two serializations: this is the Codex
transport for the same read-only servers the Claude home surfaces.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "build_codex_config_home",
    "cleanup_codex_config_home",
    "render_codex_config_toml",
]

logger = logging.getLogger(__name__)

# TOML bare-key charset; a server name outside it is quoted in the table header.
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_str(value: str) -> str:
    """Return a TOML basic string. JSON string escaping is a valid TOML subset
    for these values (double-quoted, backslash escapes for quotes/backslashes)."""
    return json.dumps(value)


def _toml_str_array(values: Sequence[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def _table_key(name: str) -> str:
    return name if _BARE_KEY.match(name) else _toml_str(name)


def _restrict(path: Path) -> None:
    """Best-effort owner-only permissions on a path; never raises.

    POSIX-effective (0o700 for the dir, applied to the credential copy too);
    a no-op on Windows, where the per-user temp tree is already ACL-scoped.
    """
    with suppress(OSError):
        path.chmod(0o700 if path.is_dir() else 0o600)


def render_codex_config_toml(specs: Sequence[dict[str, Any]]) -> str:
    """Render the ``config.toml`` body for the declared read-only servers.

    Emits one ``[mcp_servers.<name>]`` block per spec with ``command`` and
    ``args``, plus an ``[mcp_servers.<name>.env]`` sub-table when the spec carries
    env. The read-verb constraint (P04.S19) names the server's read ``tools`` in
    ``enabled_tools`` (an exact allowlist, so no write verb the server also exposes
    can be invoked) and sets ``default_tools_approval_mode = "auto"`` so those
    reads run without a prompt under the headless ``approval_policy = "never"``
    plus ``sandbox = "read-only"`` composition. Deterministic and stdlib-
    ``tomllib``-parseable.
    """
    blocks: list[str] = []
    for spec in specs:
        key = _table_key(spec["name"])
        lines = [f"[mcp_servers.{key}]", f"command = {_toml_str(spec['command'])}"]
        lines.append(f"args = {_toml_str_array(spec.get('args', ()))}")
        # Read-verb allowlist: exactly the registry's read tools, auto-approved.
        lines.append(f"enabled_tools = {_toml_str_array(spec.get('tools', ()))}")
        lines.append('default_tools_approval_mode = "auto"')
        env = spec.get("env") or {}
        block = "\n".join(lines)
        if env:
            env_lines = [f"[mcp_servers.{key}.env]"]
            env_lines += [f"{_table_key(k)} = {_toml_str(v)}" for k, v in env.items()]
            block = block + "\n\n" + "\n".join(env_lines)
        blocks.append(block)
    return "\n\n".join(blocks) + "\n" if blocks else ""


def build_codex_config_home(
    specs: Sequence[dict[str, Any]], base_home: Path | None
) -> Path:
    """Create a per-run ``CODEX_HOME`` carrying only the declared servers.

    Copies ``auth.json`` from *base_home* (if present) to preserve Codex's
    file-based auth, then writes a ``config.toml`` with exactly the declared
    ``[mcp_servers.<name>]`` blocks. The caller sets ``CODEX_HOME`` to the
    returned path and MUST call :func:`cleanup_codex_config_home` after reap.
    """
    # mkdtemp creates an owner-only (0700) directory, so the copied credential is
    # traversal-protected by the dir even before the file's own mode is set.
    home = Path(tempfile.mkdtemp(prefix="vaultspec-codex-home-"))
    try:
        _restrict(home)
        if base_home is not None:
            auth = base_home / "auth.json"
            if auth.exists():
                dest = home / "auth.json"
                shutil.copy2(auth, dest)
                # Defensive: pin the credential copy to owner-only regardless of
                # the source's mode (POSIX-effective; a no-op on Windows, where
                # the temp tree is already user-scoped).
                _restrict(dest)
        (home / "config.toml").write_text(
            render_codex_config_toml(specs), encoding="utf-8"
        )
    except BaseException:
        # A mid-build failure (e.g. copy error) must not leak the dir with a
        # partial credential copy; remove it before re-raising.
        cleanup_codex_config_home(home)
        raise
    logger.debug(
        "Codex isolated config home created at %s (%d server(s))", home, len(specs)
    )
    return home


def cleanup_codex_config_home(home: Path | None) -> None:
    """Best-effort removal of a per-run Codex config home; never raises."""
    if home is None:
        return
    shutil.rmtree(home, ignore_errors=True)
