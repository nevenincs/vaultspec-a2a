"""Permission response orchestration service.

Extracts the state-machine logic from the REST route handler into a
protocol-agnostic service function.  Does NOT commit the session, raise
``HTTPException``, or import from ``api/``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database import (
    create_control_action,
    get_control_action_by_idempotency_key,
    get_pending_permission_requests,
    get_permission_request,
    get_thread,
    record_permission_response_submission,
    reset_permission_response_submission,
    set_thread_approval_state,
    update_thread_status,
)
from ..ipc.schemas import DispatchRequest
from ..thread.dispatch_policy import FailureType, classify_dispatch_failure
from ..thread.enums import (
    TERMINAL_STATUSES,
    ApprovalStatus,
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
    ThreadStatus,
)
from ..thread.snapshots import PLAN_APPROVAL_PAUSE_CAUSES
from .dispatch import safe_dispatch
from .repair_transitions import (
    mark_dispatch_failed,
    mark_permission_response_applied,
    mark_permission_response_requested,
)

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..streaming.aggregator import EventAggregator
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "PermissionResult",
    "respond_to_permission",
]

logger = logging.getLogger(__name__)


def _allowed_option_ids(permission: object) -> set[str]:
    """Extract valid option ids from a durable permission request row."""
    raw_options = getattr(permission, "allowed_options_json", "[]")
    try:
        parsed = json.loads(raw_options)
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(parsed, list):
        return set()

    valid_ids: set[str] = set()
    for option in parsed:
        if not isinstance(option, dict):
            continue
        for key in ("option_id", "optionId"):
            value = option.get(key)
            if isinstance(value, str) and value:
                valid_ids.add(value)
    return valid_ids


def _rejected_permission_error(
    *,
    permission_status: str | None,
    thread_terminal: bool,
    option_id: str,
    valid_option_ids: set[str],
) -> tuple[str, int]:
    """Return the protocol-facing error for a rejected permission response."""
    if thread_terminal:
        return ("thread is no longer active", 409)
    if permission_status and permission_status != PermissionRequestStatus.PENDING.value:
        return ("Permission request is no longer pending", 409)
    if not valid_option_ids:
        return ("Permission request has no valid options", 409)
    if option_id not in valid_option_ids:
        return ("Unknown permission option for this request", 409)
    return ("Permission response was previously rejected", 409)


def _rejected_payload(option_id: str, error_detail: str) -> dict[str, object]:
    """Persist the original rejection reason for idempotent replay."""
    return {"option_id": option_id, "error_detail": error_detail}


def _existing_rejection_error(existing_action: object) -> str | None:
    """Read the original rejection reason from a stored control action."""
    raw_payload = getattr(existing_action, "payload_json", None)
    if not isinstance(raw_payload, str) or not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    error_detail = payload.get("error_detail")
    return error_detail if isinstance(error_detail, str) and error_detail else None


@dataclass(frozen=True, slots=True)
class PermissionResult:
    """Outcome of a permission response operation.

    The route handler translates this into an HTTP response or exception.
    """

    request_id: str
    thread_id: str
    accepted: bool
    applied: bool
    action_status: str
    action_id: str | None = None
    idempotency_key: str | None = None
    approval_status: str | None = None
    dispatched: bool = False
    # Error signalling — the route maps these to HTTPException codes.
    error_detail: str | None = None
    error_status_code: int | None = None
    circuit_open: bool = False
    failure_type: FailureType | None = None


async def respond_to_permission(
    db: AsyncSession,
    *,
    request_id: str,
    option_id: str,
    idempotency_key: str | None,
    aggregator: EventAggregator,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> PermissionResult:
    """Execute the permission-response state machine.

    Returns a :class:`PermissionResult` describing the outcome.  Commits the
    session before returning — the service owns its transaction boundary.
    The caller translates errors into protocol-specific responses.
    """
    logger.info(
        "Permission response: request_id=%s, option_id=%s",
        request_id,
        option_id,
        extra={
            "request_id": request_id,
            "thread_id": (request_id.split(":", 1)[0] if ":" in request_id else None),
            "action": "permission_response",
            "option_id": option_id,
        },
    )

    # ------------------------------------------------------------------
    # 1. Resolve permission request and thread
    # ------------------------------------------------------------------
    permission = await get_permission_request(db, request_id)
    thread_id = permission.thread_id if permission is not None else ""
    if not thread_id and ":" in request_id:
        thread_id, _ = request_id.split(":", 1)
    if not thread_id:
        return PermissionResult(
            request_id=request_id,
            thread_id="",
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
        )

    thread_record = await get_thread(db, thread_id)
    if thread_record is None:
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Thread not found",
            error_status_code=404,
        )
    if permission is None:
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="Permission request is not durably pending",
            error_status_code=409,
        )

    # ------------------------------------------------------------------
    # 2. Idempotency deduplication
    # ------------------------------------------------------------------
    resolved_idempotency_key = (
        idempotency_key
        or hashlib.sha256(f"{request_id}:{option_id}".encode()).hexdigest()
    )
    existing_action = await get_control_action_by_idempotency_key(
        db, thread_id=thread_id, idempotency_key=resolved_idempotency_key
    )
    if existing_action is not None:
        if (
            existing_action.result_status
            == ControlActionResultStatus.REJECTED_INVALID_STATE.value
        ):
            stored_error_detail = _existing_rejection_error(existing_action)
            valid_option_ids = _allowed_option_ids(permission) if permission else set()
            error_detail, error_status_code = _rejected_permission_error(
                permission_status=(
                    permission.request_status if permission is not None else None
                ),
                thread_terminal=thread_record.status in TERMINAL_STATUSES,
                option_id=option_id,
                valid_option_ids=valid_option_ids,
            )
            return PermissionResult(
                request_id=request_id,
                thread_id=thread_id,
                accepted=False,
                applied=False,
                action_status=existing_action.result_status,
                action_id=existing_action.id,
                idempotency_key=resolved_idempotency_key,
                approval_status=thread_record.approval_status,
                error_detail=stored_error_detail or error_detail,
                error_status_code=error_status_code,
            )
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=True,
            applied=existing_action.applied_at is not None,
            action_status=existing_action.result_status,
            action_id=existing_action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    # ------------------------------------------------------------------
    # 3. Permission status checks
    # ------------------------------------------------------------------
    if permission.request_status == PermissionRequestStatus.APPLIED.value:
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload={"option_id": option_id},
            result_status=ControlActionResultStatus.DUPLICATE,
        )
        await db.commit()
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=True,
            applied=True,
            action_status=ControlActionResultStatus.DUPLICATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
        )

    if permission.request_status != PermissionRequestStatus.PENDING.value:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=permission.request_status,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=_allowed_option_ids(permission),
        )
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload=_rejected_payload(option_id, error_detail),
            result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        )
        await db.commit()
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
            error_detail=error_detail,
            error_status_code=error_status_code,
        )

    # ------------------------------------------------------------------
    # 4. Thread terminal status guard
    # ------------------------------------------------------------------
    if thread_record.status in TERMINAL_STATUSES:
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
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            error_detail="thread is no longer active",
            error_status_code=409,
        )

    active_request_id: str | None = None
    pending_permissions = await get_pending_permission_requests(db, thread_id=thread_id)
    if permission.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES:
        active_plan_permissions = [
            pending.request_id
            for pending in pending_permissions
            if pending.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES
        ]
        active_request_id = (
            active_plan_permissions[-1]
            if active_plan_permissions
            else thread_record.approval_request_id or request_id
        )
    elif pending_permissions:
        active_request_id = pending_permissions[-1].request_id

    if active_request_id is not None and active_request_id != request_id:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=PermissionRequestStatus.SUPERSEDED.value,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=_allowed_option_ids(permission),
        )
        logger.warning(
            "Permission respond rejected: request %s is not the active "
            "interrupt for thread %s (active=%s)",
            request_id,
            thread_id,
            active_request_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "active_request_id": active_request_id,
                "action": "permission_response",
            },
        )
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload=_rejected_payload(option_id, error_detail),
            result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        )
        await db.commit()
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
            error_detail=error_detail,
            error_status_code=error_status_code,
        )

    valid_option_ids = _allowed_option_ids(permission)
    if not valid_option_ids:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=permission.request_status,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=set(),
        )
        logger.warning(
            "Permission respond rejected: request %s has no valid durable options",
            request_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
            },
        )
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload=_rejected_payload(option_id, error_detail),
            result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        )
        await db.commit()
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
            error_detail=error_detail,
            error_status_code=error_status_code,
        )

    if option_id not in valid_option_ids:
        error_detail, error_status_code = _rejected_permission_error(
            permission_status=permission.request_status,
            thread_terminal=False,
            option_id=option_id,
            valid_option_ids=valid_option_ids,
        )
        logger.warning(
            "Permission respond rejected: request %s received unknown option_id=%r",
            request_id,
            option_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_response",
                "option_id": option_id,
                "valid_option_ids": sorted(valid_option_ids),
            },
        )
        action = await create_control_action(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=resolved_idempotency_key,
            payload=_rejected_payload(option_id, error_detail),
            result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        )
        await db.commit()
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
            error_detail=error_detail,
            error_status_code=error_status_code,
        )

    # ------------------------------------------------------------------
    # 5. Build resume value and create control action
    # ------------------------------------------------------------------
    team_preset: str | None = thread_record.team_preset
    workspace_root: str | None = None
    if thread_record.thread_metadata:
        try:
            meta = json.loads(thread_record.thread_metadata)
            workspace_root = meta.get("workspace_root")
        except (json.JSONDecodeError, AttributeError):
            pass

    resume_value: str | dict[str, bool] = option_id
    if permission.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES:
        resume_value = {"approved": option_id == "approve"}

    action = await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        request_id=request_id,
        idempotency_key=resolved_idempotency_key,
        payload={"option_id": option_id},
    )
    await record_permission_response_submission(
        db,
        request_id=request_id,
        option_id=option_id,
        idempotency_key=resolved_idempotency_key,
    )
    if permission.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES:
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=ApprovalStatus.PENDING,
            approval_request_id=request_id,
            approval_reason=permission.description,
            approval_response_action_id=action.id,
        )
    await mark_permission_response_requested(db, thread_id)

    # ------------------------------------------------------------------
    # 6. Dispatch resume to worker
    # ------------------------------------------------------------------
    dispatch = DispatchRequest(
        action=ControlActionType.RESUME,  # ty: ignore[invalid-argument-type]
        thread_id=thread_id,
        option_id=resume_value,
        team_preset=team_preset,
        workspace_root=workspace_root,
        recursion_limit=recursion_limit,
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
            "option_id": option_id,
        },
    )

    outcome = await safe_dispatch(
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        trace_headers=trace_headers,
    )

    if not outcome.success:
        await reset_permission_response_submission(db, request_id=request_id)
        action.idempotency_key = (
            f"{resolved_idempotency_key}:dispatch-failed:{action.id}"
        )
        policy = classify_dispatch_failure(outcome.failure_type)
        typed_failure = (
            FailureType(outcome.failure_type) if outcome.failure_type else None
        )
        if policy.should_mark_failed:
            await update_thread_status(db, thread_id, ThreadStatus.INPUT_REQUIRED)
            await mark_dispatch_failed(db, thread_id)
        else:
            action.result_status = (
                ControlActionResultStatus.REJECTED_INVALID_STATE.value
            )

        error_detail: str | None = outcome.detail or "Worker dispatch failed"
        error_status_code: int | None = None
        if policy.is_circuit_open:
            error_detail = outcome.detail or "Circuit breaker open"
            error_status_code = 503
        elif policy.should_mark_failed:
            exc = outcome.exception
            http_code = getattr(exc, "status_code", 0)
            if http_code:
                error_detail = f"Worker dispatch failed (HTTP {http_code})"
            error_status_code = 502

        await db.commit()
        return PermissionResult(
            request_id=request_id,
            thread_id=thread_id,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            action_id=action.id,
            idempotency_key=resolved_idempotency_key,
            approval_status=thread_record.approval_status,
            circuit_open=policy.is_circuit_open,
            error_detail=error_detail,
            error_status_code=error_status_code,
            failure_type=typed_failure,
        )

    # ------------------------------------------------------------------
    # 7. Success path
    # ------------------------------------------------------------------
    aggregator.resolve_permission(request_id)
    await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
    await mark_permission_response_applied(db, thread_id)
    await db.commit()

    return PermissionResult(
        request_id=request_id,
        thread_id=thread_id,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        action_id=action.id,
        idempotency_key=resolved_idempotency_key,
        approval_status=(
            ApprovalStatus.PENDING.value
            if permission.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES
            else thread_record.approval_status
        ),
        dispatched=True,
    )
