"""Engine discovery via the service.json contract (attach-never-own, ADR R8).

Resolves a live dashboard engine (base URL + machine bearer) from the engine's
own discovery file, applying the reference discipline verbatim: a present file
is trusted only when its heartbeat is fresh AND a real ``GET /health`` returns
200. A stale or crashed file (the documented 20-hour-stale specimen) is skipped,
never owned. Candidate order puts an explicit override
(``VAULTSPEC_ENGINE_SERVICE_JSON``, which a ``--no-seat`` workspace-local serve
writes) ahead of the machine-global ``~/.vaultspec/service.json``.

The bearer is read out of the file and never logged (R7).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

__all__ = [
    "HEARTBEAT_STALE_MS",
    "SERVICE_JSON_ENV",
    "EngineEndpoint",
    "heartbeat_is_fresh",
    "read_service_json",
    "resolve_engine",
]

SERVICE_JSON_ENV = "VAULTSPEC_ENGINE_SERVICE_JSON"

# Consumer staleness window: a heartbeat older than this is treated as a crash,
# not as an available service (mirrors the engine's HEARTBEAT_STALE_MS, ADR R8).
HEARTBEAT_STALE_MS = 120_000
_STALE_MS = HEARTBEAT_STALE_MS


def read_service_json(path: Path) -> dict | None:
    """Read and parse a service.json, or ``None`` if unreadable or not an object.

    The shared reader half of the R8 discovery contract: it never raises, so both
    the engine consumer here and the resident-gateway producer's own boot check
    can classify a candidate without guarding every failure mode.
    """
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def heartbeat_is_fresh(info: dict, now_ms: int) -> bool:
    """Return ``False`` only when a present heartbeat is older than the window.

    A record with no ``last_heartbeat`` is treated as fresh (the field is
    optional per the contract); a present ms-epoch heartbeat older than
    :data:`HEARTBEAT_STALE_MS` reads as a crash.
    """
    heartbeat = info.get("last_heartbeat")
    if isinstance(heartbeat, bool) or not isinstance(heartbeat, (int, float)):
        return True
    return now_ms - heartbeat <= HEARTBEAT_STALE_MS


@dataclass(frozen=True, slots=True)
class EngineEndpoint:
    """A resolved, liveness-confirmed engine origin and its machine bearer."""

    base_url: str
    bearer_token: str

    def __repr__(self) -> str:
        """Redacted representation - never leaks the bearer token (R7)."""
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
    this on a loop without guarding every failure mode.
    """
    now_ms = int(time.time() * 1000)
    for path in _candidates():
        info = read_service_json(path)
        if info is None or not heartbeat_is_fresh(info, now_ms):
            continue
        port = info.get("port")
        token = info.get("service_token")
        if not isinstance(port, int) or not isinstance(token, str):
            continue
        base_url = f"http://127.0.0.1:{port}"
        try:
            resp = httpx.get(f"{base_url}/health", timeout=liveness_timeout)
        except httpx.HTTPError:
            continue
        if resp.status_code == 200:
            return EngineEndpoint(base_url=base_url, bearer_token=token)
    return None
