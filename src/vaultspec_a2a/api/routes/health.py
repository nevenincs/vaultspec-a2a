"""GET /health -- Aggregated health check."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.config import settings
from ...control.health import assemble_health_status
from ...database.session import get_db
from ..dependencies import get_circuit_breaker, get_worker_client, get_worker_spawner

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> dict:
    """Public health endpoint aggregating gateway, worker, and database status."""
    shared = assemble_health_status(app_state=request.app.state)

    checks: dict[str, dict[str, str]] = {}

    checks["gateway"] = {"status": "ok"}

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

    checkpointer_present = getattr(request.app.state, "checkpointer", None) is not None
    checks["checkpoint"] = {
        "status": "ok" if checkpointer_present else "error",
        "backend": settings.resolved_checkpoint_backend,
        "postgres_required": "yes" if settings.postgres_required else "no",
    }

    try:
        resp = await worker_client.get("/health", timeout=5.0)
        resp.raise_for_status()
        checks["worker"] = {"status": "ok"}
    except Exception:
        logger.exception("Health check: worker probe failed")
        checks["worker"] = {"status": "error", "detail": "worker probe failed"}

    checks["circuit_breaker"] = {"status": circuit_breaker.state}
    checks["worker_spawned"] = {"status": "yes" if worker_spawner.spawned else "no"}
    if shared["worker_stderr_log_path"] is not None:
        checks["worker_stderr_log"] = {"status": "configured"}

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
