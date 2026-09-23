"""Seat every pytest session inside the worktree it runs from.

A test session writes three kinds of state: pytest's own temporary trees, the
application state a code path under test falls back to, and the leases that
arbitrate contended resources between concurrent sessions. All three land under
``<rootdir>/.pytest-tmp``, which the repository ignores, and none reaches the
user profile or the operating system's temporary directory:

* ``sessions/<stamp>-<pid>/basetemp`` - pytest's ``--basetemp``, unique per
  controller so two concurrent sessions never wipe each other's trees.
* ``sessions/<stamp>-<pid>/home`` - the application state home.
* ``procs`` - the process registry and lease home, SHARED by every session of
  the worktree, because leases only arbitrate between sessions that can see one
  another.

Seating runs once per controller process, before the settings singleton is
imported, which is why the repository-root ``conftest.py`` calls it at import.
An xdist worker inherits its controller's seat through the environment. A nested
pytest run started by a test is its own controller and takes its own seat, so it
can never clear the basetemp its parent is still using.

A value the caller set explicitly is respected; a value inherited from a parent
session's seat is replaced, since it names the parent's private directories.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from ..control.infra_config import InfraConfig
from ..control.settings_base import ENV_PREFIX, ProjectSettings, env_name

__all__ = [
    "TEST_ROOT_NAME",
    "SessionSeat",
    "TestSessionSettings",
    "seat_test_session",
]

#: The ignored worktree directory every test artifact lives under.
TEST_ROOT_NAME = ".pytest-tmp"

#: Sessions older than this are pruned when a new session is seated.
_SESSION_RETENTION_SECONDS = 24 * 60 * 60
#: The newest sessions kept regardless of age, for triage of recent failures.
_SESSIONS_KEPT = 5


class TestSessionSettings(ProjectSettings):
    """The harness's own configuration, read from the process environment only.

    Never from a dotenv: these values describe one pytest process tree and are
    handed from a controller to its children, so a file on disk has no say.
    """

    __test__ = False

    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix=f"{ENV_PREFIX}TEST_",
        extra="ignore",
        env_ignore_empty=True,
    )

    session_root: Path | None = None
    session_pid: int | None = None
    seated_home: Path | None = None
    seated_procs_home: Path | None = None
    cpu_budget: int | None = Field(default=None, gt=0)
    completion_endpoint: str | None = None
    completion_owner_pid: int | None = None


class SessionSeat:
    """The directories one seated session writes to."""

    __slots__ = ("basetemp", "home", "procs_home", "root")

    def __init__(self, root: Path, procs_home: Path) -> None:
        self.root = root
        self.basetemp = root / "basetemp"
        self.home = root / "home"
        self.procs_home = procs_home


def _prune(sessions: Path, keep: Path) -> None:
    now = time.time()
    entries = sorted(
        (entry for entry in sessions.iterdir() if entry.is_dir() and entry != keep),
        key=lambda entry: entry.stat().st_mtime,
        reverse=True,
    )
    for entry in entries[_SESSIONS_KEPT:]:
        if now - entry.stat().st_mtime > _SESSION_RETENTION_SECONDS:
            shutil.rmtree(entry, ignore_errors=True)


def _seat_env(field: str, value: Path, previously_seated: Path | None) -> None:
    """Point one settings variable at the seat unless the caller chose it."""
    name = env_name(InfraConfig, field)
    current = os.environ.get(name)
    if current and (previously_seated is None or Path(current) != previously_seated):
        return
    os.environ[name] = str(value)


def _is_xdist_worker() -> bool:
    """Whether this process is an xdist worker, which runs inside its controller's seat.

    xdist's ``PYTEST_XDIST_WORKER`` alone cannot say: a nested pytest a test
    starts from inside a worker inherits it, and taking that nested controller
    for a worker hands it the parent's seat, whose basetemp its own xdist then
    clears out from under the parent. The worker itself is started by execnet as
    ``python -c``, which a nested ``python -m pytest`` never is.
    """
    return "PYTEST_XDIST_WORKER" in os.environ and sys.argv[:1] == ["-c"]


def seat_test_session(rootdir: Path) -> SessionSeat:
    """Seat this controller's session under ``rootdir``; idempotent per process."""
    harness = TestSessionSettings()
    procs_home = rootdir / TEST_ROOT_NAME / "procs"
    inherited = harness.session_root is not None and (
        harness.session_pid == os.getpid() or _is_xdist_worker()
    )
    if inherited and harness.session_root is not None:
        return SessionSeat(
            harness.session_root, harness.seated_procs_home or procs_home
        )
    sessions = rootdir / TEST_ROOT_NAME / "sessions"
    root = sessions / f"{time.strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
    seat = SessionSeat(root, procs_home)
    seat.basetemp.parent.mkdir(parents=True, exist_ok=True)
    seat.home.mkdir(parents=True, exist_ok=True)
    seat.procs_home.mkdir(parents=True, exist_ok=True)
    _prune(sessions, keep=root)
    _seat_env("a2a_home", seat.home, harness.seated_home)
    _seat_env("procs_home", seat.procs_home, harness.seated_procs_home)
    fields = TestSessionSettings
    os.environ[env_name(fields, "session_root")] = str(root)
    os.environ[env_name(fields, "session_pid")] = str(os.getpid())
    os.environ[env_name(fields, "seated_home")] = str(seat.home)
    os.environ[env_name(fields, "seated_procs_home")] = str(seat.procs_home)
    return seat
