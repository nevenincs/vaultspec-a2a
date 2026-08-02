"""Machine-global test-resource leases.

The correctness layer of resource-aware test execution: two tests that claim
the same exclusive resource can never overlap, regardless of how any scheduler
placed them, because acquisition is arbitrated by the filesystem with the same
discipline the dev-process registry uses for band ports - an ``O_EXCL`` marker
granted to exactly one claimant, reclaimable the moment its holder pid is dead,
with an mtime TTL as a pid-reuse backstop.

Leases improve on the registry's reservation markers in one respect the longer
hold demands: a holder refreshes its marker's mtime from a daemon thread while
it holds the lease, so liveness is judged on holder pid AND heartbeat together.
A dead holder frees the resource immediately (pid signal); a reused pid cannot
impersonate the holder for longer than the TTL because nothing refreshes the
marker (heartbeat signal).

Shared claims coexist with each other and exclude an exclusive claimant, via
per-holder shared markers: an exclusive acquisition requires no live shared
markers and takes the exclusive marker; a shared acquisition writes its own
marker and then re-checks that no exclusive marker appeared, retreating and
retrying if one did, so the two acquisition orders cannot deadlock or admit an
overlap.

The lease home sits beside the dev-process registry (a ``leases`` subdirectory
of the procs home), so ``VAULTSPEC_PROCS_HOME`` isolation and explicit
``home:`` injection flow through unchanged, and leases arbitrate across
concurrent test sessions on the whole machine, not only within one run.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..lifecycle import is_pid_alive, procs_home

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "LEASE_TTL_MS",
    "Lease",
    "LeaseAcquisitionTimeoutError",
    "hold_lease",
    "lease_home",
    "live_shared_holder_count",
]

# Pid-reuse backstop only: the holder's refresher touches the marker every
# REFRESH_INTERVAL_S, so a live holder's marker never approaches this age and a
# dead holder is reclaimed by the pid signal long before it. Generous, so a
# briefly-starved refresher thread on a loaded host cannot forfeit a live lease.
LEASE_TTL_MS = 300_000
_REFRESH_INTERVAL_S = 15.0
# A marker whose mtime is AHEAD of the observer's clock is anomalous only past
# this tolerance: a peer legitimately creates or refreshes a marker between the
# observer capturing "now" and statting the file, and a zero-tolerance check
# would read that fresh LIVE marker as reclaimable and steal the lease - the
# registry's reservation path carried exactly this race.
_FUTURE_SKEW_TOLERANCE_MS = 10_000

_EXCLUSIVE_SUFFIX = ".lease"
_SHARED_SUFFIX = ".shared"
_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Distinguishes multiple shared holds by one process; see _try_acquire_shared.
_SHARED_SEQ = itertools.count()


class LeaseAcquisitionTimeoutError(TimeoutError):
    """The lease stayed contended past the caller's acquisition deadline."""


def lease_home(home: Path | None = None) -> Path:
    """The machine-global lease directory, beside the dev-process registry."""
    return procs_home(home) / "leases"


def _validate_key(key: str) -> None:
    if not _KEY_PATTERN.match(key):
        raise ValueError(
            f"lease key {key!r} must be lowercase kebab-case (pattern "
            f"{_KEY_PATTERN.pattern})"
        )


def _marker_is_live(path: Path, *, now_ms: int) -> bool:
    """A marker holds its resource while its holder pid is alive AND it is fresh.

    Mirrors the registry's reservation liveness but demands both signals: the
    engine precedent shows a service can keep serving after its heartbeat
    writer dies, so neither pid-liveness nor freshness alone is trusted. An
    unreadable pid degrades to freshness-only (the TTL still bounds it).
    """
    try:
        age = now_ms - int(path.stat().st_mtime * 1000)
    except OSError:
        return False
    if age < -_FUTURE_SKEW_TOLERANCE_MS or age > LEASE_TTL_MS:
        return False
    pid = _read_holder_pid(path)
    if pid is None:
        return True
    return is_pid_alive(pid)


def _read_holder_pid(path: Path) -> int | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = data.get("pid") if isinstance(data, dict) else None
    return pid if isinstance(pid, int) and not isinstance(pid, bool) else None


def _holder_description(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"unreadable marker {path.name}"
    if not isinstance(data, dict):
        return f"malformed marker {path.name}"
    return (
        f"pid {data.get('pid')} owner {data.get('owner')!r} "
        f"since {data.get('acquired_at_ms')}"
    )


def _write_marker_excl(path: Path, *, owner: str) -> str | None:
    """Create *path* exclusively with holder metadata; ``None`` when it exists.

    Returns the exact payload written - the holder's release token - so a
    holder can later prove the marker is still its own before unlinking it.
    """
    payload = json.dumps(
        {"pid": os.getpid(), "owner": owner, "acquired_at_ms": int(time.time() * 1000)}
    )
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    return payload


def _reap_dead_marker(path: Path, *, now_ms: int) -> None:
    """Drop a marker whose holder is provably gone; O_EXCL arbitrates racers."""
    if path.exists() and not _marker_is_live(path, now_ms=now_ms):
        with contextlib.suppress(OSError):
            path.unlink()


def _live_shared_markers(root: Path, key: str) -> list[Path]:
    # Judged per-marker with a fresh clock; a snapshot taken before the walk
    # reads a marker created mid-walk as future-dated.
    markers: list[Path] = []
    for marker in root.glob(f"{key}.*{_SHARED_SUFFIX}"):
        fresh = int(time.time() * 1000)
        _reap_dead_marker(marker, now_ms=fresh)
        if marker.exists() and _marker_is_live(marker, now_ms=fresh):
            markers.append(marker)
    return markers


def live_shared_holder_count(
    key: str, *, home: Path | None = None, excluding_pid: int | None = None
) -> int:
    """Count the LIVE shared holders of *key*, optionally excluding one pid.

    Judged with the same dual-signal marker liveness the acquisition paths
    use, so a crashed holder stops counting the moment its pid dies. The
    exclusion exists for a holder asking "how many peers beside me".
    """
    _validate_key(key)
    root = lease_home(home)
    if not root.is_dir():
        return 0
    count = 0
    for marker in _live_shared_markers(root, key):
        if excluding_pid is not None and _read_holder_pid(marker) == excluding_pid:
            continue
        count += 1
    return count


@dataclass(slots=True)
class Lease:
    """A held lease: the marker path, its refresher thread, and its stop event."""

    key: str
    shared: bool
    path: Path
    _token: str
    _stop: threading.Event
    _refresher: threading.Thread

    def release(self) -> None:
        """Stop the heartbeat and drop the marker (idempotent).

        Unlinks only while the marker still carries this holder's own token: a
        holder whose marker was reclaimed (stalled refresher past the TTL) must
        not delete its successor's claim.
        """
        self._stop.set()
        self._refresher.join(timeout=5.0)
        try:
            current = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        if current == self._token:
            with contextlib.suppress(OSError):
                self.path.unlink()


def _start_refresher(
    path: Path, *, interval_s: float
) -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def _refresh() -> None:
        while not stop.wait(interval_s):
            with contextlib.suppress(OSError):
                os.utime(path)

    thread = threading.Thread(
        target=_refresh, name=f"lease-refresh-{path.name}", daemon=True
    )
    thread.start()
    return stop, thread


def _try_acquire_exclusive(
    root: Path, key: str, *, owner: str
) -> tuple[Path, str] | None:
    now = int(time.time() * 1000)
    exclusive = root / f"{key}{_EXCLUSIVE_SUFFIX}"
    _reap_dead_marker(exclusive, now_ms=now)
    if exclusive.exists():
        return None
    if _live_shared_markers(root, key):
        return None
    token = _write_marker_excl(exclusive, owner=owner)
    if token is None:
        return None
    # Shared holders admitted between the check and our create lose the race
    # only if they observed no exclusive marker; our marker existed before
    # their re-check completes or theirs existed before ours - the re-check
    # below on the shared path guarantees one side retreats.
    if _live_shared_markers(root, key):
        with contextlib.suppress(OSError):
            exclusive.unlink()
        return None
    return exclusive, token


def _try_acquire_shared(root: Path, key: str, *, owner: str) -> tuple[Path, str] | None:
    now = int(time.time() * 1000)
    exclusive = root / f"{key}{_EXCLUSIVE_SUFFIX}"
    _reap_dead_marker(exclusive, now_ms=now)
    if exclusive.exists():
        return None
    # Unique per acquisition (pid + sequence), so one process can hold several
    # shared leases on a key and an O_EXCL collision is structurally
    # impossible - the previous same-name scheme unlinked an existing marker
    # on collision under an unverifiable "leftover" assumption, which could
    # destroy a live sibling hold. A reused-pid predecessor's leftover is
    # retired by the ordinary dual-signal liveness (its mtime freezes).
    mine = root / f"{key}.{os.getpid()}-{next(_SHARED_SEQ)}{_SHARED_SUFFIX}"
    token = _write_marker_excl(mine, owner=owner)
    if token is None:
        return None
    # Re-check: if an exclusive claimant won concurrently, retreat so the
    # stronger claim proceeds alone.
    recheck_ms = int(time.time() * 1000)
    if exclusive.exists() and _marker_is_live(exclusive, now_ms=recheck_ms):
        with contextlib.suppress(OSError):
            mine.unlink()
        return None
    return mine, token


def _contention_detail(root: Path, key: str) -> str:
    now = int(time.time() * 1000)
    exclusive = root / f"{key}{_EXCLUSIVE_SUFFIX}"
    parts: list[str] = []
    if exclusive.exists() and _marker_is_live(exclusive, now_ms=now):
        parts.append(f"exclusive holder: {_holder_description(exclusive)}")
    for marker in _live_shared_markers(root, key):
        parts.append(f"shared holder: {_holder_description(marker)}")
    return "; ".join(parts) if parts else "no live holder (transient contention)"


def acquire(
    key: str,
    *,
    shared: bool = False,
    owner: str = "",
    home: Path | None = None,
    acquire_timeout_s: float | None = None,
    poll_interval_s: float = 0.25,
    refresh_interval_s: float = _REFRESH_INTERVAL_S,
) -> Lease:
    """Block until the lease for *key* is held, then heartbeat it until release.

    ``acquire_timeout_s=None`` waits indefinitely - the per-item timeout
    backstop is the guard against a runaway holder, and waiting on a LIVE
    holder is the intended serialization, not a fault. On timeout, the raised
    :class:`LeaseAcquisitionTimeoutError` names the live holder so the contention is
    diagnosable rather than a bare clock expiry.
    """
    _validate_key(key)
    root = lease_home(home)
    root.mkdir(parents=True, exist_ok=True)
    label = owner or f"pid-{os.getpid()}"
    deadline = (
        time.monotonic() + acquire_timeout_s if acquire_timeout_s is not None else None
    )
    while True:
        acquired = (
            _try_acquire_shared(root, key, owner=label)
            if shared
            else _try_acquire_exclusive(root, key, owner=label)
        )
        if acquired is not None:
            path, token = acquired
            stop, refresher = _start_refresher(path, interval_s=refresh_interval_s)
            return Lease(
                key=key,
                shared=shared,
                path=path,
                _token=token,
                _stop=stop,
                _refresher=refresher,
            )
        if deadline is not None and time.monotonic() >= deadline:
            raise LeaseAcquisitionTimeoutError(
                f"lease {key!r} stayed contended for {acquire_timeout_s}s: "
                f"{_contention_detail(root, key)}"
            )
        # Jittered so two claimants that mutually retreated (the shared vs
        # exclusive cross-check) cannot retry in lockstep forever.
        time.sleep(poll_interval_s * (0.5 + random.random()))


@contextlib.contextmanager
def hold_lease(
    key: str,
    *,
    shared: bool = False,
    owner: str = "",
    home: Path | None = None,
    acquire_timeout_s: float | None = None,
    poll_interval_s: float = 0.25,
    refresh_interval_s: float = _REFRESH_INTERVAL_S,
) -> Iterator[Lease]:
    """Context-managed :func:`acquire`; releases on exit even under failure."""
    lease = acquire(
        key,
        shared=shared,
        owner=owner,
        home=home,
        acquire_timeout_s=acquire_timeout_s,
        poll_interval_s=poll_interval_s,
        refresh_interval_s=refresh_interval_s,
    )
    try:
        yield lease
    finally:
        lease.release()
