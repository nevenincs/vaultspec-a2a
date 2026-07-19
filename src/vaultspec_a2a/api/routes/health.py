"""GET /health -- Aggregated health check."""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.config import settings
from ...control.health import build_full_health
from ...database.session import get_db
from ..dependencies import get_circuit_breaker, get_worker_client, get_worker_spawner
from ..schemas.gateway import LivenessResponse

router = APIRouter()


@router.get("/health")
async def health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> dict:
    """Public health endpoint aggregating gateway, worker, and database status.

    Under the armed desktop profile this ungated surface discloses only the
    minimal liveness signal - no process identity, service identity, or product
    state crosses the unauthenticated boundary; the aggregate readiness facts move
    behind attach authentication on the service-state verb and the authenticated
    liveness surface. The Compose and development profiles retain the full
    aggregate body their gateway healthchecks already consume.
    """
    if settings.desktop_profile_armed:
        return LivenessResponse().model_dump(mode="json")
    return await build_full_health(
        db=db,
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        app_state=request.app.state,
    )
