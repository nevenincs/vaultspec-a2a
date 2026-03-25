"""POST /threads/{thread_id}/cancel -- Cancel a running thread (MCP-R3)."""

import hashlib
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.dispatch import (
    WorkerAtCapacityError,
    WorkerUnreachableError,
    dispatch_to_worker,
)
from ...database.crud import (
    ControlActionResultStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
    create_control_action,
    get_control_action_by_idempotency_key,
    get_thread,
    set_thread_repair_state,
    update_thread_status,
)
from ...database.session import get_db
from ...ipc.schemas import DispatchRequest
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
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    if thread.status in (
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
        ThreadStatus.ARCHIVED,
    ):
        return CancelThreadResponse(
            thread_id=thread_id,
            status=thread.status,
            cancelled=False,
            accepted=False,
            applied=thread.status == ThreadStatus.CANCELLED.value,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        )

    resolved_idempotency_key = (
        idempotency_key or hashlib.sha256(f"{thread_id}:cancel".encode()).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return CancelThreadResponse(
            thread_id=thread_id,
            status=ThreadStatus.CANCELLING.value,
            cancelled=True,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
        )

    dispatched = False
    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.CANCEL,
        idempotency_key=resolved_idempotency_key,
        payload={"thread_status": thread.status},
    )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.CANCEL_PENDING,
        execution_readiness=RepairStatus.CANCEL_PENDING.value,
        last_requested_action=ControlActionType.CANCEL,
    )
    dispatch = DispatchRequest(action="cancel", thread_id=thread_id)
    logger.info(
        "Dispatching cancel dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
        },
    )
    try:
        await dispatch_to_worker(
            worker_client,
            dispatch,
            circuit_breaker,
            worker_spawner,
            bypass_circuit_breaker=True,
            trace_headers=trace_headers(),
        )
        dispatched = True
        mark_worker_connected(request)
    except (WorkerAtCapacityError, WorkerUnreachableError):
        pass

    if not dispatched:
        logger.warning(
            "Cancel dispatch failed for thread %s — leaving DB status unchanged",
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": dispatch.dispatch_id,
                "action": dispatch.action,
            },
        )
        action.result_status = ControlActionResultStatus.REJECTED_INVALID_STATE.value
        await db.commit()
        return CancelThreadResponse(
            thread_id=thread_id,
            status=thread.status,
            cancelled=False,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
        )

    await update_thread_status(db, thread_id, ThreadStatus.CANCELLING)
    await db.commit()

    return CancelThreadResponse(
        thread_id=thread_id,
        status=ThreadStatus.CANCELLING.value,
        cancelled=True,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
    )
