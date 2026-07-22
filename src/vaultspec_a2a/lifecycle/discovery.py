"""Machine-global service discovery and heartbeat for the resident gateway (R8).

The resident A2A gateway publishes ``~/.vaultspec-a2a/service.json`` so the engine
can attach to it under the attach-never-own discipline. The record adopts the R8
``ServiceInfo`` contract: ``port`` required; optional ``pid``, a non-secret
``handoff_reference``, and ``last_heartbeat`` (ms-epoch). The bearer lives in
the referenced owner-restricted file, never in discovery. The producer refreshes the
heartbeat every :data:`HEARTBEAT_REFRESH_SECONDS`; a consumer treats a heartbeat
older than :data:`~vaultspec_a2a.authoring.discovery.HEARTBEAT_STALE_MS` as a
crash.

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
import secrets
import socket
import stat
import subprocess
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

from ..artifacts import ArtifactDeclaration, RetentionDisposition
from ..authoring.discovery import (
    HEARTBEAT_STALE_MS as HEARTBEAT_STALE_MS,
)
from ..authoring.discovery import (
    heartbeat_is_fresh,
    read_service_json,
)
from ..desktop._filesystem_authority import (
    assert_directory_authority,
    create_anonymous_file,
    create_private_file,
    directory_lease,
    path_is_link_like,
    publish_no_replace,
    resolve_directory_authority,
)
from ..desktop._platform_acl import (
    restrict_windows_file as _restrict_windows_file,
)
from ..desktop._platform_acl import (
    windows_file_is_restricted as _windows_file_is_restricted,
)
from ..utils.coercion import coerce_int
from .atomic_write import atomic_write_text

__all__ = [
    "ARTIFACT_DECLARATIONS",
    "DESKTOP_DISCOVERY_VERSION",
    "DESKTOP_PROTOCOL_MAX",
    "DESKTOP_PROTOCOL_MIN",
    "HEARTBEAT_REFRESH_SECONDS",
    "HEARTBEAT_STALE_MS",
    "SERVICE_CREDENTIAL_DECLARATION",
    "SERVICE_DISCOVERY_DECLARATION",
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

# What this module leaves on disk, and who is answerable for it afterwards.
# Both records are session-scoped in intent: they describe a running gateway and
# are meaningless once it exits. Enforcement is currently partial, and the
# mechanism text says so rather than implying a reaper that does not exist - a
# record outliving its process is exactly how a pre-feature discovery file was
# read as a live unauthenticated gateway two days after the process died.
SERVICE_DISCOVERY_DECLARATION = ArtifactDeclaration(
    name="service-discovery-record",
    root="<a2a_home>/service.json",
    owner="lifecycle.discovery",
    disposition=RetentionDisposition.SESSION_SCOPED,
    mechanism=(
        "removed by remove_service_json_if_owned on a clean exit; NOT removed on "
        "a crash, so a stale record can outlive its gateway indefinitely"
    ),
)

SERVICE_CREDENTIAL_DECLARATION = ArtifactDeclaration(
    name="service-handoff-credential",
    root="<a2a_home>/service.token",
    owner="lifecycle.discovery",
    disposition=RetentionDisposition.SESSION_SCOPED,
    mechanism=(
        "replaced on each authenticated publication and unlinked by a deliberate "
        "tokenless un-publish; shares the discovery record's crash exposure"
    ),
)

ARTIFACT_DECLARATIONS: tuple[ArtifactDeclaration, ...] = (
    SERVICE_DISCOVERY_DECLARATION,
    SERVICE_CREDENTIAL_DECLARATION,
)


class DiscoveryState(StrEnum):
    """Attach-never-own classification of a discovery file (R8)."""

    FRESH = "fresh"
    STALE = "stale"
    MALFORMED = "malformed"
    ABSENT = "absent"


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    """A parsed discovery record plus its validated local handoff credential."""

    port: int
    pid: int | None = None
    last_heartbeat: int | None = None
    service_token: str | None = None
    handoff_reference: str | None = None

    def __repr__(self) -> str:
        """Redacted representation — never leaks the service token."""
        token = "<set>" if self.service_token else None
        return (
            f"ServiceInfo(port={self.port}, pid={self.pid}, "
            f"last_heartbeat={self.last_heartbeat}, service_token={token}, "
            f"handoff_reference={self.handoff_reference!r})"
        )


def service_json_path(a2a_home: Path) -> Path:
    """Return the machine-global discovery file path under the A2A home."""
    return a2a_home / _SERVICE_JSON_NAME


def _read_handoff_credential(discovery_path: Path, reference: object) -> str | None:
    """Read only this discovery record's regular, owner-restricted token file."""
    if not isinstance(reference, str) or not reference:
        return None
    candidate = Path(reference)
    try:
        authority = resolve_directory_authority(discovery_path.parent)
        expected = authority.path / "service.token"
        if candidate != expected or path_is_link_like(candidate):
            return None
        with directory_lease(authority) as leased:
            if path_is_link_like(expected):
                return None
            if os.name == "posix":
                if leased.dir_fd is None or not hasattr(os, "O_NOFOLLOW"):
                    return None
                descriptor = os.open(
                    "service.token",
                    os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=leased.dir_fd,
                )
                named = os.stat(
                    "service.token", dir_fd=leased.dir_fd, follow_symlinks=False
                )
            else:
                descriptor = os.open(
                    expected,
                    os.O_RDONLY | getattr(os, "O_BINARY", 0),
                )
                named = expected.stat(follow_symlinks=False)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(named.st_mode)
                    or not stat.S_ISREG(opened.st_mode)
                    or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
                ):
                    return None
                if os.name == "posix" and (
                    opened.st_uid != os.geteuid() or opened.st_mode & 0o077
                ):
                    return None
                if not _windows_file_is_restricted(expected):
                    return None
                with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                    descriptor = -1
                    token = handle.read().strip()
                assert_directory_authority(leased)
                named_after = expected.stat(follow_symlinks=False)
                if path_is_link_like(expected) or (
                    named_after.st_dev,
                    named_after.st_ino,
                ) != (opened.st_dev, opened.st_ino):
                    return None
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
    except (OSError, subprocess.SubprocessError):
        return None
    return token or None


def _replace_private_credential(path: Path, payload: bytes) -> Path:
    """Replace the adjacent credential through one leased parent authority."""
    authority = resolve_directory_authority(path.parent)
    destination_name = "service.token"
    destination = authority.path / destination_name
    with directory_lease(authority, publication=True) as leased:
        if path_is_link_like(destination):
            raise OSError("credential destination is link-like")
        try:
            metadata = destination.stat(follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("credential destination is not a regular file")
            destination.unlink()
            assert_directory_authority(leased)

        anonymous = False
        if os.name == "nt":
            source_name = f".service-token-{os.getpid()}-{secrets.token_hex(16)}"
            handle = create_private_file(leased, source_name)
        else:
            source_name = f".service-token-{os.getpid()}-{secrets.token_hex(16)}"
            try:
                handle = create_anonymous_file(leased)
                anonymous = True
            except OSError:
                handle = create_private_file(leased, source_name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            if os.name == "posix":
                os.fchmod(handle.fileno(), 0o600)
            else:
                _restrict_windows_file(leased.path / source_name)
            if os.name == "nt" or anonymous:
                publish_no_replace(
                    leased,
                    source_name,
                    destination_name,
                    source_fd=handle.fileno(),
                )
            else:
                if leased.dir_fd is None:
                    raise OSError("POSIX credential authority is not leased")
                os.link(
                    source_name,
                    destination_name,
                    src_dir_fd=leased.dir_fd,
                    dst_dir_fd=leased.dir_fd,
                    follow_symlinks=False,
                )
                opened = os.fstat(handle.fileno())
                published = os.stat(
                    destination_name,
                    dir_fd=leased.dir_fd,
                    follow_symlinks=False,
                )
                if not stat.S_ISREG(published.st_mode) or (
                    published.st_dev,
                    published.st_ino,
                ) != (opened.st_dev, opened.st_ino):
                    os.unlink(destination_name, dir_fd=leased.dir_fd)
                    raise OSError("credential publication identity changed")
                os.unlink(source_name, dir_fd=leased.dir_fd)
        finally:
            handle.close()
            if not anonymous:
                (leased.path / source_name).unlink(missing_ok=True)
        assert_directory_authority(leased)
    return destination


def _service_info(info: dict, discovery_path: Path) -> ServiceInfo | None:
    """Build a :class:`ServiceInfo` from a parsed record, or ``None`` if invalid."""
    port = coerce_int(info.get("port"))
    if port is None:
        return None
    reference = info.get("handoff_reference")
    token = _read_handoff_credential(discovery_path, reference)
    return ServiceInfo(
        port=port,
        pid=coerce_int(info.get("pid")),
        last_heartbeat=coerce_int(info.get("last_heartbeat")),
        service_token=token,
        handoff_reference=reference if isinstance(reference, str) else None,
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
    service = _service_info(info, path)
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

    The lifecycle spelling of the package's single liveness probe, adding this
    layer's ``None`` handling (an unrecorded pid is not alive) on top of
    :func:`vaultspec_a2a.utils.process.pid_is_live`, which owns the platform
    contract: an ``OpenProcess`` exit-code query on Windows, and on POSIX a
    signal-0 probe that discounts an unreaped zombie.
    """
    from ..utils.process import pid_is_live

    if pid is None:
        return False
    return pid_is_live(pid)


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
    allow_tokenless: bool = False,
) -> None:
    """Atomically publish the discovery record with a fresh heartbeat.

    Writes to a sibling temp file then ``os.replace`` so a concurrent reader
    never observes a partially written record.

    A publication without *service_token* is destructive rather than inert: it
    strips the handoff reference from the record and unlinks the credential
    beside it, downgrading a healthy authenticated record to one a reader
    resolves with no bearer.  Because the gateway always mints a credential, a
    tokenless call is a defect at every production call site, so it must be
    opted into explicitly via *allow_tokenless* - the un-publish case is real
    but rare, and silence is what let an unauthenticated record persist
    unnoticed.

    Raises:
        ValueError: If *service_token* is absent and *allow_tokenless* is not set.
    """
    if not service_token and not allow_tokenless:
        raise ValueError(
            "refusing to publish a discovery record without a service token: "
            "this would unlink the credential and downgrade the record to "
            "unauthenticated; pass allow_tokenless=True to un-publish on purpose"
        )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        path.parent.chmod(0o700)
    else:
        parent_authority = resolve_directory_authority(path.parent)
        _restrict_windows_file(parent_authority.path)
        if not _windows_file_is_restricted(parent_authority.path):
            raise OSError("discovery parent does not have a private ACL")
    record: dict[str, object] = {
        "port": port,
        "pid": pid,
        "last_heartbeat": now_ms if now_ms is not None else int(time.time() * 1000),
    }
    credential_path = path.parent.resolve(strict=True) / "service.token"
    credential_is_current = (
        service_token
        and _read_handoff_credential(path, str(credential_path)) == service_token
    )
    if service_token and not credential_is_current:
        credential_path = _replace_private_credential(
            path, service_token.encode("utf-8")
        )
    if service_token:
        record["handoff_reference"] = str(credential_path)
    else:
        if path_is_link_like(credential_path):
            raise OSError("credential destination is link-like")
        credential_path.unlink(missing_ok=True)
    atomic_write_text(path, json.dumps(record))


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
            # The credential goes with it: an unreadable record can never again
            # reference its token, so leaving the token behind would strand a
            # credential no reader can reach and no exit path would collect.
            path.unlink(missing_ok=True)
            _remove_handoff_credential(path)
            return True
        return False
    if info is not None and info.pid == pid:
        path.unlink(missing_ok=True)
        _remove_handoff_credential(path)
        return True
    return False


def _remove_handoff_credential(discovery_path: Path) -> None:
    """Remove the credential beside *discovery_path*, refusing a link-like target.

    The refusal matters: unlinking a symlink placed where the credential belongs
    would let an attacker who can write the directory redirect the removal, so a
    link-like destination is left alone rather than followed.
    """
    credential = discovery_path.with_name("service.token")
    if path_is_link_like(credential):
        return
    credential.unlink(missing_ok=True)


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

# The desktop gateway's supported control-protocol range (five control verbs
# plus the bounded active-run discovery read).
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
    protocol_min = coerce_int(protocol.get("min"))
    protocol_max = coerce_int(protocol.get("max"))
    pid = coerce_int(process.get("pid"))
    port = coerce_int(endpoint.get("port"))
    last_heartbeat = coerce_int(info.get("last_heartbeat"))
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
    atomic_write_text(path, json.dumps(payload), mode=0o600)
    return record
