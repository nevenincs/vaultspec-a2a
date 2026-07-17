"""File-per-process dev-process registry.

One JSON state file per managed dev/test process at an explicit machine-global
path - ``~/.vaultspec/procs/<role>-<name>.json`` - so a single place always knows
what runs where, for whom, from which build. This module owns the record schema,
atomic owner-checked writes, pid-liveness and staleness classification, and
band-constrained port allocation; the lifecycle verbs (``procs list/attach/kill/
rebuild/rerun/resume/reap``) compose over it.

The discipline mirrors the service.json discovery machinery one level up: writes
are temp-and-rename atomic, mutation of a record is refused when a *live* process
of a *different* owner holds it, and a dead-pid record is freely reclaimable. The
registry references the services' own service.json records (via ``port``/``pid``);
it never fights them.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .discovery import is_pid_alive

if TYPE_CHECKING:
    from pathlib import Path

    from .procs_config import ProcsConfig, RoleConfig

__all__ = [
    "PortReservation",
    "ProcRecord",
    "RegistryOwnershipError",
    "StalenessState",
    "allocate_port",
    "classify_record",
    "commit_reservation",
    "list_records",
    "now_ms",
    "procs_home",
    "read_record",
    "record_path",
    "refresh_last_seen",
    "release_reservation",
    "remove_record",
    "remove_record_if_owned",
    "reserve_port",
    "write_record",
]

# Liveness-aware reclaim governs a reservation marker: it is reclaimable the moment
# its stored reserver pid is dead (fast crash recovery), so the pid check does the
# real work. This mtime-TTL is only a pid-reuse backstop - generous, so a live
# reserver holding a marker is honoured well beyond any bounded reserve->commit and
# the reclaim never couples to a caller's ready_timeout.
RESERVATION_TTL_MS = 300_000
_RESERVATION_SUFFIX = ".reserved"

_PROCS_HOME_ENV = "VAULTSPEC_PROCS_HOME"


class RegistryOwnershipError(RuntimeError):
    """A mutation was refused: a live process of another owner holds the record."""


class StalenessState(StrEnum):
    """A record's liveness verdict."""

    LIVE = "live"
    STALE = "stale"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class ProcRecord:
    """A single managed process. Never carries a credential, token, or env value."""

    name: str
    role: str
    pid: int
    port: int
    repo: str = ""
    # The build tree, when it differs from the serve tree (engine-dev builds the
    # cargo workspace in the dashboard repo but serves the wrapper from the a2a
    # repo). Captured into this machine-global record at boot so procs.toml carries
    # no machine-specific path; empty means build and serve share ``repo``.
    build_repo: str = ""
    workspace: str = ""
    build_sha: str | None = None
    command: list[str] = field(default_factory=list)
    started_at_ms: int = 0
    last_seen_ms: int = 0
    log_path: str | None = None
    owner: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_ms() -> int:
    """Milliseconds since the epoch (registry timestamp unit)."""
    return int(time.time() * 1000)


def procs_home(home: Path | None = None) -> Path:
    """Resolve the registry home: explicit arg, env override, or ``~/.vaultspec/procs``.

    The ``VAULTSPEC_PROCS_HOME`` override exists for test isolation and for adopting
    an interim state-file directory; the default is the machine-global home shared
    with the engine's service.json.
    """
    from pathlib import Path as _Path

    if home is not None:
        return home
    override = os.environ.get(_PROCS_HOME_ENV)
    if override:
        return _Path(override)
    return _Path.home() / ".vaultspec" / "procs"


def record_path(role: str, name: str, *, home: Path | None = None) -> Path:
    """Return the state-file path for ``<role>-<name>.json`` under the registry home."""
    return procs_home(home) / f"{role}-{name}.json"


def _coerce_command(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            return []
        items.append(entry)
    return items


def _record_from_dict(data: dict[str, Any]) -> ProcRecord | None:
    """Build a :class:`ProcRecord` from a parsed record, or ``None`` if invalid."""
    name = data.get("name")
    role = data.get("role")
    pid = data.get("pid")
    port = data.get("port")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(role, str) or not role:
        return None
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(port, int) or isinstance(port, bool):
        return None

    def _opt_str(key: str) -> str:
        v = data.get(key)
        return v if isinstance(v, str) else ""

    def _opt_str_or_none(key: str) -> str | None:
        v = data.get(key)
        return v if isinstance(v, str) and v else None

    def _opt_int(key: str) -> int:
        v = data.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    return ProcRecord(
        name=name,
        role=role,
        pid=pid,
        port=port,
        repo=_opt_str("repo"),
        build_repo=_opt_str("build_repo"),
        workspace=_opt_str("workspace"),
        build_sha=_opt_str_or_none("build_sha"),
        command=_coerce_command(data.get("command")),
        started_at_ms=_opt_int("started_at_ms"),
        last_seen_ms=_opt_int("last_seen_ms"),
        log_path=_opt_str_or_none("log_path"),
        owner=_opt_str("owner"),
    )


def read_record(path: Path) -> ProcRecord | None:
    """Read one record file, or ``None`` when it is absent, unreadable, or malformed."""
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
    return _record_from_dict(data)


def list_records(home: Path | None = None) -> list[ProcRecord]:
    """Enumerate all valid records under the registry home (malformed files skipped)."""
    root = procs_home(home)
    if not root.is_dir():
        return []
    records: list[ProcRecord] = []
    for entry in sorted(root.glob("*.json")):
        record = read_record(entry)
        if record is not None:
            records.append(record)
    return records


def write_record(record: ProcRecord, *, home: Path | None = None) -> Path:
    """Atomically write a record, refusing to clobber a live record of another owner.

    Owner-checked mutation: if a record already exists for ``(role, name)`` whose
    pid is alive and whose owner differs, the write is refused with
    :class:`RegistryOwnershipError`. A dead-pid record, a same-owner record, or an
    absent one is freely (re)claimable. The write itself is temp-and-rename atomic,
    so a concurrent reader never sees a partial record.
    """
    path = record_path(record.role, record.name, home=home)
    existing = read_record(path)
    if (
        existing is not None
        and existing.owner != record.owner
        and is_pid_alive(existing.pid)
    ):
        raise RegistryOwnershipError(
            f"record {record.role}-{record.name} is held by a live process "
            f"(pid {existing.pid}, owner {existing.owner!r}); refusing to overwrite"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def refresh_last_seen(
    record: ProcRecord, *, at_ms: int | None = None, home: Path | None = None
) -> ProcRecord:
    """Rewrite the record's ``last_seen_ms`` heartbeat and return the updated record."""
    from dataclasses import replace

    updated = replace(record, last_seen_ms=at_ms if at_ms is not None else now_ms())
    write_record(updated, home=home)
    return updated


def remove_record(role: str, name: str, *, home: Path | None = None) -> bool:
    """Delete a record file unconditionally; ``True`` when a file was removed."""
    path = record_path(role, name, home=home)
    if not path.exists():
        return False
    path.unlink(missing_ok=True)
    return True


def remove_record_if_owned(
    role: str, name: str, owner: str, *, home: Path | None = None
) -> bool:
    """Delete a record only when *owner* holds it or its process is already dead.

    Mirrors the discovery discipline: a live record owned by someone else is left
    in place. Returns ``True`` when the file was removed.
    """
    path = record_path(role, name, home=home)
    existing = read_record(path)
    if existing is None:
        return False
    if existing.owner != owner and is_pid_alive(existing.pid):
        return False
    path.unlink(missing_ok=True)
    return True


def classify_record(
    record: ProcRecord, role_config: RoleConfig | None, *, now: int | None = None
) -> StalenessState:
    """Classify a record ``LIVE | STALE | DEAD``.

    ``DEAD`` when the pid is not a live process. For a heartbeating role, ``STALE``
    when the pid is alive but ``last_seen_ms`` is older than the role's staleness
    window; a non-heartbeating role (or an unknown role) rests on pid-liveness
    alone and reads ``LIVE`` while its pid is alive.
    """
    if not is_pid_alive(record.pid):
        return StalenessState.DEAD
    if role_config is not None and role_config.heartbeat:
        current = now if now is not None else now_ms()
        if current - record.last_seen_ms > role_config.staleness_ms:
            return StalenessState.STALE
    return StalenessState.LIVE


def _port_is_free(port: int) -> bool:
    """Return ``True`` when nothing holds *port* and it can be bound right now.

    Two probes, because neither alone is reliable on Windows:

    - A connect probe first: if a listener answers a loopback connect the port is
      taken. This is the ONLY reliable way to detect a foreign holder on Windows,
      where a plain ``bind('127.0.0.1', port)`` SUCCEEDS even when another process
      already serves ``0.0.0.0:port`` (no ``SO_EXCLUSIVEADDRUSE``) - observed live
      handing out a resident gateway's port, the exact collision the registry
      exists to prevent.
    - Then a bind probe (no ``SO_REUSEADDR``): catches a port bound but not yet
      listening, which the connect probe would miss.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def allocate_port(
    role: str,
    role_config: RoleConfig,
    *,
    home: Path | None = None,
    config: ProcsConfig | None = None,
) -> int:
    """Allocate the first free port in *role*'s band, recording no claim by itself.

    A port is taken when a live registry record already holds it (any role), when a
    live reservation marker holds it, or when it cannot be bound on the loopback
    interface (a non-registry process holds it). The caller writes the claiming
    record once the process is spawned. Raises :class:`RuntimeError` when the band
    is exhausted. For a race-free claim, prefer :func:`reserve_port`.
    """
    now = now_ms()
    claimed = {rec.port for rec in list_records(home) if is_pid_alive(rec.pid)}
    reserved = _live_reservation_ports(home, now=now)
    resident_ports = set(config.resident.values()) if config is not None else set()
    for candidate in role_config.band:
        if candidate in claimed or candidate in reserved or candidate in resident_ports:
            continue
        if _port_is_free(candidate):
            return candidate
    raise RuntimeError(
        f"role {role!r} band {role_config.band} is exhausted: no free port"
    )


@dataclass(frozen=True, slots=True)
class PortReservation:
    """An exclusive claim on a band port, held until committed or released."""

    port: int
    path: Path


def _reservation_path(role: str, port: int, *, home: Path | None) -> Path:
    return procs_home(home) / f"{role}-{port}{_RESERVATION_SUFFIX}"


def _read_reservation_pid(path: Path) -> int | None:
    """Read the reserver pid stamped into a marker, or ``None`` when unreadable."""
    try:
        raw = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return int(raw) if raw.isdigit() else None


def _reservation_is_live(path: Path, *, now: int) -> bool:
    """Return ``True`` while a marker still holds its port (blocks allocation).

    Liveness-aware: a marker is reclaimable the instant its stored reserver pid is
    dead, so a crashed reserver frees its port immediately instead of wedging it for
    the whole TTL. The mtime-TTL is only a pid-reuse backstop - a live-pid marker
    past it, or a marker with no readable pid past it, is reclaimed - never the
    primary signal, so the reclaim never couples to a caller's reserve->commit span.
    """
    try:
        age = now - int(path.stat().st_mtime * 1000)
    except OSError:
        return False
    if age < 0 or age > RESERVATION_TTL_MS:
        return False
    pid = _read_reservation_pid(path)
    if pid is None:
        return True
    return is_pid_alive(pid)


def _live_reservation_ports(home: Path | None, *, now: int) -> set[int]:
    """Ports currently held by a live (non-stale) reservation marker."""
    root = procs_home(home)
    if not root.is_dir():
        return set()
    ports: set[int] = set()
    for marker in root.glob(f"*{_RESERVATION_SUFFIX}"):
        if not _reservation_is_live(marker, now=now):
            continue
        tail = marker.stem.rsplit("-", 1)
        if len(tail) == 2 and tail[1].isdigit():
            ports.add(int(tail[1]))
    return ports


def reserve_port(
    role: str,
    role_config: RoleConfig,
    *,
    home: Path | None = None,
    config: ProcsConfig | None = None,
) -> PortReservation:
    """Atomically reserve the first free band port, closing the allocate-and-claim race.

    Unlike :func:`allocate_port`, this creates an exclusive reservation marker
    (``O_EXCL`` create) before returning, so two concurrent same-band callers can
    never receive the same port - the filesystem grants the marker to exactly one.
    The caller then spawns/binds and calls :func:`commit_reservation` (which writes
    the real record and clears the marker) or :func:`release_reservation` on
    failure. A marker older than :data:`RESERVATION_TTL_MS` with no live record is
    stale and reclaimable. Raises :class:`RuntimeError` when the band is exhausted.
    """
    root = procs_home(home)
    root.mkdir(parents=True, exist_ok=True)
    now = now_ms()
    claimed = {rec.port for rec in list_records(home) if is_pid_alive(rec.pid)}
    resident_ports = set(config.resident.values()) if config is not None else set()
    for candidate in role_config.band:
        if candidate in claimed or candidate in resident_ports:
            continue
        path = _reservation_path(role, candidate, home=home)
        if path.exists():
            if _reservation_is_live(path, now=now):
                continue
            # Stale marker: drop it, then the O_EXCL create below arbitrates the race.
            with contextlib.suppress(OSError):
                path.unlink()
        if not _port_is_free(candidate):
            continue
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            # Another allocator won this port between our checks and the create.
            continue
        try:
            os.write(fd, str(os.getpid()).encode("ascii"))
        finally:
            os.close(fd)
        return PortReservation(port=candidate, path=path)
    raise RuntimeError(
        f"role {role!r} band {role_config.band} is exhausted: no free port"
    )


def release_reservation(reservation: PortReservation) -> None:
    """Drop an uncommitted reservation, freeing the port for the next allocator."""
    with contextlib.suppress(OSError):
        reservation.path.unlink()


def commit_reservation(
    reservation: PortReservation, record: ProcRecord, *, home: Path | None = None
) -> Path:
    """Write the claiming record and clear the reservation marker (atomic handoff)."""
    path = write_record(record, home=home)
    release_reservation(reservation)
    return path
