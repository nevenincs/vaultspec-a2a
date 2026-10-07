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
singleton is still being constructed, so it imports nothing that reads settings.
Its one sibling import is the thread package's digest helper, which depends on
no other service module.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from ..thread import sha256_hex
from .env_prefix import ENV_PREFIX

__all__ = [
    "DEFAULT_HOME",
    "HANDOFF_CREDENTIAL",
    "SEAL_FILE",
    "StateLayout",
    "UnsafeStateHomeError",
    "engine_discovery_path",
    "seal_state_home",
    "state_layout",
]

#: The state home's location relative to the project root when none is set.
DEFAULT_HOME = Path(".vault") / "data" / "agents"

#: The discovery record's file name at the root of a state home.
DISCOVERY_RECORD = "service.json"

#: External per-project discovery namespace owned by the engine producer.
ENGINE_DISCOVERY_RECORD = Path(".vaultspec-engine") / "discovery"


def engine_discovery_path(project_root: Path) -> Path:
    """Locate protected engine state without trusting workspace discovery files."""
    identity = os.path.normcase(str(project_root.resolve())).encode("utf-8")
    project_key = sha256_hex(identity)
    # storage-anchor-ok: external producer state is owned by the engine, not A2A.
    engine_home = Path.home()  # storage-anchor-ok
    return engine_home / ENGINE_DISCOVERY_RECORD / project_key / DISCOVERY_RECORD


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
    owned = {path.relative_to(layout.home).parts[0] for path in layout.paths}
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
    """Every mutable path a2a writes, derived from one state home.

    The home is the only thing the layout holds, because the home is the only
    thing it is: every path below is a pure function of it, named once here so
    no caller spells a location of a2a's state for itself.
    """

    home: Path

    @property
    def _stores(self) -> Path:
        return self.home / "state"

    @property
    def database_path(self) -> Path:
        """The application database."""
        return self._stores / "vaultspec.db"

    @property
    def checkpoint_path(self) -> Path:
        """The graph checkpoint store."""
        return self._stores / "checkpoints.db"

    @property
    def authoring_calls_dir(self) -> Path:
        """Durable logical tool-call identities, partitioned by run and role."""
        return self._stores / "authoring-calls"

    @property
    def logs_dir(self) -> Path:
        """Process logs and runtime locks."""
        return self.home / "runtime"

    @property
    def discovery_path(self) -> Path:
        """The gateway discovery record, at the root of the home."""
        return self.home / DISCOVERY_RECORD

    @property
    def handoff_credential_path(self) -> Path:
        """The bearer handoff credential, beside the discovery record."""
        return self.home / HANDOFF_CREDENTIAL

    @property
    def procs_dir(self) -> Path:
        """The development process registry, port reservations and leases."""
        return self.home / "procs"

    @property
    def workspaces_root(self) -> Path:
        """The workspace tree runs are checked out into."""
        return self.home / "workspaces"

    @property
    def credentials_dir(self) -> Path:
        """Copies of provider logins seated for this home."""
        return self.home / "credentials"

    @property
    def receipts_dir(self) -> Path:
        """Durable receipts kept beyond a single run."""
        return self.home / "receipts"

    @property
    def temp_homes_dir(self) -> Path:
        """Per-run provider configuration homes."""
        return self.home / "tmp" / "homes"

    @property
    def snapshots_dir(self) -> Path:
        """Consistency-group snapshots of the state home."""
        return self.home / "snapshots"

    @property
    def paths(self) -> tuple[Path, ...]:
        """Every path beneath the home that a2a itself writes.

        The home is not among them: it is what the others are relative to.
        """
        return (
            self.database_path,
            self.checkpoint_path,
            self.authoring_calls_dir,
            self.logs_dir,
            self.discovery_path,
            self.handoff_credential_path,
            self.procs_dir,
            self.workspaces_root,
            self.credentials_dir,
            self.receipts_dir,
            self.temp_homes_dir,
            self.snapshots_dir,
        )


def state_layout(home: Path) -> StateLayout:
    """Derive the state layout beneath an absolute state home."""
    return StateLayout(home=Path(os.path.normpath(home)))
