"""POST /threads/{thread_id}/messages -- Send message into thread."""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.message_service import send_followup_message
from ...database.session import get_db
from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...thread.constants import DEFAULT_SUPERVISOR_ID
from ...thread.dispatch_policy import FailureType
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import (
    get_aggregator,
    get_circuit_breaker,
    get_worker_client,
    get_worker_spawner,
)
from ..schemas.rest import SendMessageRequest, SendMessageResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/threads/{thread_id}/messages",
    status_code=202,
    response_model=SendMessageResponse,
)
async def send_message_endpoint(
    thread_id: str,
    body: SendMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _aggregator: EventAggregator = Depends(get_aggregator),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SendMessageResponse:
    """Send a user message into an existing thread.

    Returns 202 Accepted immediately; the message is dispatched to the
    worker process for graph execution (ADR-019).
    """
    agent_id = body.agent_id or DEFAULT_SUPERVISOR_ID

    result = await send_followup_message(
        db=db,
        thread_id=thread_id,
        content=body.content,
        agent_id=agent_id,
        idempotency_key=idempotency_key,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )

    if result.failure_type == FailureType.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Thread not found")
    if result.failure_type == FailureType.INPUT_REQUIRED:
        raise HTTPException(status_code=409, detail=result.error_detail)
    if result.failure_type == FailureType.TERMINAL:
        raise HTTPException(status_code=409, detail=result.error_detail)

    if result.dispatched:
        mark_worker_connected(request)

    if result.failure_type is not None:
        if result.failure_type in (FailureType.CIRCUIT_OPEN, FailureType.AT_CAPACITY):
            raise HTTPException(status_code=503, detail=result.error_detail)
        raise HTTPException(status_code=502, detail=result.error_detail)

    return SendMessageResponse(
        status="accepted",
        thread_id=result.thread_id,
        accepted=True,
        applied=False,
        action_status=result.thread_status
        if not result.dispatched
        else "accepted_not_applied",
        action_id=result.action_id,
        idempotency_key=idempotency_key or "",
    )
