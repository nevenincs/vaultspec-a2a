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
session's seat is replaced, since it names the parent's private directories. The
one class of value the seat always takes away is a variable naming a settings
FILE, which would hand the session a bundle of settings it never declared.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from ..control.settings_base import ENV_FILE_ENV, ProjectSettings, env_name
from .harness_names import TEST_ENV_PREFIX

__all__ = [
    "TEST_ROOT_NAME",
    "TestSessionSettings",
    "prune_stale_dirs",
    "seat_test_session",
    "session_scratch_dir",
]

#: The ignored worktree directory every test artifact lives under.
TEST_ROOT_NAME = ".pytest-tmp"

#: Every variable that names a SOURCE of settings rather than one setting.
#: None of them survives into a test session; see
#: :func:`_drop_undeclared_settings_sources`.
_UNDECLARED_SETTINGS_SOURCES: tuple[str, ...] = (ENV_FILE_ENV,)

#: Sessions older than this are pruned when a new session is seated.
_SESSION_RETENTION_SECONDS = 24 * 60 * 60
#: The newest sessions kept regardless of age, for triage of recent failures.
_SESSIONS_KEPT = 5


class TestSessionSettings(ProjectSettings):
    """The harness's own configuration, read from the process environment only.

    Never a setting from a file: these values describe one pytest process tree
    and are handed from a controller to its children, so a file on disk has no
    say.
    """

    __test__ = False

    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix=TEST_ENV_PREFIX,
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


def prune_stale_dirs(
    root: Path,
    *,
    kept_newest: int,
    keep: Path | None = None,
    older_than_s: float | None = None,
) -> list[Path]:
    """Remove all but the *kept_newest* most recent directories under *root*.

    *keep* is retained regardless and does not count toward the kept set - the
    caller's own directory. *older_than_s*, when given, spares any directory
    modified more recently than that, however many there are. Returns the
    directories actually removed.

    Another process starting at the same moment may be deleting these very
    directories, so an entry that vanishes mid-scan is skipped, never fatal:
    this runs at conftest import, where an error fails the whole session.
    """
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    stamped: list[tuple[float, str, Path]] = []
    for entry in entries:
        if entry == keep:
            continue
        try:
            if entry.is_dir():
                stamped.append((entry.stat().st_mtime, entry.name, entry))
        except OSError:
            continue
    # Name breaks ties, so directories sharing one filesystem timestamp tick
    # evict deterministically rather than in arbitrary order.
    stamped.sort(reverse=True)
    now = time.time()
    removed: list[Path] = []
    for modified, _name, entry in stamped[kept_newest:]:
        if older_than_s is not None and now - modified <= older_than_s:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed.append(entry)
    return removed


def _seat_env(field: str, value: Path, previously_seated: Path | None) -> None:
    """Point one settings variable at the seat unless the caller chose it."""
    from ..control.infra_config import InfraConfig

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


def _drop_undeclared_settings_sources() -> None:
    """Remove the names that hand this session settings it never declared.

    A single exported variable is a visible choice: whoever set
    ``VAULTSPEC_A2A_PORT`` before running the suite meant that port. A
    variable naming a settings FILE is not - it is a bundle of values nobody
    listed, and the documentation now tells developers to export it, so the
    ordinary case is a developer whose checkout ``.env`` would quietly decide
    this session's ports, database and timeouts. A file named but absent is
    worse still: the settings refuse it, and the refusal lands in collection.

    So the seat takes the file away. What the session does declare - the
    environment, the exporters, its own seat - it declares by name, and the
    per-test cases that exercise an operator file set the variable themselves,
    inside the block that restores it.
    """
    for name in _UNDECLARED_SETTINGS_SOURCES:
        os.environ.pop(name, None)


def seat_test_session(rootdir: Path) -> SessionSeat:
    """Seat this controller's session under ``rootdir``; idempotent per process."""
    _drop_undeclared_settings_sources()
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
    prune_stale_dirs(
        sessions,
        kept_newest=_SESSIONS_KEPT,
        keep=root,
        older_than_s=_SESSION_RETENTION_SECONDS,
    )
    _seat_env("a2a_home", seat.home, harness.seated_home)
    _seat_env("procs_home", seat.procs_home, harness.seated_procs_home)
    fields = TestSessionSettings
    os.environ[env_name(fields, "session_root")] = str(root)
    os.environ[env_name(fields, "session_pid")] = str(os.getpid())
    os.environ[env_name(fields, "seated_home")] = str(seat.home)
    os.environ[env_name(fields, "seated_procs_home")] = str(seat.procs_home)
    return seat


def session_scratch_dir(prefix: str) -> Path:
    """Create a unique scratch directory inside this session's seat.

    For state a test needs outside any one test's ``tmp_path`` - a template
    built once per process, a directory named at import - so it still lands in
    the ignored worktree rather than the system temporary directory.
    """
    root = TestSessionSettings().session_root
    if root is None:
        msg = "no test session is seated; the repository conftest seats one"
        raise RuntimeError(msg)
    scratch = root / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=scratch))
