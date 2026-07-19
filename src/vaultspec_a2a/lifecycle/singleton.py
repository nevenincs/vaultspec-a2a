"""Operating-system-held runtime singleton for one desktop application home.

The desktop gateway must be the sole live owner of one application home for its
whole lifetime. This module provides that guarantee with an exclusively held lock
file whose byte-zero region is locked through the platform's native advisory lock
(``msvcrt.locking`` on Windows, ``fcntl.flock`` on POSIX). The lock dies with the
holding process, so a crash releases it without leaving a wedged home; a clean
shutdown releases it explicitly. No third-party dependency is used.

Two artifacts live under ``<app_home>/runtime``:

- ``gateway.singleton.lock`` — the anchor whose locked byte the operating system
  grants to exactly one live process. Its content is irrelevant; the lock, not the
  bytes, is authoritative.
- ``gateway.singleton.json`` — an atomically published owner record carrying the
  holder's process identity (pid plus a start fingerprint that guards against pid
  reuse) and owner identity. It never carries a credential, token, or secret.

Acquisition classifies the prior state and fails closed on a live foreign or
unverifiable resident. Only an owner-matching stale record (its recorded process
proven dead) is quarantined and atomically taken over. Read-only classification
via :func:`classify_app_home` lets a contender or the discovery layer reason about
ownership without contending for the lock.

The process-start fingerprint helpers are the single authority for "prove this
recorded process is really dead": :mod:`vaultspec_a2a.lifecycle.discovery` reuses
them for the versioned discovery record's process identity.
"""

from __future__ import annotations

import contextlib
import getpass
import json
import os
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .discovery import is_pid_alive

__all__ = [
    "SINGLETON_RECORD_VERSION",
    "RuntimeSingleton",
    "SingletonConflictError",
    "SingletonError",
    "SingletonHeldError",
    "SingletonRecord",
    "SingletonState",
    "acquire_singleton",
    "active_singleton",
    "classify_app_home",
    "clear_active_singleton",
    "current_process_fingerprint",
    "default_owner",
    "process_start_fingerprint",
    "recorded_process_is_live",
    "set_active_singleton",
    "singleton_lock_path",
    "singleton_record_path",
]

# Bumped only on an incompatible record-shape change; readers reject an unknown
# version fail-closed rather than guessing at a foreign layout.
SINGLETON_RECORD_VERSION = 1

_LOCK_NAME = "gateway.singleton.lock"
_RECORD_NAME = "gateway.singleton.json"
_RUNTIME_DIR = "runtime"

# The runtime singleton the current process holds for its desktop application
# home, if any. The desktop serve entrypoint acquires the singleton before the
# gateway binds and registers it here; the gateway lifetime reads it to key its
# discovery publication and to release ownership on shutdown. This is process
# state, not machine state — it is never persisted.
_active: RuntimeSingleton | None = None


def set_active_singleton(singleton: RuntimeSingleton) -> None:
    """Register the runtime singleton this process holds for its app home."""
    global _active
    _active = singleton


def active_singleton() -> RuntimeSingleton | None:
    """Return the runtime singleton this process holds, or ``None`` if none."""
    return _active


def clear_active_singleton() -> None:
    """Forget the process's active runtime singleton (after release)."""
    global _active
    _active = None


class SingletonState(StrEnum):
    """A runtime-singleton classification for one application home.

    ``FREE`` licenses a clean acquire; ``HELD`` and ``FOREIGN`` are live residents
    (the owner matches, or does not); ``STALE`` is a record whose recorded process
    is proven dead; ``MALFORMED`` is an unreadable or unversioned record.
    """

    FREE = "free"
    HELD = "held"
    STALE = "stale"
    FOREIGN = "foreign"
    MALFORMED = "malformed"


class SingletonError(RuntimeError):
    """Base class for runtime-singleton acquisition failures."""


class SingletonConflictError(SingletonError):
    """Acquisition refused: a live foreign or unverifiable resident owns the home.

    Carries the observed :class:`SingletonState` and the offending record (when one
    was readable) so a caller can render an actionable immutable-conflict message.
    """

    def __init__(
        self, message: str, *, state: SingletonState, record: SingletonRecord | None
    ) -> None:
        super().__init__(message)
        self.state = state
        self.record = record


class SingletonHeldError(SingletonConflictError):
    """Acquisition refused: this same owner already holds a live singleton here."""


def default_owner() -> str:
    """Return a stable owner identity for this operating-system principal.

    Two gateways launched by the same principal against one application home must
    read as the same owner so a crash-restart is an owner-matching takeover, while a
    different principal reads as foreign. Falls back through the numeric uid and a
    constant so this never raises on a stripped environment.
    """
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = ""
    if user:
        return user
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        return f"uid:{getuid()}"
    return "desktop"


def process_start_fingerprint(pid: int) -> str | None:
    """Return a stable start-time fingerprint for *pid*, or ``None`` if unavailable.

    The fingerprint guards pid reuse: a recorded pid that is live again but was
    started later carries a different fingerprint, so a dead recorded process is not
    mistaken for a live one. Windows reads the process creation ``FILETIME``; Linux
    reads ``starttime`` from ``/proc/<pid>/stat``. Platforms without a cheap source
    (notably macOS) return ``None``, and callers degrade to pid-liveness alone.
    """
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _windows_start_fingerprint(pid)
    if sys.platform.startswith("linux"):
        return _linux_start_fingerprint(pid)
    return None


def _windows_start_fingerprint(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    process_query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_query, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return None
        return f"{creation.dwHighDateTime}:{creation.dwLowDateTime}"
    finally:
        kernel32.CloseHandle(handle)


def _linux_start_fingerprint(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # comm (field 2) is wrapped in parentheses and may itself contain spaces and
    # parentheses, so split after the final ')': the remaining fields start at the
    # process state (field 3). starttime is field 22 -> index 19 of that tail.
    close = stat.rfind(")")
    if close == -1:
        return None
    tail = stat[close + 2 :].split()
    if len(tail) < 20:
        return None
    return tail[19]


def current_process_fingerprint() -> str | None:
    """Return this process's own start fingerprint (``None`` when unavailable)."""
    return process_start_fingerprint(os.getpid())


@dataclass(frozen=True, slots=True)
class SingletonRecord:
    """The published owner of a runtime singleton. Never carries a secret.

    ``start_fingerprint`` is ``None`` on platforms without a cheap start-time
    source; a reader then rests on pid-liveness alone.
    """

    version: int
    pid: int
    owner: str
    start_fingerprint: str | None
    acquired_at_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "pid": self.pid,
            "owner": self.owner,
            "start_fingerprint": self.start_fingerprint,
            "acquired_at_ms": self.acquired_at_ms,
        }


def singleton_lock_path(app_home: Path) -> Path:
    """Return the OS lock-anchor path for *app_home*."""
    return app_home / _RUNTIME_DIR / _LOCK_NAME


def singleton_record_path(app_home: Path) -> Path:
    """Return the owner-record path for *app_home*."""
    return app_home / _RUNTIME_DIR / _RECORD_NAME


def _read_record(path: Path) -> SingletonRecord | None:
    """Read and validate an owner record, or ``None`` when absent or malformed."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    pid = data.get("pid")
    owner = data.get("owner")
    acquired = data.get("acquired_at_ms")
    if version != SINGLETON_RECORD_VERSION:
        return None
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if not isinstance(owner, str):
        return None
    fingerprint = data.get("start_fingerprint")
    if fingerprint is not None and not isinstance(fingerprint, str):
        return None
    if not isinstance(acquired, int) or isinstance(acquired, bool):
        acquired = 0
    return SingletonRecord(
        version=version,
        pid=pid,
        owner=owner,
        start_fingerprint=fingerprint,
        acquired_at_ms=acquired,
    )


def recorded_process_is_live(record: SingletonRecord) -> bool:
    """Return ``True`` when the record's recorded process is provably still alive.

    Pid-liveness is the primary signal; the start fingerprint is a pid-reuse guard.
    When both the record and the live pid expose a fingerprint they must match, so a
    reused pid belonging to an unrelated process reads as dead. When either side
    cannot produce a fingerprint the check degrades to pid-liveness alone.
    """
    if not is_pid_alive(record.pid):
        return False
    if record.start_fingerprint is None:
        return True
    current = process_start_fingerprint(record.pid)
    if current is None:
        return True
    return current == record.start_fingerprint


def _write_record(path: Path, record: SingletonRecord) -> None:
    """Atomically publish an owner record (temp write + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(record.to_dict(), indent=2).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def classify_app_home(
    app_home: Path, *, owner: str | None = None
) -> tuple[SingletonState, SingletonRecord | None]:
    """Classify the singleton state of *app_home* without contending for the lock.

    Read-only: a contender or the discovery layer uses this to reason about who
    owns a home. ``FREE`` when no record exists; ``MALFORMED`` when the record is
    unreadable or unversioned; otherwise ``HELD``/``FOREIGN`` when the recorded
    process is live (owner matches, or does not) and ``STALE`` when it is proven
    dead. The lock file itself is never opened, so this never blocks or races an
    acquirer.
    """
    principal = owner if owner is not None else default_owner()
    record_path = singleton_record_path(app_home)
    if not record_path.exists():
        return SingletonState.FREE, None
    record = _read_record(record_path)
    if record is None:
        return SingletonState.MALFORMED, None
    if not recorded_process_is_live(record):
        return SingletonState.STALE, record
    if record.owner == principal:
        return SingletonState.HELD, record
    return SingletonState.FOREIGN, record


def _try_lock(fd: int) -> bool:
    """Take a non-blocking exclusive lock on byte zero; ``True`` when granted."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    """Release the byte-zero lock. POSIX ``flock`` also releases on close."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)


@dataclass(slots=True)
class RuntimeSingleton:
    """A held runtime singleton. Release with :meth:`release` or as a context manager.

    The open file descriptor keeps the operating-system lock live for the process
    lifetime; dropping the process (crash or clean exit) releases it. ``release``
    unlocks, closes the descriptor, and removes this owner's record so the next
    start reads ``FREE`` rather than a stale record.
    """

    app_home: Path
    record: SingletonRecord
    _fd: int
    _released: bool = False

    def __enter__(self) -> RuntimeSingleton:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    @property
    def owner(self) -> str:
        """Return this singleton's owner identity."""
        return self.record.owner

    def release(self) -> None:
        """Release the lock and remove this owner's record. Idempotent."""
        if self._released:
            return
        self._released = True
        _unlock(self._fd)
        with contextlib.suppress(OSError):
            os.close(self._fd)
        record_path = singleton_record_path(self.app_home)
        current = _read_record(record_path)
        if current is not None and current.pid == self.record.pid:
            record_path.unlink(missing_ok=True)


# Bounded window to wait out an orphaned lock. A just-terminated Windows holder's
# byte-range lock lingers for a few tens of milliseconds after the process exits
# before the kernel releases it; a genuinely live holder is detected from its record
# and short-circuits immediately, so this delay is only ever paid reclaiming a dead
# holder's home, never contending a live one.
_ORPHAN_LOCK_TIMEOUT_S = 3.0
_ORPHAN_LOCK_POLL_S = 0.05


def _acquire_lock_or_conflict(fd: int, record_path: Path) -> bool:
    """Take the lock, waiting out an orphaned lock but not a live holder.

    Returns ``True`` when the lock is held by this process. Returns ``False`` only
    when a live holder is proven present (its recorded process is alive) or the lock
    stays contended past the bounded orphaned-lock window, in which case the caller
    reads the record to name the conflict.
    """
    deadline = time.monotonic() + _ORPHAN_LOCK_TIMEOUT_S
    while True:
        if _try_lock(fd):
            return True
        prior = _read_record(record_path)
        if prior is not None and recorded_process_is_live(prior):
            # A real live holder (owner match or not); do not wait it out.
            return False
        if time.monotonic() >= deadline:
            # The lock never freed and no live owner is provable: fail closed.
            return False
        time.sleep(_ORPHAN_LOCK_POLL_S)


def acquire_singleton(app_home: Path, *, owner: str | None = None) -> RuntimeSingleton:
    """Acquire the runtime singleton for *app_home*, or fail closed on a conflict.

    The operating-system lock on the anchor file is authoritative: holding it proves
    sole live ownership, and being unable to take it proves a live resident. On a
    live resident the prior record is read to classify the conflict: a matching
    owner raises :class:`SingletonHeldError`, any other (or an unreadable) live
    resident raises :class:`SingletonConflictError`. When the lock is granted the
    prior record is examined before takeover: a matching-owner ``STALE`` record is
    quarantined and taken over atomically, while a live or foreign-stale prior
    record is refused (the lock is released) so a foreign home is never silently
    stolen from its owner or its receipt-holder.

    Raises:
        SingletonHeldError: This owner already holds a live singleton here.
        SingletonConflictError: A live or foreign-stale resident owns the home.
        SingletonError: The lock file could not be opened.
    """
    principal = owner if owner is not None else default_owner()
    lock_path = singleton_lock_path(app_home)
    record_path = singleton_record_path(app_home)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise SingletonError(
            f"could not open the desktop runtime singleton lock at {lock_path}: {exc}"
        ) from exc

    if not _acquire_lock_or_conflict(fd, record_path):
        os.close(fd)
        prior = _read_record(record_path)
        if (
            prior is not None
            and prior.owner == principal
            and recorded_process_is_live(prior)
        ):
            raise SingletonHeldError(
                f"desktop application home {app_home} is already owned by a live "
                f"gateway of this owner ({principal!r}, pid {prior.pid}); refusing to "
                "start a second gateway on one application home.",
                state=SingletonState.HELD,
                record=prior,
            )
        owner_desc = (
            f"owner {prior.owner!r}, pid {prior.pid}"
            if prior
            else "an unverifiable owner"
        )
        raise SingletonConflictError(
            f"desktop application home {app_home} is held by a live foreign gateway "
            f"({owner_desc}); this is an immutable conflict — attach to the resident "
            "service instead of starting a competing gateway.",
            state=SingletonState.FOREIGN,
            record=prior,
        )

    # The lock is ours. Classify the prior record before overwriting it.
    prior = _read_record(record_path)
    prior_is_live = prior is not None and recorded_process_is_live(prior)
    if prior is not None and prior_is_live and prior.owner != principal:
        # A foreign process is recorded live even though the lock was free; do not
        # steal the home from a possibly-live foreign owner. Fail closed.
        _unlock(fd)
        os.close(fd)
        raise SingletonConflictError(
            f"desktop application home {app_home} records a live foreign gateway "
            f"(owner {prior.owner!r}, pid {prior.pid}); refusing takeover.",
            state=SingletonState.FOREIGN,
            record=prior,
        )
    if prior is not None and not prior_is_live and prior.owner != principal:
        # Foreign-stale: only the matching receipt owner may quarantine stale state
        # under the installation lock (per the desktop discovery decision). Refuse.
        _unlock(fd)
        os.close(fd)
        raise SingletonConflictError(
            f"desktop application home {app_home} holds a stale record of a foreign "
            f"owner ({prior.owner!r}, pid {prior.pid}); its owner must quarantine it "
            "under the installation lock before a different owner may claim the home.",
            state=SingletonState.STALE,
            record=prior,
        )

    # FREE, or an owner-matching STALE record: quarantine (overwrite) and take over.
    record = SingletonRecord(
        version=SINGLETON_RECORD_VERSION,
        pid=os.getpid(),
        owner=principal,
        start_fingerprint=current_process_fingerprint(),
        acquired_at_ms=int(time.time() * 1000),
    )
    try:
        _write_record(record_path, record)
    except OSError as exc:
        _unlock(fd)
        os.close(fd)
        raise SingletonError(
            f"acquired the desktop runtime singleton lock but could not publish its "
            f"owner record at {record_path}: {exc}"
        ) from exc
    return RuntimeSingleton(app_home=app_home, record=record, _fd=fd)
