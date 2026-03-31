"""Consolidated health-data assembly for gateway health endpoints (D-06).

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
]

logger = logging.getLogger(__name__)


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

    # --- Checkpointer presence ---
    checkpointer_present = getattr(app_state, "checkpointer", None) is not None
    checks["checkpoint"] = {
        "status": "ok" if checkpointer_present else "error",
        "backend": settings.resolved_checkpoint_backend,
        "postgres_required": "yes" if settings.postgres_required else "no",
    }

    # --- Worker HTTP probe ---
    try:
        resp = await worker_client.get("/health", timeout=5.0)
        resp.raise_for_status()
        checks["worker"] = {"status": "ok"}
    except Exception:
        logger.exception("Health check: worker probe failed")
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
