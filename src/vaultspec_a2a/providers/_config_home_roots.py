"""Shared per-run config-home root resolution and orphan sweep.

The Codex path (``_codex_config_home``) builds a fresh, per-run CLI
configuration directory for every spawn. (The Claude/Z.ai ACP lane once carried
a sibling isolated home; it now runs in the operator's real config home under
the no-auth ambient-environment contract, and its MCP confinement rides
run-workspace projections instead.)

Two concerns stay shared here rather than in the CLI-specific builder: WHERE a
per-run directory lives and HOW an abandoned one gets reclaimed. Every profile
keeps its ephemeral homes inside the state home (so they are accounted for
with the rest of a2a's state, and a system-wide temp sweep cannot delete a
live run's home out from under it), and a home left behind by a crashed run is
reclaimed once it is stale enough that liveness can no longer plausibly be
assumed. The sweep is parameterized by the caller's own
naming prefix so it never collects a directory belonging to another product.
"""

from __future__ import annotations

import logging
import shutil
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ORPHAN_HOME_MIN_AGE_SECONDS", "sweep_orphan_homes", "temp_home_root"]

logger = logging.getLogger(__name__)

ORPHAN_HOME_MIN_AGE_SECONDS = 24 * 60 * 60
"""How stale an abandoned home must be before the sweep reclaims it.

A home carries no owning process id, so age stands in for liveness. The window is
deliberately generous: deleting a live run's configuration is far worse than
keeping residue for another cycle.
"""


def temp_home_root() -> Path:
    """Return the directory per-run config homes are created inside, creating it.

    The state home's ``tmp/homes``. There is no fallback to the system temporary
    directory: a home created there would copy a credential outside the state
    a2a accounts for, so an unwritable state home fails the run loudly instead.
    """
    from ..control.config import settings

    return settings.prepare_state_dir(settings.temp_homes_dir)


def _orphan_home_is_collectable(
    candidate: Path, *, keep: Path | None, cutoff: float
) -> bool:
    """Select an old directory while tolerating concurrent removal."""
    if not candidate.is_dir() or (keep is not None and candidate == keep):
        return False
    try:
        return candidate.stat().st_mtime <= cutoff
    except OSError:
        return False


def sweep_orphan_homes(
    *, prefix: str, keep: Path | None = None, root: Path | None = None
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
        prefix: The caller's own directory-name prefix (e.g. the Claude or
            Codex home prefix). Scoping the glob to it is what keeps a sweep for
            one CLI from ever collecting a home belonging to the other.
        keep: A home to leave alone regardless of age - the caller's own.
        root: Directory to sweep; defaults to the profile's temporary-home root.

    Returns:
        The homes removed, for the caller to log.
    """
    search_root = root if root is not None else temp_home_root()
    cutoff = time.time() - ORPHAN_HOME_MIN_AGE_SECONDS
    removed: list[Path] = []
    try:
        candidates = list(search_root.glob(f"{prefix}*"))
    except OSError:
        return removed
    for candidate in candidates:
        if not _orphan_home_is_collectable(candidate, keep=keep, cutoff=cutoff):
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        if not candidate.exists():
            removed.append(candidate)
    if removed:
        logger.info(
            "Swept %d orphaned config home(s) (prefix %r) from %s",
            len(removed),
            prefix,
            search_root,
        )
    return removed
