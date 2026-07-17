"""Consolidated health-data assembly for gateway health endpoints.

Both ``/health`` (liveness) and ``/api/health`` (readiness) share a common
set of worker, circuit breaker, spawner, and infrastructure diagnostics.
This module provides ``assemble_health_status()`` as the single source of
truth for that shared data, plus ``build_sqlite_fallback_diagnostics()``
which was previously inlined in ``api/app.py``.

``build_full_health()`` is the async service function that runs all probes
(database, worker HTTP, checkpoint, circuit breaker) and returns the
complete readiness payload consumed by ``/api/health``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from ..database.session import inspect_sqlite_database
from .config import settings

if TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner, WorkerState

__all__ = [
    "assemble_health_status",
    "build_full_health",
    "build_sqlite_fallback_diagnostics",
    "probe_engine_discovery_freshness",
]

logger = logging.getLogger(__name__)


def probe_engine_discovery_freshness() -> bool | None:
    """Return engine authoring-backend discovery freshness without an HTTP probe.

    Reads the engine service.json candidates (the env override then the
    machine-global path) and classifies them by heartbeat only - never a live
    ``/health`` call - so the service-state path stays non-blocking. Returns True
    when a fresh, well-formed record is present, False when a record is present
    but stale or malformed, and None when no engine discovery file is configured
    for this process (authoring is simply not wired here).
    """
    import os
    import time
    from pathlib import Path

    from ..authoring.discovery import (
        SERVICE_JSON_ENV,
        heartbeat_is_fresh,
        read_service_json,
    )

    candidates: list[Path] = []
    env_path = os.environ.get(SERVICE_JSON_ENV)
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.home() / ".vaultspec" / "service.json")

    now_ms = int(time.time() * 1000)
    any_present = False
    for path in candidates:
        info = read_service_json(path)
        if info is None:
            continue
        any_present = True
        if heartbeat_is_fresh(info, now_ms) and isinstance(info.get("port"), int):
            return True
    return False if any_present else None


def build_sqlite_fallback_diagnostics(
    *,
    database_backend: str | None = None,
    checkpoint_backend: str | None = None,
    database_path: Path | None = None,
    checkpoint_path: Path | None = None,
    busy_timeout_ms: int | None = None,
) -> dict[str, object] | None:
    """Build explicit diagnostics for the SQLite fallback path."""
    resolved_database_backend = database_backend or settings.resolved_database_backend
    resolved_checkpoint_backend = (
        checkpoint_backend or settings.resolved_checkpoint_backend
    )
    if (
        resolved_database_backend != "sqlite"
        and resolved_checkpoint_backend != "sqlite"
    ):
        return None

    diagnostics: dict[str, object] = {
        "active": True,
        "busy_timeout_ms": busy_timeout_ms or settings.sqlite_busy_timeout_ms,
        "production_certifying": False,
        "limitations": ["sqlite_fallback_not_production_certifying"],
    }
    if resolved_database_backend == "sqlite":
        diagnostics["database"] = inspect_sqlite_database(
            database_path or settings.database_path
        )
    if resolved_checkpoint_backend == "sqlite":
        diagnostics["checkpoint"] = inspect_sqlite_database(
            checkpoint_path or settings.checkpoint_path
        )
    return diagnostics


def assemble_health_status(
    *,
    app_state: Any,
) -> dict[str, Any]:
    """Assemble the shared health-status payload from app state.

    Reads circuit breaker, spawner, worker state, repair summary, and SQLite
    fallback diagnostics from ``app_state``.  The returned dict contains all
    fields shared by both ``/health`` and ``/api/health``; each route adds its
    own unique fields on top.

    Parameters
    ----------
    app_state:
        The FastAPI ``app.state`` object carrying runtime singletons.

    Returns
    -------
    dict
        Shared health fields ready for inclusion in either endpoint's response.
    """
    # --- Circuit breaker ---
    cb: WorkerCircuitBreaker | None = getattr(app_state, "circuit_breaker", None)
    cb_state = cb.state if cb is not None else "unknown"

    # --- Spawner ---
    spawner: LazyWorkerSpawner | None = getattr(app_state, "worker_spawner", None)
    worker_spawned = spawner.spawned if spawner is not None else False
    worker_pid = (
        spawner.process.pid if spawner is not None and spawner.process else None
    )

    # --- Worker heartbeat ---
    last_hb = getattr(app_state, "worker_last_heartbeat_ts", None)
    worker_connected = False
    if last_hb is not None:
        worker_connected = (
            time.monotonic() - last_hb
        ) < settings.worker_heartbeat_timeout_seconds

    # --- Worker state ---
    ws: WorkerState | None = getattr(app_state, "worker_state", None)
    worker_status = ws.worker_status if ws is not None else "unknown"
    worker_restart_count = ws.worker_restart_count if ws is not None else 0
    worker_last_restart_reason = (
        ws.worker_last_restart_reason if ws is not None else None
    )
    worker_last_restart_detail = (
        ws.worker_last_restart_detail if ws is not None else None
    )
    worker_last_restart_started_at = (
        ws.worker_last_restart_started_at if ws is not None else None
    )
    worker_last_restart_completed_at = (
        ws.worker_last_restart_completed_at if ws is not None else None
    )
    worker_last_restart_succeeded = (
        ws.worker_last_restart_succeeded if ws is not None else None
    )
    worker_last_restart_attempts = (
        ws.worker_last_restart_attempts if ws is not None else 0
    )
    worker_stderr_log_path = ws.worker_stderr_log_path if ws is not None else None

    # --- Repair summary ---
    repair_summary: dict[str, int] = getattr(
        app_state,
        "repair_summary",
        {
            "repair_backlog": 0,
            "paused_resumable": 0,
            "checkpoint_unavailable": 0,
        },
    )

    # --- SQLite fallback ---
    sqlite_fallback_diagnostics = getattr(
        app_state, "sqlite_fallback_diagnostics", None
    )

    # A band gateway dispatching outside the worker-dev band with no band worker
    # present (the non-fatal half of the dispatch-pairing guard) surfaces here so an
    # operator sees the mis-target without reading logs.
    dispatch_pairing_warning = getattr(app_state, "dispatch_pairing_warning", None)

    return {
        "circuit_breaker": cb_state,
        "worker_connected": worker_connected,
        "worker_spawned": worker_spawned,
        "worker_pid": worker_pid,
        "worker_status": worker_status,
        "worker_restart_count": worker_restart_count,
        "worker_last_restart_reason": worker_last_restart_reason,
        "worker_last_restart_detail": worker_last_restart_detail,
        "worker_last_restart_started_at": worker_last_restart_started_at,
        "worker_last_restart_completed_at": worker_last_restart_completed_at,
        "worker_last_restart_succeeded": worker_last_restart_succeeded,
        "worker_last_restart_attempts": worker_last_restart_attempts,
        "worker_stderr_log_path": worker_stderr_log_path,
        "database_backend": settings.resolved_database_backend,
        "checkpoint_backend": settings.resolved_checkpoint_backend,
        "postgres_required": settings.postgres_required,
        "repair_backlog": repair_summary.get("repair_backlog", 0),
        "paused_resumable": repair_summary.get("paused_resumable", 0),
        "checkpoint_unavailable": repair_summary.get("checkpoint_unavailable", 0),
        "sqlite_fallback": sqlite_fallback_diagnostics,
        "dispatch_pairing_warning": dispatch_pairing_warning,
    }


async def build_full_health(
    *,
    db: AsyncSession,
    worker_client: httpx.AsyncClient,
    circuit_breaker: Any,
    worker_spawner: Any,
    app_state: Any,
) -> dict[str, Any]:
    """Run all health probes and return the complete readiness payload.

    This is the service-layer orchestration consumed by ``/api/health``.
    It runs the DB probe, worker HTTP check, checkpoint presence test,
    circuit breaker and spawner inspection, then computes overall readiness.
    """
    shared = assemble_health_status(app_state=app_state)

    checks: dict[str, dict[str, str]] = {}
    checks["gateway"] = {"status": "ok"}

    # --- Database probe ---
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = {
            "status": "ok",
            "backend": settings.resolved_database_backend,
            "postgres_required": "yes" if settings.postgres_required else "no",
        }
    except Exception:
        logger.exception("Health check: database probe failed")
        checks["database"] = {
            "status": "error",
            "backend": settings.resolved_database_backend,
            "detail": "database probe failed",
            "postgres_required": "yes" if settings.postgres_required else "no",
        }

    # --- Checkpointer probe ---
    checkpointer = getattr(app_state, "checkpointer", None)
    checkpoint_check: dict[str, str] = {
        "backend": settings.resolved_checkpoint_backend,
        "postgres_required": "yes" if settings.postgres_required else "no",
    }
    if checkpointer is None:
        checkpoint_check["status"] = "error"
        checkpoint_check["detail"] = "checkpointer missing"
    else:
        try:
            await asyncio.wait_for(
                checkpointer.aget_tuple(
                    {
                        "configurable": {
                            "thread_id": "__health_probe__",
                            "checkpoint_ns": "",
                        }
                    }
                ),
                timeout=5.0,
            )
            checkpoint_check["status"] = "ok"
        except TimeoutError:
            logger.warning("Health check: checkpoint probe timed out")
            checkpoint_check["status"] = "error"
            checkpoint_check["detail"] = "checkpoint probe timed out"
        except Exception:
            logger.exception("Health check: checkpoint probe failed")
            checkpoint_check["status"] = "error"
            checkpoint_check["detail"] = "checkpoint probe failed"
    checks["checkpoint"] = checkpoint_check

    # --- Worker HTTP probe ---
    # The single worker-health primitive, reusing the pooled client; "healthy" is an
    # exact 200 for both this endpoint and the watchdog, so they cannot disagree.
    from .worker_management import _check_worker_health

    if await _check_worker_health(
        settings.worker_url, timeout=5.0, client=worker_client
    ):
        checks["worker"] = {"status": "ok"}
    else:
        logger.warning("Health check: worker probe failed")
        checks["worker"] = {"status": "error", "detail": "worker probe failed"}

    # --- Circuit breaker & spawner ---
    checks["circuit_breaker"] = {"status": circuit_breaker.state}
    checks["worker_spawned"] = {"status": "yes" if worker_spawner.spawned else "no"}
    if shared["worker_stderr_log_path"] is not None:
        checks["worker_stderr_log"] = {"status": "configured"}

    # --- Overall readiness ---
    ready = (
        checks["gateway"]["status"] == "ok"
        and checks["database"]["status"] == "ok"
        and checks["checkpoint"]["status"] == "ok"
        and checks["worker"]["status"] == "ok"
        and checks["circuit_breaker"]["status"] == "closed"
    )
    return {
        "status": "ok" if ready else "degraded",
        "checks": checks,
        **shared,
    }
