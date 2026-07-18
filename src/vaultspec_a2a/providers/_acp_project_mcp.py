"""Project the declared MCP surface into the run workspace's ``.mcp.json``.

The pinned CLI/adapter path does NOT surface user-scope config-home ``mcpServers``
to the model, but it DOES read PROJECT-scope ``.mcp.json`` files - collected from
every ancestor directory of the run cwd, with ``${VAR}`` placeholders expanded
from the process environment and (binary-verified) auto-approved in a
non-interactive session. This module makes that the deliberate surfacing channel:
it writes the run workspace's own ``.mcp.json`` carrying EXACTLY the declared
harness servers plus the run's authoring bridge, in the same placeholder-env shape
the isolated home admits, so the real tokens ride the spawn env and never touch
disk.

Two guards keep the channel honest:

- **Collision guard.** The projected file carries a signature marker; the writer
  REFUSES to overwrite a ``.mcp.json`` that lacks it, so a user's or a crashed
  run's real project config is never clobbered - the same admission philosophy as
  the isolated-home entries.
- **Ancestor deny set.** :func:`enumerate_ancestor_mcp_names` mirrors the binary's
  own walk (cwd to filesystem root, every ``.mcp.json``), subsuming the single
  level of the harness deny-pin. The caller denies ``enumerated - declared`` so a
  server declared in an ancestor tree cannot ride in beside the projected set.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._acp_authoring import config_home_authoring_entry
from ._acp_mcp import config_home_mcp_servers

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "PROJECTION_MARKER_KEY",
    "ProjectionRefusedError",
    "cleanup_projected_mcp",
    "enumerate_ancestor_mcp_names",
    "project_declared_mcp",
    "projected_declared_names",
]

logger = logging.getLogger(__name__)

# Signature marker written at the top level of a projected ``.mcp.json``. Its
# presence proves the file is ours to rewrite/remove; its absence means a foreign
# file we must never clobber. A ``.mcp.json`` schema reader consumes ``mcpServers``
# and ignores unknown top-level keys, so the marker is inert to the CLI.
PROJECTION_MARKER_KEY = "_vaultspec_projection"


class ProjectionRefusedError(RuntimeError):
    """Raised when the run workspace cannot host a projected ``.mcp.json``.

    A pre-existing ``.mcp.json`` without our signature marker is a foreign (user
    or crashed-run) file; refusing to overwrite it is fail-loud rather than
    silently destroying real project config.
    """


def _mcp_names(mcp_path: Path) -> set[str]:
    """Return the ``mcpServers`` names in one ``.mcp.json``; {} on any fault."""
    try:
        raw = mcp_path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("mcp config at %s is not valid JSON; ignoring", mcp_path)
        return set()
    servers = parsed.get("mcpServers") if isinstance(parsed, dict) else None
    if not isinstance(servers, dict):
        return set()
    return {str(name) for name in servers}


def enumerate_ancestor_mcp_names(start_dir: Path | str | None) -> list[str]:
    """Return MCP names from every ``.mcp.json`` from *start_dir* up to root.

    Mirrors the pinned binary's own project-scope collection walk: the cwd and
    each ancestor directory up to the filesystem root, unioning the ``mcpServers``
    names found in each ``.mcp.json``. Best-effort and side-effect-free - a missing
    or malformed file contributes nothing rather than raising. Returns the union
    sorted for deterministic output. Subsumes the single-level workspace
    enumeration of the harness deny-pin.
    """
    if start_dir is None:
        return []
    start = Path(start_dir).resolve()
    names: set[str] = set()
    for directory in (start, *start.parents):
        names |= _mcp_names(directory / ".mcp.json")
    return sorted(names)


def projected_declared_names(mcp_servers: Sequence[dict[str, Any]]) -> list[str]:
    """Return the server names this run would PROJECT (declared harness + bridge).

    These are the names the caller must keep OUT of the deny set (they are what
    the projection deliberately surfaces) and pass to ``enabledMcpjsonServers``.
    """
    return sorted(_declared_home_entries(mcp_servers))


def _declared_home_entries(
    mcp_servers: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Compose the declared surfacing entries (harness servers + authoring bridge).

    Reuses the exact isolated-home builders so the projected file and the home
    admit byte-for-byte the same specs (placeholder env, guarded bridge shape).
    """
    surfacing = config_home_mcp_servers(mcp_servers)
    bridge_entry, _spawn_env = config_home_authoring_entry(mcp_servers)
    surfacing.update(bridge_entry)
    return surfacing


def project_declared_mcp(
    run_workspace: Path | str,
    mcp_servers: Sequence[dict[str, Any]],
) -> Path | None:
    """Write ``{run_workspace}/.mcp.json`` with the declared surfacing set.

    The file carries ``mcpServers`` = the declared harness servers plus the run's
    authoring bridge (placeholder env; the real values ride the spawn env), and
    the signature marker. Returns the written path, or ``None`` when there is
    nothing to project (a non-armed run), leaving the workspace untouched.

    Refuses (``ProjectionRefusedError``) to overwrite an existing ``.mcp.json``
    that lacks our marker - a foreign file. An existing file that DOES carry the
    marker (a re-projection or a prior run in the same workspace) is replaced.
    """
    surfacing = _declared_home_entries(mcp_servers)
    if not surfacing:
        return None
    path = Path(run_workspace) / ".mcp.json"
    if path.exists() and not _is_projected(path):
        raise ProjectionRefusedError(
            f"refusing to overwrite a foreign .mcp.json at {path}: it lacks the "
            f"{PROJECTION_MARKER_KEY!r} projection marker (a user or crashed-run "
            "file). Use a clean scratch run workspace."
        )
    content: dict[str, Any] = {
        "mcpServers": surfacing,
        PROJECTION_MARKER_KEY: True,
    }
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    logger.debug(
        "projected %d declared MCP server(s) into %s", len(surfacing), path
    )
    return path


def _is_projected(path: Path) -> bool:
    """Return True when *path* is a ``.mcp.json`` we previously projected."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return isinstance(parsed, dict) and parsed.get(PROJECTION_MARKER_KEY) is True


def cleanup_projected_mcp(path: Path | None) -> None:
    """Best-effort removal of a projected ``.mcp.json``; never raises.

    Only removes a file we own (carries the marker), so a foreign file that
    somehow reached this path is never deleted.
    """
    if path is None:
        return
    if path.exists() and _is_projected(path):
        try:
            path.unlink()
        except OSError:
            logger.warning("failed to remove projected .mcp.json at %s", path)
