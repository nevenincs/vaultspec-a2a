"""POST /permissions/{request_id}/respond -- Permission response (REST)."""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.config import domain_config
from ...control.permission_service import PermissionResult, respond_to_permission
from ...database.session import get_db
from ...streaming.aggregator import EventAggregator
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import (
    get_aggregator,
    get_circuit_breaker,
    get_worker_client,
    get_worker_spawner,
)
from ..schemas.rest import PermissionResponseRequest, PermissionResponseResult

router = APIRouter()


def _to_response(result: PermissionResult) -> PermissionResponseResult:
    """Map a service result to the REST response schema."""
    return PermissionResponseResult(
        request_id=result.request_id,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        thread_id=result.thread_id,
        action_id=result.action_id,
        idempotency_key=result.idempotency_key,
        approval_status=result.approval_status,
    )


@router.post(
    "/permissions/{request_id}/respond",
    response_model=PermissionResponseResult,
)
async def respond_to_permission_endpoint(
    request_id: str,
    body: PermissionResponseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    aggregator: EventAggregator = Depends(get_aggregator),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PermissionResponseResult:
    """Submit a permission response via REST for guaranteed delivery."""

    result = await respond_to_permission(
        db=db,
        request_id=request_id,
        option_id=body.option_id,
        idempotency_key=idempotency_key,
        aggregator=aggregator,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )

    if result.dispatched:
        mark_worker_connected(request)

    if result.circuit_open:
        raise HTTPException(status_code=503, detail=result.error_detail)

    if result.error_detail:
        raise HTTPException(
            status_code=result.error_status_code or 500,
            detail=result.error_detail,
        )

    return _to_response(result)
