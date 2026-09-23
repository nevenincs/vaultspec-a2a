"""The one layout of a2a's mutable state beneath a state home.

Every place a2a writes derives its location here from a single state home, so
the default profile, a relocated home and the desktop application home share one
shape and one set of names:

* ``state/vaultspec.db`` and ``state/checkpoints.db`` - the stores.
* ``runtime/`` - process logs and runtime locks.
* ``service.json`` and ``service.token`` - the discovery record and its handoff
  credential, at the root so a reader finds them from the home alone.
* ``procs/`` - the development process registry, port reservations, leases.
* ``credentials/``, ``receipts/``, ``snapshots/``, ``workspaces/`` - desktop
  profile state.
* ``tmp/homes/`` - per-run provider configuration homes.

The home itself defaults to ``<project root>/.vault/data/agents``, the
framework-managed runtime subtree vaultspec already ignores and never walks.

This module is a leaf: the settings validators call it while the settings
singleton is still being constructed, so it imports nothing from the service.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .env_prefix import ENV_PREFIX

__all__ = [
    "DEFAULT_HOME",
    "DISCOVERY_RECORD",
    "ENGINE_DISCOVERY_RECORD",
    "HANDOFF_CREDENTIAL",
    "SEAL_FILE",
    "StateLayout",
    "UnsafeStateHomeError",
    "seal_state_home",
    "state_layout",
]

#: The state home's location relative to the project root when none is set.
DEFAULT_HOME = Path(".vault") / "data" / "agents"

#: The discovery record's file name at the root of a state home.
DISCOVERY_RECORD = "service.json"

#: Where the vaultspec engine publishes its own discovery record, relative to
#: the project root it serves.
ENGINE_DISCOVERY_RECORD = Path(".vault") / "data" / "engine-data" / DISCOVERY_RECORD

#: The bearer handoff credential's file name beside the discovery record.
HANDOFF_CREDENTIAL = "service.token"


#: The file that keeps a state home out of version control.
SEAL_FILE = ".gitignore"

# Ignores everything, itself included, so the home never shows as untracked. The
# project a state home lives in need not be a vaultspec project that already
# ignores .vault/data, and the home holds the gateway's handoff credential and
# copies of provider logins.
_SEAL_TEXT = (
    "# Written by vaultspec-a2a: runtime state and credentials, never committed.\n*\n"
)


logger = logging.getLogger(__name__)

#: Homes already reported as unsealable, so the warning is said once per process.
_UNSEALED_REPORTED: set[Path] = set()


class UnsafeStateHomeError(ValueError):
    """A state home that is itself a repository, which sealing would hide whole."""


def _holds_only_a2a_state(home: Path) -> bool:
    """Whether every entry in an existing ``home`` is one the state layout writes.

    Such a home is a2a's own even though a2a did not just create it - one made
    before homes were sealed, or by a concurrent writer that won the race.
    """
    layout = state_layout(home)
    owned = {
        path.relative_to(layout.home).parts[0]
        for path in (
            getattr(layout, field) for field in StateLayout.__dataclass_fields__
        )
        if path != layout.home
    }
    owned.add(SEAL_FILE)
    # The atomic writer stages the discovery record and its credential beside
    # themselves, so their temporary siblings carry the same prefix.
    staged = (DISCOVERY_RECORD, HANDOFF_CREDENTIAL)
    return all(
        entry.name in owned or entry.name.startswith(staged) for entry in home.iterdir()
    )


def seal_state_home(home: Path) -> None:
    """Create ``home`` and make it invisible to version control, idempotently.

    The seal ignores everything beneath it, so it is written only into a home
    a2a owns: one it creates here, or an existing one that holds nothing but
    the state layout. An existing directory with anything else in it belongs
    to the operator, who chose it; a2a writes no ignore file there, and says
    once that the state it writes there is not kept out of version control.

    Raises:
        UnsafeStateHomeError: If ``home`` is the root of a repository, which a
            seal would stop from tracking anything at all.
    """
    if (home / ".git").exists():
        msg = (
            f"refusing to use {home} as a2a state: it is the root of a "
            "repository, and sealing it would hide the whole repository from "
            f"version control. Point {ENV_PREFIX}HOME at a directory of its own."
        )
        raise UnsafeStateHomeError(msg)
    try:
        home.mkdir(parents=True)
        created = True
    except FileExistsError:
        created = False
    seal = home / SEAL_FILE
    if seal.exists():
        return
    if not created and not _holds_only_a2a_state(home):
        if home not in _UNSEALED_REPORTED:
            _UNSEALED_REPORTED.add(home)
            logger.warning(
                "%s already holds files a2a did not write, so a2a leaves it "
                "without an ignore file; keep the a2a state written there out of "
                "version control yourself, or point %sHOME at a directory of its "
                "own.",
                home,
                ENV_PREFIX,
            )
        return
    try:
        with seal.open("x", encoding="utf-8") as handle:
            handle.write(_SEAL_TEXT)
    except FileExistsError:
        # A concurrent writer sealed it first; the content is identical.
        return


@dataclass(frozen=True, slots=True)
class StateLayout:
    """Every mutable path a2a writes, derived from one state home."""

    home: Path
    database_path: Path
    checkpoint_path: Path
    logs_dir: Path
    discovery_path: Path
    handoff_credential_path: Path
    procs_dir: Path
    workspaces_root: Path
    credentials_dir: Path
    receipts_dir: Path
    temp_homes_dir: Path
    snapshots_dir: Path


def state_layout(home: Path) -> StateLayout:
    """Derive the state layout beneath an absolute state home."""
    root = Path(os.path.normpath(home))
    state = root / "state"
    return StateLayout(
        home=root,
        database_path=state / "vaultspec.db",
        checkpoint_path=state / "checkpoints.db",
        logs_dir=root / "runtime",
        discovery_path=root / DISCOVERY_RECORD,
        handoff_credential_path=root / HANDOFF_CREDENTIAL,
        procs_dir=root / "procs",
        workspaces_root=root / "workspaces",
        credentials_dir=root / "credentials",
        receipts_dir=root / "receipts",
        temp_homes_dir=root / "tmp" / "homes",
        snapshots_dir=root / "snapshots",
    )
