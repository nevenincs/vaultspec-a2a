"""Engine discovery via the service.json contract (attach-never-own).

Resolves a live dashboard engine (base URL + machine bearer) from the engine's
own discovery file, applying the reference discipline verbatim: a present file
is trusted only when its heartbeat is fresh AND a real ``GET /health`` returns
200. A stale or crashed file (the documented 20-hour-stale specimen) is skipped,
never owned. Candidate order puts an explicit override
(``VAULTSPEC_ENGINE_SERVICE_JSON``, which a ``--no-seat`` workspace-local serve
writes) ahead of the machine-global ``~/.vaultspec/service.json``.

The bearer is read out of the file and never logged.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

__all__ = [
    "DESKTOP_RECORD_VERSION",
    "HEARTBEAT_STALE_MS",
    "SERVICE_JSON_ENV",
    "DiscoveryRecordView",
    "EngineEndpoint",
    "heartbeat_is_fresh",
    "parse_discovery_record",
    "read_discovery_record",
    "read_service_json",
    "resolve_engine",
    "resolve_engine_with_retry",
]

SERVICE_JSON_ENV = "VAULTSPEC_ENGINE_SERVICE_JSON"

# The versioned desktop record's identifying version and profile. The producer
# authority for this shape is ``lifecycle.discovery``; it is mirrored here (the
# lower, shared reader module — importing lifecycle would cycle) so this reader
# recognises a versioned record instead of misreading it as a malformed legacy
# one.
DESKTOP_RECORD_VERSION = 1
_DESKTOP_PROFILE = "desktop"

# Consumer staleness window: a heartbeat older than this is treated as a crash,
# not as an available service (mirrors the engine's HEARTBEAT_STALE_MS).
HEARTBEAT_STALE_MS = 120_000
_STALE_MS = HEARTBEAT_STALE_MS


def read_service_json(path: Path) -> dict | None:
    """Read and parse a service.json, or ``None`` if unreadable or not an object.

    The shared reader half of the discovery contract: it never raises, so both
    the engine consumer here and the resident-gateway producer's own boot check
    can classify a candidate without guarding every failure mode.
    """
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def _parse_heartbeat_ms(value: object) -> int | None:
    """Return *value* as a millisecond epoch, or ``None`` when it is unusable.

    Accepts a finite number and an ISO-8601 timestamp, because a peer may publish
    either. Rejects booleans, non-finite floats, unparseable strings, and every
    other type.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp() * 1000)
    return None


def heartbeat_is_fresh(info: dict, now_ms: int) -> bool:
    """Return whether the record's heartbeat licenses treating the peer as live.

    A record carrying no ``last_heartbeat`` is fresh: the field is optional per
    the contract, and its absence says nothing about liveness.

    A heartbeat that is PRESENT but unusable is stale, not fresh. That direction
    matters: this guard decides whether a peer is treated as running, so an
    unparseable, non-finite, or implausibly future value must not license
    liveness. A record claiming an infinite or far-future heartbeat would
    otherwise read as permanently fresh, which is exactly the shape a stale or
    forged record takes.

    A future heartbeat is tolerated only within one staleness window, which
    absorbs ordinary clock skew between peers without accepting a timestamp that
    could pin freshness indefinitely.
    """
    if "last_heartbeat" not in info or info.get("last_heartbeat") is None:
        return True
    heartbeat = _parse_heartbeat_ms(info.get("last_heartbeat"))
    if heartbeat is None:
        return False
    if heartbeat - now_ms > HEARTBEAT_STALE_MS:
        return False
    return now_ms - heartbeat <= HEARTBEAT_STALE_MS


@dataclass(frozen=True, slots=True)
class DiscoveryRecordView:
    """A shape-agnostic view of a discovery record: legacy or versioned desktop.

    ``bearer_token`` is the inline machine bearer of a legacy record; a versioned
    desktop record is secret-free, so its ``bearer_token`` is always ``None`` and
    its owner-restricted attach credential is named only by
    ``credential_reference`` (a filesystem path, never a value).
    """

    port: int
    host: str
    versioned: bool
    bearer_token: str | None
    credential_reference: str | None

    @property
    def base_url(self) -> str:
        """Return the loopback origin the record advertises."""
        return f"http://{self.host}:{self.port}"


def _coerce_port(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def parse_discovery_record(info: dict) -> DiscoveryRecordView | None:
    """Parse a discovery record dict into a view, preferring the versioned shape.

    A record carrying the known desktop ``version`` and ``desktop`` profile is
    read as versioned (secret-free, endpoint nested under ``endpoint``); anything
    else is read as the legacy R8 record (top-level ``port`` and inline
    ``service_token``). Fail-closed: a record without a valid integer port yields
    ``None`` rather than a partially trusted view.
    """
    if (
        info.get("version") == DESKTOP_RECORD_VERSION
        and info.get("profile") == _DESKTOP_PROFILE
    ):
        endpoint = info.get("endpoint")
        if not isinstance(endpoint, dict):
            return None
        port = _coerce_port(endpoint.get("port"))
        if port is None:
            return None
        host = endpoint.get("host")
        reference = info.get("credential_reference")
        return DiscoveryRecordView(
            port=port,
            host=host if isinstance(host, str) and host else "127.0.0.1",
            versioned=True,
            bearer_token=None,
            credential_reference=(
                reference if isinstance(reference, str) and reference else None
            ),
        )
    port = _coerce_port(info.get("port"))
    if port is None:
        return None
    token = info.get("service_token")
    reference = info.get("handoff_reference")
    return DiscoveryRecordView(
        port=port,
        host="127.0.0.1",
        versioned=False,
        bearer_token=token if isinstance(token, str) and token else None,
        credential_reference=(
            reference if isinstance(reference, str) and reference else None
        ),
    )


def read_discovery_record(path: Path) -> DiscoveryRecordView | None:
    """Read and parse a discovery file into a shape-agnostic view, or ``None``."""
    info = read_service_json(path)
    if info is None:
        return None
    return parse_discovery_record(info)


@dataclass(frozen=True, slots=True)
class EngineEndpoint:
    """A resolved, liveness-confirmed engine origin and its machine bearer."""

    base_url: str
    bearer_token: str

    def __repr__(self) -> str:
        """Redacted representation - never leaks the bearer token."""
        return f"EngineEndpoint(base_url={self.base_url!r}, bearer_token=<set>)"


def _candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get(SERVICE_JSON_ENV)
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".vaultspec" / "service.json")
    return candidates


def resolve_engine(*, liveness_timeout: float = 3.0) -> EngineEndpoint | None:
    """Return a live :class:`EngineEndpoint`, or ``None`` if none is reachable.

    Non-raising by contract: an unreadable file, a stale heartbeat, a malformed
    record, or a refused ``/health`` probe are all skipped so a caller can poll
    this on a loop without guarding every failure mode. A versioned, secret-free
    desktop record is now parsed rather than misread as malformed, and skipped
    for engine resolution because it carries no inline machine bearer; the
    engine's own record remains the legacy inline-token shape, so this path is
    unchanged for it.
    """
    now_ms = int(time.time() * 1000)
    for path in _candidates():
        info = read_service_json(path)
        if info is None or not heartbeat_is_fresh(info, now_ms):
            continue
        view = parse_discovery_record(info)
        if view is None or view.bearer_token is None:
            continue
        base_url = f"http://127.0.0.1:{view.port}"
        try:
            resp = httpx.get(f"{base_url}/health", timeout=liveness_timeout)
        except httpx.HTTPError:
            continue
        if resp.status_code == 200:
            return EngineEndpoint(base_url=base_url, bearer_token=view.bearer_token)
    return None


def resolve_engine_with_retry(
    *,
    attempts: int = 4,
    delay_seconds: float = 2.0,
    liveness_timeout: float = 3.0,
) -> EngineEndpoint | None:
    """Resolve the engine, riding out its transient stall windows.

    The engine periodically stops answering ``/health`` for several seconds
    (measured live: ~4-6s windows while its scope watcher rebuilds), so a
    single :func:`resolve_engine` probe at a decision point - the worker's
    run-start submitter build - can miss a healthy engine and truthfully fail
    a run that would have succeeded moments later. This is the single home of
    the bounded poll the ``resolve_engine`` docstring anticipates: up to
    *attempts* probes spaced *delay_seconds* apart, returning on the first
    success, ``None`` only when the engine stayed unreachable across the whole
    window. Blocking (sleep + probe); callers on an event loop should offload
    or accept the bounded stall as they do for the surrounding work.
    """
    for attempt in range(1, attempts + 1):
        endpoint = resolve_engine(liveness_timeout=liveness_timeout)
        if endpoint is not None:
            return endpoint
        if attempt < attempts:
            time.sleep(delay_seconds)
    return None
