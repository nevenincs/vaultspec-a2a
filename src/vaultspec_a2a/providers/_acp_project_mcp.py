"""Project the declared MCP surface into the run workspace's ``.mcp.json``.

The pinned CLI/adapter path does NOT surface user-scope config-home ``mcpServers``
to the model, but it DOES read PROJECT-scope ``.mcp.json`` files - collected from
every ancestor directory of the run cwd, with ``${VAR}`` placeholders expanded
from the process environment and (binary-verified) auto-approved in a
non-interactive session. This module makes that the deliberate surfacing channel:
it MERGES the declared harness servers plus the run's authoring bridge into the run
workspace's own ``.mcp.json``, in the same placeholder-env shape the isolated home
admits, so the real tokens ride the spawn env and never touch disk.

A real vaultspec project root near-universally carries its own git-tracked
``.mcp.json``. Rather than refuse (which hard-fails the normative production case)
or replace (which would hide the project's own servers), the writer adds the
declared entries ALONGSIDE the project's own and records exactly which keys it
added. Ownership is entry-level, not file-level:

- **Marked-entry merge.** The projected file carries a signature marker listing the
  entry names this run added plus a fingerprint of the pre-merge file. Cleanup
  removes EXACTLY those keys and the marker - a foreign entry, or one a user added
  mid-run, is never touched. The file is deleted only when the pre-merge state was
  absent and nothing foreign remains.
- **Loud refusal, narrowed.** Projection refuses only when a declared server name
  collides with an existing NON-projected entry (silent shadowing either way is
  unacceptable) or the existing file is unparseable. A foreign file with no name
  overlap is merged, not refused.
- **Crash-residue idempotency.** A re-projection over a file still carrying a stale
  marker first inverts that marker to recover the original base, then merges fresh,
  carrying the ORIGINAL pre-merge state forward so a later cleanup still restores it.
- **Legacy marker.** A pre-merge-release whole-file marker (``true``) keeps its
  original whole-file removal semantics for one transition release.
- **Ancestor deny set.** :func:`enumerate_ancestor_mcp_names` mirrors the binary's
  own walk (cwd to filesystem root, every ``.mcp.json``), subsuming the single
  level of the harness deny-pin. The caller denies ``enumerated - declared`` so a
  server declared in an ancestor tree cannot ride in beside the projected set. This
  decision is upstream of the merge and unchanged by it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..thread.errors import ProjectionRefusedError
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
# presence proves the entries WE added are ours to remove; a ``.mcp.json`` schema
# reader consumes ``mcpServers`` and ignores unknown top-level keys, so the marker
# is inert to the CLI. Two shapes are recognised:
#   - dict (current): ``{"added": [names], "base_absent": bool,
#     "base_fingerprint": str | None}`` - entry-level ownership.
#   - ``True`` (legacy, one transition release): the whole file was ours;
#     cleanup removes it wholesale, as the pre-merge release did.
PROJECTION_MARKER_KEY = "_vaultspec_projection"


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


def _fingerprint(base: dict[str, Any]) -> str:
    """A content fingerprint of a pre-merge base (``mcpServers`` plus other
    top-level keys), enforced at cleanup and re-projection - not diagnostic-only.

    Hashes a canonical (sorted-key) JSON serialization of the PARSED base, not
    the file's raw text: our own writes always go through ``json.dumps``, so a
    raw-text fingerprint would spuriously mismatch on our own re-serialization
    (different key order/whitespace) even with zero tampering. A canonical hash
    survives our own round-trips while still changing on any semantic edit to
    the base a marker is supposed to protect.
    """
    canonical = json.dumps(base, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_unlink(path: Path) -> None:
    if path.exists():
        try:
            path.unlink()
        except OSError:
            logger.warning("failed to remove projected .mcp.json at %s", path)


def _recover_base(
    parsed: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool, str | None]:
    """Recover the pre-merge base from an existing parsed ``.mcp.json``.

    Returns ``(base_servers, base_other, base_absent, base_fingerprint)`` where
    ``base_other`` is the file's non-``mcpServers``/non-marker top-level keys. A
    dict marker is a crash residue: its ``added`` keys are stripped to recover the
    base, and the ORIGINAL pre-merge state it recorded is carried forward - BUT
    only when the stripped result's fingerprint still matches the marker's
    recorded ``base_fingerprint``. A mismatch means the file was hand-edited since
    the crash (the marker's ``added`` list no longer accurately describes what is
    actually ours to strip), so the stale added-list is NOT trusted: the base
    falls back to the FULL current ``mcpServers`` (nothing stripped), fingerprinted
    fresh, so the caller's collision check judges every name currently present as
    an existing entry rather than silently reusing a slot we can no longer verify.
    A legacy ``true`` marker means the whole file was ours (only ever written over
    an absent file), so the base is empty and absent. No marker means a genuine
    foreign file: its content IS the base, present and fingerprinted.
    """
    servers_raw = parsed.get("mcpServers")
    servers: dict[str, Any] = dict(servers_raw) if isinstance(servers_raw, dict) else {}
    other = {
        k: v
        for k, v in parsed.items()
        if k not in ("mcpServers", PROJECTION_MARKER_KEY)
    }
    marker = parsed.get(PROJECTION_MARKER_KEY)

    if marker is True:
        # Legacy whole-file projection: everything was ours; original was absent.
        return {}, {}, True, None
    if isinstance(marker, dict):
        # Crash residue from this model: strip our prior additions, carry the
        # ORIGINAL pre-merge state forward so a later cleanup still restores it -
        # but only once the stripped base's fingerprint is verified to still
        # match what the marker recorded.
        stripped = dict(servers)
        for name in marker.get("added") or []:
            stripped.pop(str(name), None)
        recorded_fingerprint = marker.get("base_fingerprint")
        base_absent = bool(marker.get("base_absent", False))
        if recorded_fingerprint is not None:
            recovered_fingerprint = _fingerprint({"mcpServers": stripped, **other})
            if recovered_fingerprint != recorded_fingerprint:
                logger.warning(
                    "stale projection marker's added-list no longer matches its"
                    " recorded base fingerprint (file hand-edited since a prior"
                    " crash); treating every currently-present server name as"
                    " existing rather than trusting the stale added-list"
                )
                fresh_fingerprint = _fingerprint({"mcpServers": servers, **other})
                return servers, other, False, fresh_fingerprint
        return stripped, other, base_absent, recorded_fingerprint
    # Foreign, marker-less file: its content is the base.
    return servers, other, False, _fingerprint({"mcpServers": servers, **other})


def project_declared_mcp(
    run_workspace: Path | str,
    mcp_servers: Sequence[dict[str, Any]],
) -> Path | None:
    """Merge the declared surfacing set into ``{run_workspace}/.mcp.json``.

    Adds the declared harness servers plus the run's authoring bridge (placeholder
    env; the real values ride the spawn env) ALONGSIDE any entries already present,
    and records the added names plus the pre-merge fingerprint in the marker.
    Returns the written path, or ``None`` when there is nothing to project (a
    non-armed run), leaving the workspace untouched.

    Refuses (``ProjectionRefusedError``) ONLY when a declared server name collides
    with an existing NON-projected entry, or the existing file is unparseable -
    silently shadowing either side, or projecting over a file we cannot reason
    about, is unacceptable. A foreign file with no name overlap is merged.
    """
    surfacing = _declared_home_entries(mcp_servers)
    if not surfacing:
        return None
    path = Path(run_workspace) / ".mcp.json"

    base_servers: dict[str, Any] = {}
    base_other: dict[str, Any] = {}
    base_absent = True
    base_fingerprint: str | None = None

    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, ValueError, TypeError) as exc:
            raise ProjectionRefusedError(
                f"refusing to project into an unparseable .mcp.json at {path}: "
                f"{exc}. Repair or remove the file, or use a clean run workspace."
            ) from exc
        if not isinstance(parsed, dict):
            raise ProjectionRefusedError(
                f"refusing to project into {path}: top-level JSON is not an object."
            )
        base_servers, base_other, base_absent, base_fingerprint = _recover_base(parsed)

    collisions = sorted(set(surfacing) & set(base_servers))
    if collisions:
        raise ProjectionRefusedError(
            f"refusing to project into {path}: declared server name(s) {collisions} "
            "collide with existing non-projected entries. Rename the project's "
            "server or the declared surface so neither silently shadows the other."
        )

    merged = dict(base_servers)
    merged.update(surfacing)
    content: dict[str, Any] = {
        **base_other,
        "mcpServers": merged,
        PROJECTION_MARKER_KEY: {
            "added": sorted(surfacing),
            "base_absent": base_absent,
            "base_fingerprint": base_fingerprint,
        },
    }
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    logger.debug(
        "projected %d declared MCP server(s) into %s (base_absent=%s)",
        len(surfacing),
        path,
        base_absent,
    )
    return path


def cleanup_projected_mcp(path: Path | None) -> None:
    """Invert exactly what :func:`project_declared_mcp` added; never raises.

    Removes only the marker's ``added`` keys and the marker itself, then deletes the
    file only when the pre-merge state was absent AND nothing foreign remains -
    otherwise it writes back the surviving entries (the project's own, plus anything
    a user added mid-run) with the marker gone. A legacy ``true`` marker keeps the
    pre-merge whole-file removal. A file with no marker of ours is never touched.

    Enforced, not diagnostic-only: when a recorded ``base_fingerprint`` is present,
    the recovered base (current ``mcpServers`` minus the marker's ``added`` names,
    plus the other top-level keys) must still fingerprint to that value. A mismatch
    means the marker or the base was hand-edited since we wrote it - the marker's
    ``added`` list can no longer be trusted to name only entries that are truly
    ours, so inversion is SKIPPED entirely (the file is left exactly as found) and
    the desync is logged at WARNING naming the file, rather than risk popping a
    hand-added entry that merely happens to share one of our reserved names.
    """
    if path is None:
        return
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(parsed, dict):
        return
    marker = parsed.get(PROJECTION_MARKER_KEY)

    if marker is True:
        _safe_unlink(path)
        return
    if not isinstance(marker, dict):
        # Foreign / not ours - never touch.
        return

    servers_raw = parsed.get("mcpServers")
    servers: dict[str, Any] = dict(servers_raw) if isinstance(servers_raw, dict) else {}
    other = {
        k: v
        for k, v in parsed.items()
        if k not in ("mcpServers", PROJECTION_MARKER_KEY)
    }

    recovered: dict[str, Any] = dict(servers)
    for name in marker.get("added") or []:
        # Remove ONLY what we added; a same-named entry a user re-added mid-run is
        # theirs now and survives (the marker's list is the authoritative scope).
        recovered.pop(str(name), None)

    recorded_fingerprint = marker.get("base_fingerprint")
    if recorded_fingerprint is not None:
        recovered_fingerprint = _fingerprint({"mcpServers": recovered, **other})
        if recovered_fingerprint != recorded_fingerprint:
            logger.warning(
                "skipping projection cleanup for %s: the recovered base no"
                " longer matches the marker's recorded fingerprint (hand-edited"
                " since projection); leaving the file untouched rather than"
                " trusting a desynced added-list",
                path,
            )
            return

    if bool(marker.get("base_absent", False)) and not recovered and not other:
        # We created the file and nothing foreign remains - restore the absent state.
        _safe_unlink(path)
        return

    restored: dict[str, Any] = {**other, "mcpServers": recovered}
    try:
        path.write_text(json.dumps(restored, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("failed to restore pre-merge .mcp.json at %s", path)
