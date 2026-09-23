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

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_HOME",
    "DISCOVERY_RECORD",
    "ENGINE_DISCOVERY_RECORD",
    "HANDOFF_CREDENTIAL",
    "StateLayout",
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
