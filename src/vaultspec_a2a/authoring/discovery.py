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

__all__ = ["SERVICE_JSON_ENV", "EngineEndpoint", "resolve_engine"]

SERVICE_JSON_ENV = "VAULTSPEC_ENGINE_SERVICE_JSON"

# Consumer staleness window: a heartbeat older than this is treated as a crash,
# not as an available service (mirrors the engine's HEARTBEAT_STALE_MS).
_STALE_MS = 120_000


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
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(info, dict):
            continue
        heartbeat = info.get("last_heartbeat")
        if isinstance(heartbeat, (int, float)) and now_ms - heartbeat > _STALE_MS:
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
