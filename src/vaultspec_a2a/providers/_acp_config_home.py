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
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

from ..artifacts import ArtifactDeclaration, RetentionDisposition
from ._acp_project_mcp import enumerate_ancestor_mcp_names

__all__ = [
    "ORPHAN_HOME_MIN_AGE_SECONDS",
    "PRESERVED_SESSION_LIMIT",
    "SESSION_RECORD_DECLARATION",
    "cleanup_isolated_config_home",
    "create_isolated_config_home",
    "isolation_required_but_absent",
    "preserve_session_record",
    "preserved_session_root",
    "should_isolate_config_home",
    "sweep_orphan_config_homes",
]

logger = logging.getLogger(__name__)

PRESERVED_SESSION_LIMIT = 20
"""How many preserved session records to keep before evicting the oldest."""

_HOME_PREFIX = "vaultspec-acp-home-"

ORPHAN_HOME_MIN_AGE_SECONDS = 24 * 60 * 60
"""How stale an abandoned home must be before the sweep reclaims it.

A home carries no owning process id, so age stands in for liveness. The window is
deliberately generous: deleting a live run's configuration is far worse than
keeping residue for another cycle.
"""

ORPHAN_HOME_DECLARATION = ArtifactDeclaration(
    name="acp-isolated-config-home",
    root="<desktop temp homes root, else system temp>/vaultspec-acp-home-<random>",
    owner="providers._acp_config_home",
    disposition=RetentionDisposition.SESSION_SCOPED,
    mechanism=(
        "removed at teardown when the run unwinds; a home left by a crash is "
        "reclaimed by sweep_orphan_config_homes once it is a day stale"
    ),
)

# Preservation only became defensible once it was bounded. The record this keeps
# is the agent's own account of a run, which is worth outliving the run - but an
# uncapped archive of transcripts would trade a small leak for a larger one.
SESSION_RECORD_DECLARATION = ArtifactDeclaration(
    name="agent-session-record",
    root="<a2a_home>/runtime/transcripts/<config-home-name>",
    owner="providers._acp_config_home",
    disposition=RetentionDisposition.BOUNDED_BY_SIZE,
    mechanism=(
        f"oldest-first eviction past {PRESERVED_SESSION_LIMIT} records, applied "
        "on every successful preservation"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (
    SESSION_RECORD_DECLARATION,
    ORPHAN_HOME_DECLARATION,
)

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


def isolation_required_but_absent(
    *,
    acp_family: str | None,
    command: list[str],
    mcp_servers: object,
    config_home: Path | None,
) -> bool:
    """Return True when an armed Claude/Z.ai run reached spawn without isolation.

    A harness-armed run (``mcp_servers`` non-empty) on the ``CLAUDE_CONFIG_DIR``
    isolation path (the ``claude`` acp family - Claude and Z.ai; Kimi has its own
    inline ``--config`` isolation, Gemini its own home) MUST spawn inside an
    isolated config home. Reaching spawn with ``config_home is None`` means the
    isolation was never established - almost always because ``auth_mode`` resolved
    to ``none_detected`` so :func:`should_isolate_config_home` declined - and the
    agent would inherit the operator's ambient MCP and auto-load the workspace
    ``.mcp.json``. The caller fails loud on a True return rather than launching an
    agent with an unbounded MCP surface. Pure predicate, no I/O, so the fail-loud
    decision is deterministically unit-testable.
    """
    uses_config_home_isolation = (
        acp_family == "claude"
        and bool(command)
        and Path(command[0]).stem.lower() != "gemini"
    )
    return uses_config_home_isolation and bool(mcp_servers) and config_home is None


def create_isolated_config_home(
    mcp_servers: Mapping[str, Mapping[str, object]] | None = None,
    workspace_root: Path | str | None = None,
) -> Path:
    """Create and return a fresh per-run ``CLAUDE_CONFIG_DIR``.

    The home always carries the onboarding flags. When *mcp_servers* is provided
    (P03.S14) they are written as the home's user-global ``mcpServers`` so the CLI
    SURFACES them to the model - the fallback the P02 re-probe made unconditional,
    since session-injected servers do not surface. The caller composes that mapping
    from the declared read-only harness servers plus, for a bridged run, the run's
    own authoring bridge entry (S18, ``config_home_authoring_entry``); a server's
    ``env`` value may be a ``${VAR}`` placeholder the CLI expands from its process
    environment at parse time, which is how the bridge keeps its real tokens off
    disk. Empty/None writes no servers, so the home performs suppression only.

    The home also always carries a ``settings.json`` governing the project-scope
    ``.mcp.json`` surface the adapter path DOES honour. The declared set (the keys
    of *mcp_servers* - the projected harness servers plus the run's authoring
    bridge) is explicitly enabled (``enabledMcpjsonServers``); every OTHER server
    discovered by walking ``.mcp.json`` from *workspace_root* to the filesystem
    root (``enumerate_ancestor_mcp_names``, minus the declared set) is disabled and
    tool-denied, and ``enableAllProjectMcpServers`` stays false so nothing else
    auto-enables. This closes the S20 ancestor leak - a ``vaultspec-core`` in a
    repo-root ``.mcp.json`` above the run workspace - while letting the projected
    declared set surface.

    The caller sets ``CLAUDE_CONFIG_DIR`` to the returned path and MUST call
    :func:`cleanup_isolated_config_home` after the subprocess is reaped.
    """
    home = Path(tempfile.mkdtemp(prefix=_HOME_PREFIX, dir=_temp_home_root()))
    # Reclaim what earlier crashed runs left behind, once per home creation - the
    # same boot-time cadence the worker-log sweep uses, and for the same reason:
    # there is no supervisor to run it on a schedule.
    with suppress(OSError):
        sweep_orphan_config_homes(keep=home)
    _write_config(home, mcp_servers=mcp_servers)
    declared = sorted(mcp_servers or {})
    declared_set = set(declared)
    denied = [
        name
        for name in enumerate_ancestor_mcp_names(workspace_root)
        if name not in declared_set
    ]
    _write_settings(home, disabled_server_names=denied, enabled_server_names=declared)
    logger.debug(
        "ACP isolated config home created at %s (surfacing %d server(s), "
        "enabling %d declared, pinning out %d ancestor MCP server(s))",
        home,
        len(mcp_servers or {}),
        len(declared),
        len(denied),
    )
    return home


def _write_config(
    home: Path, mcp_servers: Mapping[str, Mapping[str, object]] | None
) -> None:
    """Write the home's ``.claude.json`` with onboarding flags and optional servers."""
    config: dict[str, object] = dict(_ONBOARDING_FLAGS)
    if mcp_servers:
        config["mcpServers"] = {
            name: dict(server) for name, server in mcp_servers.items()
        }
    (home / ".claude.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def _write_settings(
    home: Path,
    *,
    disabled_server_names: list[str],
    enabled_server_names: list[str],
) -> None:
    """Write the home's ``settings.json`` governing project ``.mcp.json`` surface.

    Never auto-enable ANY project ``.mcp.json`` server wholesale
    (``enableAllProjectMcpServers`` false, always written). Explicitly enable the
    declared, projected set (``enabledMcpjsonServers``) so it surfaces. For every
    OTHER (ancestor) server, defense in depth: name it in
    ``disabledMcpjsonServers`` AND deny every tool via ``permissions.deny``
    (``mcp__<name>`` denies the whole server - binary-verified whole-server match).
    A name in both the enabled and disabled lists cannot occur: the caller
    computes disabled as the ancestor enumeration MINUS the declared set.
    """
    settings: dict[str, object] = {"enableAllProjectMcpServers": False}
    if enabled_server_names:
        settings["enabledMcpjsonServers"] = list(enabled_server_names)
    if disabled_server_names:
        settings["disabledMcpjsonServers"] = list(disabled_server_names)
        settings["permissions"] = {
            "deny": [f"mcp__{name}" for name in disabled_server_names]
        }
    (home / "settings.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )


def sweep_orphan_config_homes(
    *, keep: Path | None = None, root: Path | None = None
) -> list[Path]:
    """Remove per-run config homes abandoned by a process that never unwound.

    Teardown removes a home when the run unwinds, but a killed or crashed worker
    leaves one behind and nothing collects it.  On an armed desktop install that
    residue accumulates inside the application home, where no system-wide
    temporary sweep will ever reach it.

    A home carries no owning process id in its name, so liveness cannot be
    established the way the worker-log sweep establishes it from the process
    registry.  Age is the honest substitute: a home untouched for longer than
    :data:`ORPHAN_HOME_MIN_AGE_SECONDS` belonged to a run that is no longer
    writing to it.  The threshold is generous precisely because the cost of
    deleting a live run's home far exceeds the cost of keeping residue one more
    cycle.

    Args:
        keep: A home to leave alone regardless of age - the caller's own.
        root: Directory to sweep; defaults to the profile's temporary-home root.

    Returns:
        The homes removed, for the caller to log.
    """
    search_root = root if root is not None else _temp_home_root()
    if search_root is None:
        search_root = Path(tempfile.gettempdir())
    cutoff = time.time() - ORPHAN_HOME_MIN_AGE_SECONDS
    removed: list[Path] = []
    try:
        candidates = list(search_root.glob(f"{_HOME_PREFIX}*"))
    except OSError:
        return removed
    for candidate in candidates:
        if not candidate.is_dir() or (keep is not None and candidate == keep):
            continue
        try:
            if candidate.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            removed.append(candidate)
    if removed:
        logger.info(
            "Swept %d orphaned ACP config home(s) from %s", len(removed), search_root
        )
    return removed


def _temp_home_root() -> Path | None:
    """Return the directory per-run config homes are created inside.

    An armed desktop install keeps its ephemeral homes under its own application
    home, so an uninstall can account for them and a system-wide temporary sweep
    cannot remove a home out from under a live run.  Every other profile returns
    ``None``, which leaves the operating system temporary directory in charge -
    the right default for development, where a system sweep reclaiming an
    abandoned home is a feature rather than a hazard.

    Falls back to the operating system temporary directory if the declared root
    cannot be created: an unwritable state directory must not stop a run.
    """
    from ..control.config import settings

    declared = settings.desktop_temp_homes_dir
    if declared is None:
        return None
    try:
        declared.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning(
            "Could not create the declared temporary-home root %s; "
            "falling back to the system temporary directory",
            declared,
            exc_info=True,
        )
        return None
    return declared


def preserved_session_root() -> Path:
    """Return the declared root for preserved session records.

    Resolved here rather than by the caller so the location the declaration
    names and the location the code writes to cannot drift apart.  The import is
    deferred because this module sits on the provider spawn path, which must stay
    importable without pulling the settings model.
    """
    from ..control.config import settings

    return settings.a2a_home / "runtime" / "transcripts"


def preserve_session_record(
    home: Path | None, *, destination_root: Path
) -> Path | None:
    """Copy the CLI's own session record out of *home* before it is destroyed.

    The spawned CLI writes its transcript, history, and todo state beneath its
    config home.  That is the most complete account of what the agent actually
    did, and destroying the home discards it unread - a run leaves behind the
    events a viewer happened to be watching for and nothing else.

    Copies rather than moves, so a failure here can never cost the caller its
    teardown.  Best-effort by design: preservation must not be able to fail a
    run, and a run that cannot preserve is better than a run that crashes trying.

    Args:
        home: The config home about to be removed, or ``None``.
        destination_root: Directory to collect preserved records under.

    Returns:
        The directory the record was copied into, or ``None`` when there was
        nothing to preserve or the copy failed.
    """
    if home is None or not home.is_dir():
        return None
    sources = [
        candidate
        for candidate in (home / "projects", home / "history.jsonl", home / "todos")
        if candidate.exists()
    ]
    if not sources:
        return None
    destination = destination_root / home.name
    try:
        destination.mkdir(parents=True, exist_ok=True)
        for source in sources:
            target = destination / source.name
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
    except OSError:
        logger.warning(
            "Could not preserve the session record from %s", home, exc_info=True
        )
        return None
    _prune_preserved_records(destination_root)
    return destination


def _prune_preserved_records(destination_root: Path) -> None:
    """Keep only the most recent :data:`PRESERVED_SESSION_LIMIT` records.

    The cap is what makes preservation safe to enable.  An unbounded transcript
    archive would trade one leak for a larger one, which is the failure this
    package's governing decision exists to prevent.
    """
    try:
        # Name breaks ties: several records preserved inside one filesystem
        # timestamp tick would otherwise evict in an unstable order.
        records = sorted(
            (entry for entry in destination_root.iterdir() if entry.is_dir()),
            key=lambda entry: (entry.stat().st_mtime, entry.name),
            reverse=True,
        )
    except OSError:
        return
    for stale in records[PRESERVED_SESSION_LIMIT:]:
        shutil.rmtree(stale, ignore_errors=True)


def cleanup_isolated_config_home(home: Path | None) -> None:
    """Best-effort removal of a per-run config home; never raises."""
    if home is None:
        return
    shutil.rmtree(home, ignore_errors=True)
