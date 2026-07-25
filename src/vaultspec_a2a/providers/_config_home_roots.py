"""Shared per-run config-home root resolution and orphan sweep.

Both the Claude/Z.ai ACP path (``_acp_config_home``) and the Codex path
(``_codex_config_home``) build a fresh, per-run CLI configuration directory for
every spawn. They diverge in everything that is genuinely CLI-specific - Claude
carries auth via an env token and writes JSON, Codex carries auth via a copied
``auth.json`` and writes TOML - so those two builders stay separate modules on
purpose.

What they do NOT diverge on is WHERE that per-run directory lives and HOW an
abandoned one gets reclaimed: an armed desktop install keeps every ephemeral
home under its own accounted application state directory (so an uninstall can
find them all, and a system-wide temp sweep cannot delete a live run's home out
from under it), and a home left behind by a crashed run is reclaimed once it is
stale enough that liveness can no longer plausibly be assumed. One root, one
sweep, two CLI-specific homes: this module is the single implementation of
those two shared concerns, parameterized only by the caller's own naming
prefix so a sweep for one CLI never collects a home belonging to the other.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

__all__ = [
    "ORPHAN_HOME_MIN_AGE_SECONDS",
    "sweep_orphan_homes",
    "temp_home_root",
]

logger = logging.getLogger(__name__)

ORPHAN_HOME_MIN_AGE_SECONDS = 24 * 60 * 60
"""How stale an abandoned home must be before the sweep reclaims it.

A home carries no owning process id, so age stands in for liveness. The window is
deliberately generous: deleting a live run's configuration is far worse than
keeping residue for another cycle.
"""


def temp_home_root() -> Path | None:
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
    if search_root is None:
        search_root = Path(tempfile.gettempdir())
    cutoff = time.time() - ORPHAN_HOME_MIN_AGE_SECONDS
    removed: list[Path] = []
    try:
        candidates = list(search_root.glob(f"{prefix}*"))
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
            "Swept %d orphaned config home(s) (prefix %r) from %s",
            len(removed),
            prefix,
            search_root,
        )
    return removed
