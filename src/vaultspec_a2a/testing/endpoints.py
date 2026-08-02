"""Resolve live service endpoints the way production does: from the registry.

The dev-process registry is the discovery mechanism for allocated services - a
gateway booted by the lifecycle verbs takes a band port and registers pid,
port, role, and heartbeat machine-globally. A test harness that falls back to a
fixed default port concludes "no stack" on a correctly-running host whenever
the port was allocated rather than defaulted, and skips a proof the registry
could have run. Resolution here therefore consults, in order:

- the explicit environment override (operator control keeps the last word);
- the registry's LIVE records for the role - alive pid AND fresh heartbeat,
  judged by the production classifier - freshest first, each confirmed with a
  real health probe before it is trusted.

A record that is DEAD or STALE is refused exactly as the lifecycle verbs would
refuse it; a record whose health probe fails is passed over, so an inherited
port serving some foreign process never resolves as our service.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from ..control.config import GATEWAY_URL_ENV, WORKER_URL_ENV
from ..lifecycle import (
    ProcsConfig,
    ProcsConfigError,
    StalenessState,
    classify_record,
    list_records,
    load_procs_config,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..lifecycle import ProcRecord

__all__ = [
    "ResolvedService",
    "resolve_gateway_url",
    "resolve_service",
    "resolve_worker_url",
]


@dataclass(frozen=True, slots=True)
class ResolvedService:
    """A reachable service: its base URL and, when registry-found, its record."""

    url: str
    record: ProcRecord | None

    @property
    def source(self) -> str:
        """Where the resolution came from, for diagnostics."""
        if self.record is None:
            return "environment override"
        return (
            f"registry record {self.record.role}-{self.record.name} "
            f"(pid {self.record.pid}, port {self.record.port})"
        )


def _health_answers(url: str, *, timeout_s: float) -> bool:
    try:
        return httpx.get(f"{url}/health", timeout=timeout_s).status_code == 200
    except httpx.HTTPError:
        return False


def _load_config() -> ProcsConfig | None:
    try:
        return load_procs_config()
    except ProcsConfigError:
        return None


def resolve_service(
    role: str,
    *,
    env_var: str = "",
    home: Path | None = None,
    health_timeout_s: float = 3.0,
) -> ResolvedService | None:
    """Resolve a live, health-answering endpoint for *role*, or ``None``.

    The environment override, when set, is returned WITHOUT a health probe:
    the operator's explicit word is a guarantee to honor, and an unreachable
    override should fail the consuming test loudly rather than dissolve into a
    silent registry fallback.
    """
    if env_var:
        override = (os.environ.get(env_var) or "").strip()
        if override:
            return ResolvedService(url=override.rstrip("/"), record=None)
    config = _load_config()
    role_config = config.roles.get(role) if config is not None else None
    candidates = [record for record in list_records(home) if record.role == role]
    candidates.sort(key=lambda record: record.last_seen_ms, reverse=True)
    for record in candidates:
        if classify_record(record, role_config) is not StalenessState.LIVE:
            continue
        url = f"http://127.0.0.1:{record.port}"
        if _health_answers(url, timeout_s=health_timeout_s):
            return ResolvedService(url=url, record=record)
    return None


def resolve_gateway_url(
    *, home: Path | None = None, health_timeout_s: float = 3.0
) -> ResolvedService | None:
    """The a2a gateway: explicit override, else the registry's live gateway-dev."""
    return resolve_service(
        "gateway-dev",
        env_var=GATEWAY_URL_ENV,
        home=home,
        health_timeout_s=health_timeout_s,
    )


def resolve_worker_url(
    *, home: Path | None = None, health_timeout_s: float = 3.0
) -> ResolvedService | None:
    """The a2a worker: explicit override, else the registry's live worker-dev."""
    return resolve_service(
        "worker-dev",
        env_var=WORKER_URL_ENV,
        home=home,
        health_timeout_s=health_timeout_s,
    )
