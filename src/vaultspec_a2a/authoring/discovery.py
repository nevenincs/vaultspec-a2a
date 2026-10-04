"""Engine attachment from protected discovery and authenticated health.

Record reading and freshness checks remain shared with gateway lifecycle classification.
Only the engine-specific resolver grants authoring endpoint authority.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, override

from ..utils.coercion import coerce_object_mapping
from ._engine_trust import prove_engine_identity, read_engine_record

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "HEARTBEAT_STALE_MS",
    "EngineEndpoint",
    "heartbeat_is_fresh",
    "read_service_json",
    "resolve_engine",
    "resolve_engine_with_retry",
    "service_json_candidates",
]


# Consumer staleness window: a heartbeat older than this is treated as a crash,
# not as an available service (mirrors the engine's HEARTBEAT_STALE_MS).
HEARTBEAT_STALE_MS = 120_000


def read_service_json(path: Path) -> dict[str, object] | None:
    """Read and parse a service.json, or ``None`` if unreadable or not an object.

    The shared reader half of the discovery contract: it never raises, so both
    the engine consumer here and the resident-gateway producer's own boot check
    can classify a candidate without guarding every failure mode.
    """
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return coerce_object_mapping(decoded)


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


def heartbeat_is_fresh(info: Mapping[str, object], now_ms: int) -> bool:
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
class EngineEndpoint:
    """A resolved, liveness-confirmed engine origin and its machine bearer."""

    base_url: str
    bearer_token: str

    @override
    def __repr__(self) -> str:
        """Redacted representation - never leaks the bearer token."""
        return f"EngineEndpoint(base_url={self.base_url!r}, bearer_token=<set>)"


def service_json_candidates() -> list[Path]:
    """Return the ordered service.json candidate paths this process consults.

    The configured ``engine_service_json`` is the one candidate, defaulting to
    external per-project engine state. Exported so every reader of
    the discovery file shares this ordering rather than restating it — a
    caller that only classifies freshness (never resolves a live endpoint)
    still needs the same candidate list.
    """
    from ..control.config import settings

    return [settings.engine_discovery_path]


def resolve_engine(*, liveness_timeout: float = 3.0) -> EngineEndpoint | None:
    """Return a live :class:`EngineEndpoint`, or ``None`` if none is reachable.

    Repository-controlled, linked, public, legacy, stale, or unproven records
    are unavailable. This same boundary applies during bearer re-resolution.
    """
    from ..control.config import settings

    now_ms = int(time.time() * 1000)
    roots = (settings.project_root,)
    if settings.workspace_root is not None:
        roots += (settings.workspace_root,)
    for path in service_json_candidates():
        record = read_engine_record(path, workspace_roots=roots, now_ms=now_ms)
        if record is None:
            continue
        if prove_engine_identity(record, timeout=liveness_timeout):
            return EngineEndpoint(
                base_url=record.base_url, bearer_token=record.bearer_token
            )
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
