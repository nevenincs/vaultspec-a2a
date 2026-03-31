"""POST /threads/{thread_id}/cancel -- Cancel a running thread (MCP-R3)."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.cancel_service import cancel_thread
from ...database.session import get_db
from ...domain_config import domain_config
from ...thread.dispatch_policy import FailureType
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import get_circuit_breaker, get_worker_client, get_worker_spawner
from ..schemas.rest import CancelThreadResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/threads/{thread_id}/cancel",
    response_model=CancelThreadResponse,
)
async def cancel_thread_endpoint(
    thread_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CancelThreadResponse:
    """Cancel a running thread by dispatching a cancel action to the worker."""
    result = await cancel_thread(
        db=db,
        thread_id=thread_id,
        idempotency_key=idempotency_key,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )

    if result.failure_type == FailureType.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Thread not found")
    if result.failure_type is not None:
        raise HTTPException(
            status_code=502,
            detail=result.error_detail or "Cancel dispatch failed",
        )

    if result.cancelled:
        mark_worker_connected(request)

    return CancelThreadResponse(
        thread_id=result.thread_id,
        status=result.thread_status,
        cancelled=result.cancelled,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        action_id=result.action_id,
        idempotency_key=result.idempotency_key,
    )
