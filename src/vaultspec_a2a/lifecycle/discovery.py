"""Machine-global service discovery and heartbeat for the resident gateway (R8).

The resident A2A gateway publishes ``~/.vaultspec-a2a/service.json`` so the engine
can attach to it under the attach-never-own discipline. The record adopts the R8
``ServiceInfo`` contract: ``port`` required; optional ``pid``, ``service_token``,
and ``last_heartbeat`` (ms-epoch). The producer refreshes the heartbeat every
:data:`HEARTBEAT_REFRESH_SECONDS`; a consumer treats a heartbeat older than
:data:`~vaultspec_a2a.authoring.discovery.HEARTBEAT_STALE_MS` as a crash.

Discovery is classified as ``FRESH | STALE | MALFORMED | ABSENT``: only ``ABSENT``
licenses starting a new resident service; a live ``FRESH`` file means another
instance is resident (do not start), and ``STALE``/``MALFORMED`` (or a ``FRESH``
record whose pid is dead) reads as Crashed — reclaimable by the next resident but
never silently trusted. Hot-path classification is filesystem-only and cheap; the
pid-liveness and ``/health`` probes are reserved for lifecycle callers.

The reader half (parse + heartbeat freshness) is shared with
``authoring.discovery`` so the freshness contract lives in exactly one place.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import httpx

from ..authoring.discovery import (
    HEARTBEAT_STALE_MS as HEARTBEAT_STALE_MS,
)
from ..authoring.discovery import (
    heartbeat_is_fresh,
    read_service_json,
)

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "DESKTOP_DISCOVERY_VERSION",
    "DESKTOP_PROTOCOL_MAX",
    "DESKTOP_PROTOCOL_MIN",
    "HEARTBEAT_REFRESH_SECONDS",
    "HEARTBEAT_STALE_MS",
    "DesktopDiscoveryRecord",
    "DesktopDiscoveryState",
    "DiscoveryState",
    "ServiceInfo",
    "another_resident_is_live",
    "classify_desktop_discovery",
    "classify_discovery",
    "is_pid_alive",
    "port_has_listener",
    "probe_health",
    "read_desktop_discovery",
    "read_resident_service",
    "remove_service_json_if_owned",
    "service_json_path",
    "write_desktop_discovery",
    "write_service_json",
]

# Producer refresh cadence (R8): well under the 120s consumer staleness window so
# a live service never reads as stale between writes.
HEARTBEAT_REFRESH_SECONDS = 15

_SERVICE_JSON_NAME = "service.json"


class DiscoveryState(StrEnum):
    """Attach-never-own classification of a discovery file (R8)."""

    FRESH = "fresh"
    STALE = "stale"
    MALFORMED = "malformed"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    """A parsed discovery record. ``service_token`` is redacted from ``repr``."""

    port: int
    pid: int | None = None
    last_heartbeat: int | None = None
    service_token: str | None = None

    def __repr__(self) -> str:
        """Redacted representation — never leaks the service token."""
        token = "<set>" if self.service_token else None
        return (
            f"ServiceInfo(port={self.port}, pid={self.pid}, "
            f"last_heartbeat={self.last_heartbeat}, service_token={token})"
        )


def service_json_path(a2a_home: Path) -> Path:
    """Return the machine-global discovery file path under the A2A home."""
    return a2a_home / _SERVICE_JSON_NAME


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _service_info(info: dict) -> ServiceInfo | None:
    """Build a :class:`ServiceInfo` from a parsed record, or ``None`` if invalid."""
    port = _coerce_int(info.get("port"))
    if port is None:
        return None
    token = info.get("service_token")
    return ServiceInfo(
        port=port,
        pid=_coerce_int(info.get("pid")),
        last_heartbeat=_coerce_int(info.get("last_heartbeat")),
        service_token=token if isinstance(token, str) and token else None,
    )


def classify_discovery(
    path: Path, *, now_ms: int | None = None
) -> tuple[DiscoveryState, ServiceInfo | None]:
    """Classify a discovery file filesystem-only (no pid or /health probe, R8).

    ``ABSENT`` when the file is missing, ``MALFORMED`` when it is unreadable or
    lacks a valid ``port``, ``STALE`` when a present heartbeat is beyond the
    window, and ``FRESH`` otherwise. This is the cheap hot-path read; a
    ``FRESH`` result still warrants a pid/health probe before it is trusted as a
    live resident.
    """
    if not path.exists():
        return DiscoveryState.ABSENT, None
    info = read_service_json(path)
    if info is None:
        return DiscoveryState.MALFORMED, None
    service = _service_info(info)
    if service is None:
        return DiscoveryState.MALFORMED, None
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if not heartbeat_is_fresh(info, now):
        return DiscoveryState.STALE, service
    return DiscoveryState.FRESH, service


def read_resident_service(a2a_home: Path) -> tuple[DiscoveryState, ServiceInfo | None]:
    """Hot-path, filesystem-only discovery of the resident gateway (R8)."""
    return classify_discovery(service_json_path(a2a_home))


def is_pid_alive(pid: int | None) -> bool:
    """Return ``True`` when *pid* is a live process on this machine.

    Cross-platform without a third-party dependency: an ``OpenProcess`` query on
    Windows, a signal-0 probe on POSIX. A ``PermissionError`` (POSIX) means the
    process exists but is owned by another user — still alive.
    """
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process_query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        still_active = 259  # STILL_ACTIVE
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def port_has_listener(port: int, *, timeout: float) -> bool:
    """Return ``True`` when a loopback ``connect`` to *port* is accepted.

    The single connect-probe primitive for the lifecycle package: a successful
    ``connect_ex`` to ``127.0.0.1:port`` proves a live listener is accepting there.
    It is the ONLY reliable "is this port taken" signal on Windows, where a plain
    ``bind`` succeeds even when another process already serves the port (no
    ``SO_EXCLUSIVEADDRUSE``); a caller that must also catch a bound-but-not-yet-
    listening port pairs this with a bind-probe. *timeout* is required rather than
    defaulted because a readiness poll (fast) and a liveness check (patient) want
    different budgets.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def write_service_json(
    path: Path,
    *,
    port: int,
    pid: int,
    service_token: str | None = None,
    now_ms: int | None = None,
) -> None:
    """Atomically publish the discovery record with a fresh heartbeat.

    Writes to a sibling temp file then ``os.replace`` so a concurrent reader
    never observes a partially written record.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "port": port,
        "pid": pid,
        "last_heartbeat": now_ms if now_ms is not None else int(time.time() * 1000),
    }
    if service_token:
        record["service_token"] = service_token
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)


def probe_health(base_url: str, *, timeout: float = 2.0) -> dict | None:
    """Probe ``GET /health`` on a resident gateway (lifecycle-only, R8).

    Returns the parsed health body on a real ``200``, else ``None``. Reserved for
    lifecycle/ops callers; never used on the filesystem-only discovery hot path.
    """
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/health", timeout=timeout)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def another_resident_is_live(a2a_home: Path, *, health_timeout: float = 2.0) -> bool:
    """Return ``True`` when a different, live resident gateway already holds the file.

    Single-resident semantics (R8): the record must be ``FRESH``, its pid must be
    a live process, and its ``/health`` must answer ``200``. A crashed or stale
    record (dead pid, old heartbeat, no answer) is NOT a live resident — it is
    reclaimable — so this returns ``False`` and the caller may start and overwrite.
    """
    state, info = read_resident_service(a2a_home)
    if state is not DiscoveryState.FRESH or info is None:
        return False
    if not is_pid_alive(info.pid):
        return False
    base_url = f"http://127.0.0.1:{info.port}"
    return probe_health(base_url, timeout=health_timeout) is not None


def remove_service_json_if_owned(path: Path, pid: int) -> bool:
    """Remove the discovery file only when it records *pid* as its owner.

    Returns ``True`` when the file was removed. A file owned by a different pid is
    left in place — this process never reclaims another resident's record.
    """
    state, info = classify_discovery(path)
    if state in (DiscoveryState.ABSENT, DiscoveryState.MALFORMED):
        if state is DiscoveryState.MALFORMED:
            # A malformed file with no readable owner is ours to clear on exit.
            path.unlink(missing_ok=True)
            return True
        return False
    if info is not None and info.pid == pid:
        path.unlink(missing_ok=True)
        return True
    return False



# ---------------------------------------------------------------------------
# Versioned desktop discovery record
# ---------------------------------------------------------------------------
#
# The desktop profile publishes a richer, versioned discovery record than the
# R8 Compose record above. It never carries a bearer value: the attach
# credential lives in an owner-ACL-protected file that the record only
# *references* by path. The desktop gateway acquires the runtime singleton and
# binds its listener before publishing this record; a contender validates it
# (process identity, protocol compatibility, freshness) before attaching through
# the referenced credential file, never by trusting discovery alone.

# Bumped only on an incompatible desktop-record-shape change; a reader rejects an
# unknown version fail-closed rather than guessing at a foreign layout.
DESKTOP_DISCOVERY_VERSION = 1

# The desktop gateway's supported control-protocol range (the five-verb edge).
# Published so a contender refuses an incompatible resident instead of speaking
# past it.
DESKTOP_PROTOCOL_MIN = 1
DESKTOP_PROTOCOL_MAX = 1

_DESKTOP_PROFILE = "desktop"


class DesktopDiscoveryState(StrEnum):
    """Filesystem-only classification of a versioned desktop discovery record."""

    FRESH = "fresh"
    STALE = "stale"
    MALFORMED = "malformed"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class DesktopDiscoveryRecord:
    """A parsed versioned desktop discovery record. Carries no credential value.

    ``credential_reference`` is a filesystem path to the owner-ACL-protected
    attach-credential file, never the credential itself. ``start_fingerprint`` is
    ``None`` on platforms without a cheap process start-time source.
    """

    version: int
    profile: str
    generation: str
    protocol_min: int
    protocol_max: int
    pid: int
    start_fingerprint: str | None
    host: str
    port: int
    last_heartbeat: int
    owner: str
    credential_reference: str | None

    @property
    def base_url(self) -> str:
        """Return the loopback origin the record advertises."""
        return f"http://{self.host}:{self.port}"

    def supports_protocol(self, version: int) -> bool:
        """Return whether *version* falls within the advertised protocol range."""
        return self.protocol_min <= version <= self.protocol_max


def _parse_desktop_record(info: dict) -> DesktopDiscoveryRecord | None:
    """Map a parsed record dict to a versioned desktop record, or ``None``.

    Fail-closed: an absent or unknown ``version``, a non-``desktop`` profile, or
    any missing required identity/endpoint field yields ``None`` (classified
    ``MALFORMED``) rather than a partially trusted record.
    """
    if info.get("version") != DESKTOP_DISCOVERY_VERSION:
        return None
    if info.get("profile") != _DESKTOP_PROFILE:
        return None
    protocol = info.get("protocol")
    process = info.get("process")
    endpoint = info.get("endpoint")
    if not isinstance(protocol, dict) or not isinstance(process, dict):
        return None
    if not isinstance(endpoint, dict):
        return None
    protocol_min = _coerce_int(protocol.get("min"))
    protocol_max = _coerce_int(protocol.get("max"))
    pid = _coerce_int(process.get("pid"))
    port = _coerce_int(endpoint.get("port"))
    last_heartbeat = _coerce_int(info.get("last_heartbeat"))
    if (
        protocol_min is None
        or protocol_max is None
        or pid is None
        or port is None
        or last_heartbeat is None
    ):
        return None
    if protocol_min > protocol_max:
        return None
    host = endpoint.get("host")
    owner = info.get("owner")
    generation = info.get("generation")
    if not isinstance(host, str) or not host:
        return None
    if not isinstance(owner, str) or not isinstance(generation, str):
        return None
    fingerprint = process.get("start_fingerprint")
    if fingerprint is not None and not isinstance(fingerprint, str):
        return None
    reference = info.get("credential_reference")
    if reference is not None and not isinstance(reference, str):
        return None
    return DesktopDiscoveryRecord(
        version=DESKTOP_DISCOVERY_VERSION,
        profile=_DESKTOP_PROFILE,
        generation=generation,
        protocol_min=protocol_min,
        protocol_max=protocol_max,
        pid=pid,
        start_fingerprint=fingerprint,
        host=host,
        port=port,
        last_heartbeat=last_heartbeat,
        owner=owner,
        credential_reference=reference,
    )


def read_desktop_discovery(path: Path) -> DesktopDiscoveryRecord | None:
    """Read and validate a versioned desktop discovery record, or ``None``."""
    info = read_service_json(path)
    if info is None:
        return None
    return _parse_desktop_record(info)


def classify_desktop_discovery(
    path: Path, *, now_ms: int | None = None
) -> tuple[DesktopDiscoveryState, DesktopDiscoveryRecord | None]:
    """Classify a desktop discovery file filesystem-only (no pid or /health probe).

    ``ABSENT`` when the file is missing, ``MALFORMED`` when it is unreadable or is
    not a valid versioned desktop record, ``STALE`` when its heartbeat is beyond
    the freshness window, and ``FRESH`` otherwise. As with the Compose classifier,
    a ``FRESH`` result still warrants a process-liveness probe via
    :func:`desktop_record_process_is_live` before it is trusted as a live resident.
    """
    if not path.exists():
        return DesktopDiscoveryState.ABSENT, None
    info = read_service_json(path)
    if info is None:
        return DesktopDiscoveryState.MALFORMED, None
    record = _parse_desktop_record(info)
    if record is None:
        return DesktopDiscoveryState.MALFORMED, None
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if not heartbeat_is_fresh(info, now):
        return DesktopDiscoveryState.STALE, record
    return DesktopDiscoveryState.FRESH, record


def desktop_record_process_is_live(record: DesktopDiscoveryRecord) -> bool:
    """Return ``True`` when the record's recorded gateway process is still alive.

    Pid-liveness is the primary signal; the singleton's start fingerprint is the
    pid-reuse guard. Delegates to the runtime singleton's process-liveness
    authority so "prove this recorded process dead" has exactly one definition.
    """
    from .singleton import process_start_fingerprint

    if not is_pid_alive(record.pid):
        return False
    if record.start_fingerprint is None:
        return True
    current = process_start_fingerprint(record.pid)
    if current is None:
        return True
    return current == record.start_fingerprint


def write_desktop_discovery(
    path: Path,
    *,
    generation: str,
    port: int,
    owner: str,
    credential_reference: str | None = None,
    host: str = "127.0.0.1",
    protocol_min: int = DESKTOP_PROTOCOL_MIN,
    protocol_max: int = DESKTOP_PROTOCOL_MAX,
    pid: int | None = None,
    start_fingerprint: str | None = None,
    now_ms: int | None = None,
) -> DesktopDiscoveryRecord:
    """Atomically publish the versioned desktop discovery record and return it.

    Publishes no bearer value: ``credential_reference`` is a filesystem path to the
    owner-ACL-protected attach-credential file, never its contents. The record is
    written to a sibling temp file, fsynced, then ``os.replace``-renamed so a
    concurrent reader never observes a partially written record. ``pid`` and
    ``start_fingerprint`` default to this process's identity.
    """
    from .singleton import current_process_fingerprint

    resolved_pid = pid if pid is not None else os.getpid()
    fingerprint = (
        start_fingerprint
        if start_fingerprint is not None
        else current_process_fingerprint()
    )
    heartbeat = now_ms if now_ms is not None else int(time.time() * 1000)
    record = DesktopDiscoveryRecord(
        version=DESKTOP_DISCOVERY_VERSION,
        profile=_DESKTOP_PROFILE,
        generation=generation,
        protocol_min=protocol_min,
        protocol_max=protocol_max,
        pid=resolved_pid,
        start_fingerprint=fingerprint,
        host=host,
        port=port,
        last_heartbeat=heartbeat,
        owner=owner,
        credential_reference=credential_reference,
    )
    payload: dict[str, object] = {
        "version": record.version,
        "profile": record.profile,
        "generation": record.generation,
        "protocol": {"min": record.protocol_min, "max": record.protocol_max},
        "process": {"pid": record.pid, "start_fingerprint": record.start_fingerprint},
        "endpoint": {"host": record.host, "port": record.port},
        "last_heartbeat": record.last_heartbeat,
        "owner": record.owner,
        "credential_reference": record.credential_reference,
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        path.parent.chmod(0o700)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(payload).encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    _atomic_replace(tmp, path)
    return record


def _atomic_replace(tmp: Path, path: Path) -> None:
    """Rename *tmp* over *path*, riding out a transient Windows sharing violation.

    ``os.replace`` is atomic, but on Windows a concurrent reader holding the target
    open can briefly deny the rename with ``PermissionError``. The publication is
    still all-or-nothing; this only retries the rename over the short contention
    window rather than propagating a spurious failure to the heartbeat caller.
    """
    deadline = time.monotonic() + 2.0
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
