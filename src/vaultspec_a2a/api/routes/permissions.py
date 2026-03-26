"""POST /permissions/{request_id}/respond -- Permission response (REST)."""

import hashlib
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.dispatch import (
    WorkerAtCapacityError,
    WorkerCircuitOpenError,
    WorkerDispatchRejectedError,
    WorkerUnreachableError,
    dispatch_to_worker,
)
from ...database.crud import (
    ApprovalStatus,
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
    create_control_action,
    get_control_action_by_idempotency_key,
    get_permission_request,
    get_thread,
    record_permission_response_submission,
    set_thread_approval_state,
    set_thread_repair_state,
    update_thread_status,
)
from ...database.session import get_db
from ...ipc.schemas import DispatchRequest
from ...streaming.aggregator import EventAggregator
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import (
    get_aggregator,
    get_circuit_breaker,
    get_worker_client,
    get_worker_spawner,
)
from ..schemas.enums import PermissionType
from ..schemas.rest import PermissionResponseRequest, PermissionResponseResult

router = APIRouter()
logger = logging.getLogger(__name__)

_PLAN_APPROVAL_PAUSE_CAUSES = {
    PermissionType.PLAN_APPROVAL.value,
    "plan_approval_request",
}


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
    logger.info(
        "Permission response: request_id=%s, option_id=%s",
        request_id,
        body.option_id,
        extra={
            "request_id": request_id,
            "thread_id": (request_id.split(":", 1)[0] if ":" in request_id else None),
            "action": "permission_response",
            "option_id": body.option_id,
        },
    )

    permission = await get_permission_request(db, request_id)
    thread_id = permission.thread_id if permission is not None else ""
    if not thread_id and ":" in request_id:
        thread_id, _ = request_id.split(":", 1)
    if not thread_id:
        return PermissionResponseResult(
            request_id=request_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            thread_id="",
        )

    thread_record = await get_thread(db, thread_id)
    if thread_record is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    if permission is None:
        raise HTTPException(
            status_code=409,
            detail="Permission request is not durably pending",
        )

    resolved_idempotency_key = (
        idempotency_key
        or hashlib.sha256(f"{request_id}:{body.option_id}".encode()).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        return PermissionResponseResult(
            request_id=request_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            thread_id=thread_id,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    if permission.request_status == PermissionRequestStatus.APPLIED.value:
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload={"option_id": body.option_id},
            result_status=ControlActionResultStatus.DUPLICATE,
        )
        await db.commit()
        return PermissionResponseResult(
            request_id=request_id,
            accepted=True,
            applied=True,
            action_status=ControlActionResultStatus.DUPLICATE.value,
            thread_id=thread_id,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    if permission.request_status != PermissionRequestStatus.PENDING.value:
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload={"option_id": body.option_id},
            result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        )
        await db.commit()
        return PermissionResponseResult(
            request_id=request_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            thread_id=thread_id,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    permission_terminal_statuses = {
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
    }
    if thread_record.status in permission_terminal_statuses:
        logger.warning(
            "Permission respond rejected: thread %s is no longer active (status=%r)",
            thread_id,
            thread_record.status,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
                "thread_status": thread_record.status,
            },
        )
        raise HTTPException(
            status_code=409,
            detail="thread is no longer active",
        )

    team_preset: str | None = thread_record.team_preset
    workspace_root: str | None = None
    if thread_record.thread_metadata:
        try:
            meta = json.loads(thread_record.thread_metadata)
            workspace_root = meta.get("workspace_root")
        except (json.JSONDecodeError, AttributeError):
            pass

    resume_value: str | dict[str, bool] = body.option_id
    if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
        resume_value = {"approved": body.option_id == "approve"}

    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        request_id=request_id,
        idempotency_key=resolved_idempotency_key,
        payload={"option_id": body.option_id},
    )
    await record_permission_response_submission(
        db,
        request_id=request_id,
        option_id=body.option_id,
        idempotency_key=resolved_idempotency_key,
    )
    if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=ApprovalStatus.PENDING,
            approval_request_id=request_id,
            approval_reason=permission.description,
            approval_response_action_id=action.id,
        )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.PAUSED_RESUMABLE,
        execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
        last_requested_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
    )

    dispatch = DispatchRequest(
        action="resume",
        thread_id=thread_id,
        option_id=resume_value,
        team_preset=team_preset,
        workspace_root=workspace_root,
    )

    logger.info(
        "Dispatching resume dispatch_id=%s for thread %s (request_id=%s)",
        dispatch.dispatch_id,
        thread_id,
        request_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "request_id": request_id,
            "action": dispatch.action,
            "option_id": body.option_id,
        },
    )
    dispatched = False
    try:
        await dispatch_to_worker(
            worker_client,
            dispatch,
            circuit_breaker,
            worker_spawner,
            trace_headers=trace_headers(),
        )
        dispatched = True
        mark_worker_connected(request)
    except WorkerCircuitOpenError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    except (WorkerAtCapacityError, WorkerDispatchRejectedError, WorkerUnreachableError):
        pass

    if dispatched:
        aggregator.resolve_permission(request_id)
        await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
        await set_thread_repair_state(
            db,
            thread_id,
            repair_status=RepairStatus.HEALTHY,
            execution_readiness=RepairStatus.HEALTHY.value,
            last_requested_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        )
        await db.commit()
        return PermissionResponseResult(
            request_id=request_id,
            accepted=True,
            applied=False,
            action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
            thread_id=thread_id,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=(
                ApprovalStatus.PENDING.value
                if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES
                else thread_record.approval_status
            ),
        )

    action.result_status = ControlActionResultStatus.REJECTED_INVALID_STATE.value
    await db.commit()
    return PermissionResponseResult(
        request_id=request_id,
        accepted=False,
        applied=False,
        action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        thread_id=thread_id,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
        approval_status=thread_record.approval_status,
    )
