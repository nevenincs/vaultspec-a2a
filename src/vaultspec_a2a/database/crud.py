"""Async CRUD operations for durable orchestration state."""

# ruff: noqa: D103, PLR0913

from __future__ import annotations

import json

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import NicknameConflictError
from .models import (
    ArtifactModel,
    ControlActionModel,
    CostTrackingModel,
    PermissionLogModel,
    PermissionRequestModel,
    ThreadExecutionStateModel,
    ThreadModel,
)


class ThreadStatus(StrEnum):
    """Durable lifecycle states for orchestration threads."""

    SUBMITTED = "submitted"
    RUNNING = "running"
    INPUT_REQUIRED = "input_required"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
    REPAIR_NEEDED = "repair_needed"
    RECONCILING = "reconciling"


class RepairStatus(StrEnum):
    """Repair and readiness classification distinct from lifecycle."""

    HEALTHY = "healthy"
    PAUSED_RESUMABLE = "paused_resumable"
    CANCEL_PENDING = "cancel_pending"
    REPLAY_GAP = "replay_gap"
    CHECKPOINT_UNAVAILABLE = "checkpoint_unavailable"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    OPERATOR_INTERVENTION_REQUIRED = "operator_intervention_required"


class ControlActionType(StrEnum):
    """Durable journaled control action types."""

    INGEST = "ingest"
    RESUME = "resume"
    CANCEL = "cancel"
    PERMISSION_REQUEST_CREATED = "permission_request_created"
    PERMISSION_RESPONSE_SUBMITTED = "permission_response_submitted"
    PERMISSION_RESPONSE_APPLIED = "permission_response_applied"
    MESSAGE_FOLLOWUP_REQUESTED = "message_followup_requested"
    MESSAGE_FOLLOWUP_APPLIED = "message_followup_applied"
    REPAIR_STARTED = "repair_started"
    REPAIR_FINISHED = "repair_finished"


class ControlActionResultStatus(StrEnum):
    """Journaled outcome states for control actions."""

    ACCEPTED_NOT_APPLIED = "accepted_not_applied"
    APPLIED = "applied"
    REJECTED_INVALID_STATE = "rejected_invalid_state"
    SUPERSEDED = "superseded"
    DUPLICATE = "duplicate"


class PermissionRequestStatus(StrEnum):
    """Durable lifecycle for permission requests."""

    PENDING = "pending"
    ANSWERED_PENDING_APPLY = "answered_pending_apply"
    APPLIED = "applied"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED_BY_TERMINAL_STATE = "expired_by_terminal_state"


class ApprovalStatus(StrEnum):
    """Durable lifecycle for plan approval state on a thread."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


__all__ = [
    "ApprovalStatus",
    "ControlActionResultStatus",
    "ControlActionType",
    "InvalidTransitionError",
    "PermissionRequestStatus",
    "RepairStatus",
    "ThreadStatus",
    "append_cost_record",
    "append_permission_log",
    "create_artifact",
    "create_control_action",
    "create_thread",
    "delete_thread",
    "delete_thread_execution_state",
    "expire_pending_permission_requests",
    "get_artifact",
    "get_artifacts_by_thread",
    "get_control_action_by_idempotency_key",
    "get_latest_control_action",
    "get_pending_permission_requests",
    "get_permission_logs_by_thread",
    "get_permission_request",
    "get_thread",
    "get_thread_execution_state",
    "get_thread_metadata",
    "list_non_terminal_threads",
    "list_threads",
    "mark_control_action_applied",
    "mark_control_action_duplicate",
    "mark_control_action_superseded",
    "mark_permission_request_applied",
    "record_permission_request",
    "record_permission_response_submission",
    "record_thread_execution_state",
    "save_model",
    "set_thread_approval_state",
    "set_thread_repair_state",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
    "supersede_permission_requests",
    "update_thread_metadata",
    "update_thread_status",
]


async def save_model[
    M: (
        ThreadModel,
        ArtifactModel,
        PermissionLogModel,
        PermissionRequestModel,
        ControlActionModel,
        CostTrackingModel,
        ThreadExecutionStateModel,
    )
](session: AsyncSession, model: M) -> M:
    """Persist any database model instance."""
    session.add(model)
    await session.flush()
    return model


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _UnsetType:
    """Typed sentinel for distinguishing 'not provided' from ``None``."""

    _instance: _UnsetType | None = None

    def __new__(cls) -> _UnsetType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _UnsetType()


def _coerce_status(status: ThreadStatus | str) -> ThreadStatus:
    if isinstance(status, ThreadStatus):
        return status
    try:
        return ThreadStatus(status)
    except ValueError:
        valid = ", ".join(s.value for s in ThreadStatus)
        msg = f"Invalid thread status: {status!r}. Must be one of: {valid}"
        raise ValueError(msg) from None


def _coerce_repair_status(status: RepairStatus | str) -> RepairStatus:
    if isinstance(status, RepairStatus):
        return status
    try:
        return RepairStatus(status)
    except ValueError:
        valid = ", ".join(s.value for s in RepairStatus)
        msg = f"Invalid repair status: {status!r}. Must be one of: {valid}"
        raise ValueError(msg) from None


def _coerce_control_action_type(
    action_type: ControlActionType | str,
) -> ControlActionType:
    if isinstance(action_type, ControlActionType):
        return action_type
    return ControlActionType(action_type)


def _coerce_control_result(
    status: ControlActionResultStatus | str,
) -> ControlActionResultStatus:
    if isinstance(status, ControlActionResultStatus):
        return status
    return ControlActionResultStatus(status)


def _coerce_permission_request_status(
    status: PermissionRequestStatus | str,
) -> PermissionRequestStatus:
    if isinstance(status, PermissionRequestStatus):
        return status
    return PermissionRequestStatus(status)


def _coerce_approval_status(status: ApprovalStatus | str) -> ApprovalStatus:
    if isinstance(status, ApprovalStatus):
        return status
    return ApprovalStatus(status)


async def create_thread(
    session: AsyncSession,
    *,
    title: str | None = None,
    status: ThreadStatus | str = ThreadStatus.SUBMITTED,
    metadata: str | None = None,
    nickname: str | None = None,
    thread_id: str | None = None,
    team_preset: str | None = None,
    repair_status: RepairStatus | str = RepairStatus.HEALTHY,
    repair_reason: str | None = None,
    execution_readiness: str = "healthy",
) -> ThreadModel:
    """Create a new orchestration thread."""
    coerced_status = _coerce_status(status)
    coerced_repair_status = _coerce_repair_status(repair_status)

    if nickname is not None:
        existing = (
            await session.execute(
                select(ThreadModel).where(ThreadModel.nickname == nickname)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise NicknameConflictError(nickname)

    thread = ThreadModel(
        id=thread_id or uuid4().hex,
        title=title,
        status=coerced_status.value,
        repair_status=coerced_repair_status.value,
        repair_reason=repair_reason,
        execution_readiness=execution_readiness,
        thread_metadata=metadata,
        nickname=nickname,
        team_preset=team_preset,
    )
    try:
        return await save_model(session, thread)
    except IntegrityError as exc:
        if nickname is not None and "nickname" in str(exc).lower():
            raise NicknameConflictError(nickname) from exc
        raise


async def get_thread(session: AsyncSession, thread_id: str) -> ThreadModel | None:
    return await session.get(ThreadModel, thread_id)


async def list_threads(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 50,
    status: ThreadStatus | None = None,
) -> tuple[Sequence[ThreadModel], int]:
    count_stmt = select(func.count()).select_from(ThreadModel)
    if status is not None:
        count_stmt = count_stmt.where(ThreadModel.status == status.value)
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = (
        select(ThreadModel)
        .order_by(ThreadModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(ThreadModel.status == status.value)
    result = await session.execute(stmt)
    return result.scalars().all(), total


async def list_non_terminal_threads(session: AsyncSession) -> Sequence[ThreadModel]:
    """Return all threads that still require orchestration attention."""
    stmt = (
        select(ThreadModel)
        .where(
            ThreadModel.status.not_in(
                [
                    ThreadStatus.COMPLETED.value,
                    ThreadStatus.FAILED.value,
                    ThreadStatus.CANCELLED.value,
                    ThreadStatus.ARCHIVED.value,
                ]
            )
        )
        .order_by(ThreadModel.created_at.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def delete_thread(session: AsyncSession, thread_id: str) -> bool:
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return False
    await session.delete(thread)
    await session.flush()
    return True


class InvalidTransitionError(ValueError):
    """Raised when a thread status transition is not allowed."""


_VALID_TRANSITIONS: dict[ThreadStatus, frozenset[ThreadStatus]] = {
    ThreadStatus.SUBMITTED: frozenset(
        {
            ThreadStatus.RUNNING,
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.RUNNING: frozenset(
        {
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.INPUT_REQUIRED: frozenset(
        {
            ThreadStatus.RUNNING,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.CANCELLING: frozenset(
        {
            ThreadStatus.CANCELLED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.RECONCILING: frozenset(
        {
            ThreadStatus.SUBMITTED,
            ThreadStatus.RUNNING,
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.REPAIR_NEEDED: frozenset(
        {
            ThreadStatus.RECONCILING,
            ThreadStatus.RUNNING,
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.FAILED,
        }
    ),
    ThreadStatus.COMPLETED: frozenset({ThreadStatus.ARCHIVED}),
    ThreadStatus.FAILED: frozenset({ThreadStatus.ARCHIVED}),
    ThreadStatus.CANCELLED: frozenset({ThreadStatus.ARCHIVED}),
    ThreadStatus.ARCHIVED: frozenset(),
}


async def update_thread_status(
    session: AsyncSession,
    thread_id: str,
    status: ThreadStatus | str,
) -> ThreadModel | None:
    """Update a thread's status with transition validation."""
    coerced_status = _coerce_status(status)
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    current = _coerce_status(thread.status)
    if current == coerced_status:
        thread.updated_at = _utcnow()
        await session.flush()
        return thread

    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    if coerced_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition thread {thread_id} from "
            f"{current.value!r} to {coerced_status.value!r}"
        )

    thread.status = coerced_status.value
    thread.updated_at = _utcnow()
    await session.flush()
    return thread


async def set_thread_repair_state(
    session: AsyncSession,
    thread_id: str,
    *,
    repair_status: RepairStatus | str,
    repair_reason: str | None = None,
    execution_readiness: str | None = None,
    last_requested_action: ControlActionType | str | None = None,
    last_applied_action: ControlActionType | str | None = None,
    increment_generation: bool = False,
    increment_recovery_epoch: bool = False,
) -> ThreadModel | None:
    """Persist thread repair metadata used by restart reconciliation."""
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    thread.repair_status = _coerce_repair_status(repair_status).value
    thread.repair_reason = repair_reason
    if execution_readiness is not None:
        thread.execution_readiness = execution_readiness
    if last_requested_action is not None:
        thread.last_requested_action = _coerce_control_action_type(
            last_requested_action
        ).value
    if last_applied_action is not None:
        thread.last_applied_action = _coerce_control_action_type(
            last_applied_action
        ).value
    if increment_generation:
        thread.repair_generation += 1
    if increment_recovery_epoch:
        thread.recovery_epoch += 1
    thread.updated_at = _utcnow()
    await session.flush()
    return thread


async def set_thread_approval_state(
    session: AsyncSession,
    thread_id: str,
    *,
    approval_status: ApprovalStatus | str | None | _UnsetType = _UNSET,
    approval_request_id: str | None | _UnsetType = _UNSET,
    approval_reason: str | None | _UnsetType = _UNSET,
    approval_response_action_id: str | None | _UnsetType = _UNSET,
    approval_updated_at: datetime | None = None,
) -> ThreadModel | None:
    """Persist durable plan-approval state on the thread row."""
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    if not isinstance(approval_status, _UnsetType):
        thread.approval_status = (
            _coerce_approval_status(approval_status).value
            if approval_status is not None
            else None
        )
    if not isinstance(approval_request_id, _UnsetType):
        thread.approval_request_id = approval_request_id
    if not isinstance(approval_reason, _UnsetType):
        thread.approval_reason = approval_reason
    if not isinstance(approval_response_action_id, _UnsetType):
        thread.approval_response_action_id = approval_response_action_id
    thread.approval_updated_at = approval_updated_at or _utcnow()
    await session.flush()
    return thread


async def record_thread_execution_state(
    session: AsyncSession,
    *,
    thread_id: str,
    checkpoint_id: str | None,
    parent_checkpoint_id: str | None,
    snapshot_created_at: datetime | None,
    task_count: int,
    interrupt_count: int,
    next_nodes: list[str],
    interrupt_types: list[str],
    tasks: list[dict[str, object]],
    degraded_reasons: list[str],
) -> ThreadExecutionStateModel | None:
    """Create or refresh the latest execution-state projection for a thread."""
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    existing = await session.get(ThreadExecutionStateModel, thread_id)
    degraded_only = (
        checkpoint_id is None
        and parent_checkpoint_id is None
        and snapshot_created_at is None
        and task_count == 0
        and interrupt_count == 0
        and not next_nodes
        and not interrupt_types
        and not tasks
        and bool(degraded_reasons)
    )
    next_nodes_json = json.dumps(next_nodes)
    interrupt_types_json = json.dumps(interrupt_types)
    tasks_json = json.dumps(tasks)
    degraded_reasons_json = json.dumps(degraded_reasons)

    if existing is not None:
        if not degraded_only:
            existing.checkpoint_id = checkpoint_id
            existing.parent_checkpoint_id = parent_checkpoint_id
            existing.snapshot_created_at = snapshot_created_at
            existing.task_count = task_count
            existing.interrupt_count = interrupt_count
            existing.next_nodes_json = next_nodes_json
            existing.interrupt_types_json = interrupt_types_json
            existing.tasks_json = tasks_json
        existing.recorded_at = _utcnow()
        existing.recovery_epoch = thread.recovery_epoch
        existing.degraded_reasons_json = degraded_reasons_json
        await session.flush()
        return existing

    model = ThreadExecutionStateModel(
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        snapshot_created_at=snapshot_created_at,
        recorded_at=_utcnow(),
        recovery_epoch=thread.recovery_epoch,
        task_count=task_count,
        interrupt_count=interrupt_count,
        next_nodes_json=next_nodes_json,
        interrupt_types_json=interrupt_types_json,
        tasks_json=tasks_json,
        degraded_reasons_json=degraded_reasons_json,
    )
    return await save_model(session, model)


async def get_thread_execution_state(
    session: AsyncSession,
    thread_id: str,
) -> ThreadExecutionStateModel | None:
    """Return the latest execution-state projection for a thread."""
    return await session.get(ThreadExecutionStateModel, thread_id)


async def delete_thread_execution_state(
    session: AsyncSession,
    thread_id: str,
) -> bool:
    """Delete the latest execution-state projection for a thread."""
    model = await session.get(ThreadExecutionStateModel, thread_id)
    if model is None:
        return False
    await session.delete(model)
    await session.flush()
    return True


async def update_thread_metadata(
    session: AsyncSession,
    thread_id: str,
    metadata: str | None,
) -> ThreadModel | None:
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    thread.thread_metadata = metadata
    thread.updated_at = _utcnow()
    await session.flush()
    return thread


async def get_thread_metadata(session: AsyncSession, thread_id: str) -> str | None:
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    return thread.thread_metadata


async def create_control_action(
    session: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str,
    idempotency_key: str,
    request_id: str | None = None,
    payload: dict[str, object] | None = None,
    worker_generation: int = 0,
    result_status: ControlActionResultStatus | str = (
        ControlActionResultStatus.ACCEPTED_NOT_APPLIED
    ),
) -> ControlActionModel:
    """Append a durable control journal record."""
    model = ControlActionModel(
        id=uuid4().hex,
        thread_id=thread_id,
        action_type=_coerce_control_action_type(action_type).value,
        request_id=request_id,
        idempotency_key=idempotency_key,
        payload_json=json.dumps(payload) if payload is not None else None,
        worker_generation=worker_generation,
        result_status=_coerce_control_result(result_status).value,
    )
    return await save_model(session, model)


async def get_control_action_by_idempotency_key(
    session: AsyncSession,
    *,
    thread_id: str,
    idempotency_key: str,
) -> ControlActionModel | None:
    stmt = select(ControlActionModel).where(
        ControlActionModel.thread_id == thread_id,
        ControlActionModel.idempotency_key == idempotency_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_control_action(
    session: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str | None = None,
) -> ControlActionModel | None:
    stmt = (
        select(ControlActionModel)
        .where(ControlActionModel.thread_id == thread_id)
        .order_by(ControlActionModel.requested_at.desc())
    )
    if action_type is not None:
        stmt = stmt.where(
            ControlActionModel.action_type
            == _coerce_control_action_type(action_type).value
        )
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def mark_control_action_applied(
    session: AsyncSession,
    action_id: str,
    *,
    applied_at: datetime | None = None,
    result_status: ControlActionResultStatus | str = ControlActionResultStatus.APPLIED,
) -> ControlActionModel | None:
    action = await session.get(ControlActionModel, action_id)
    if action is None:
        return None
    action.applied_at = applied_at or _utcnow()
    action.result_status = _coerce_control_result(result_status).value
    await session.flush()
    return action


async def mark_control_action_duplicate(
    session: AsyncSession,
    action_id: str,
) -> ControlActionModel | None:
    action = await session.get(ControlActionModel, action_id)
    if action is None:
        return None
    action.result_status = ControlActionResultStatus.DUPLICATE.value
    await session.flush()
    return action


async def mark_control_action_superseded(
    session: AsyncSession,
    action_id: str,
) -> ControlActionModel | None:
    action = await session.get(ControlActionModel, action_id)
    if action is None:
        return None
    action.result_status = ControlActionResultStatus.SUPERSEDED.value
    action.superseded_at = _utcnow()
    await session.flush()
    return action


async def record_permission_request(
    session: AsyncSession,
    *,
    request_id: str,
    thread_id: str,
    pause_reason_type: str,
    description: str,
    allowed_options: list[dict[str, object]],
    tool_call: str | None = None,
    worker_generation: int = 0,
) -> PermissionRequestModel:
    """Create or refresh a durable permission request."""
    existing = await session.get(PermissionRequestModel, request_id)
    allowed_options_json = json.dumps(allowed_options)
    if existing is not None:
        existing.pause_reason_type = pause_reason_type
        existing.description = description
        existing.allowed_options_json = allowed_options_json
        existing.tool_call = tool_call
        existing.worker_generation = worker_generation
        existing.request_status = PermissionRequestStatus.PENDING.value
        existing.response_option_id = None
        existing.idempotency_key = None
        existing.responded_at = None
        existing.applied_at = None
        await session.flush()
        return existing

    model = PermissionRequestModel(
        request_id=request_id,
        thread_id=thread_id,
        pause_reason_type=pause_reason_type,
        tool_call=tool_call,
        description=description,
        allowed_options_json=allowed_options_json,
        request_status=PermissionRequestStatus.PENDING.value,
        worker_generation=worker_generation,
    )
    return await save_model(session, model)


async def get_permission_request(
    session: AsyncSession, request_id: str
) -> PermissionRequestModel | None:
    return await session.get(PermissionRequestModel, request_id)


async def get_pending_permission_requests(
    session: AsyncSession,
    *,
    thread_id: str | None = None,
) -> Sequence[PermissionRequestModel]:
    stmt = select(PermissionRequestModel).where(
        PermissionRequestModel.request_status.in_(
            [
                PermissionRequestStatus.PENDING.value,
                PermissionRequestStatus.ANSWERED_PENDING_APPLY.value,
            ]
        )
    )
    if thread_id is not None:
        stmt = stmt.where(PermissionRequestModel.thread_id == thread_id)
    stmt = stmt.order_by(PermissionRequestModel.created_at.asc())
    return (await session.execute(stmt)).scalars().all()


async def supersede_permission_requests(
    session: AsyncSession,
    *,
    thread_id: str,
    pause_reason_type: str | None = None,
    except_request_id: str | None = None,
) -> int:
    """Mark earlier pending permission requests as superseded."""
    stmt = select(PermissionRequestModel).where(
        PermissionRequestModel.thread_id == thread_id,
        PermissionRequestModel.request_status.in_(
            [
                PermissionRequestStatus.PENDING.value,
                PermissionRequestStatus.ANSWERED_PENDING_APPLY.value,
            ]
        ),
    )
    if pause_reason_type is not None:
        stmt = stmt.where(PermissionRequestModel.pause_reason_type == pause_reason_type)
    permissions = (await session.execute(stmt)).scalars().all()
    updated = 0
    for permission in permissions:
        if permission.request_id == except_request_id:
            continue
        permission.request_status = PermissionRequestStatus.SUPERSEDED.value
        permission.applied_at = permission.applied_at or _utcnow()
        updated += 1
    await session.flush()
    return updated


async def record_permission_response_submission(
    session: AsyncSession,
    *,
    request_id: str,
    option_id: str,
    idempotency_key: str,
) -> PermissionRequestModel | None:
    permission = await session.get(PermissionRequestModel, request_id)
    if permission is None:
        return None
    permission.response_option_id = option_id
    permission.idempotency_key = idempotency_key
    permission.request_status = PermissionRequestStatus.ANSWERED_PENDING_APPLY.value
    permission.responded_at = _utcnow()
    await session.flush()
    return permission


async def mark_permission_request_applied(
    session: AsyncSession,
    *,
    request_id: str,
    status: PermissionRequestStatus | str = PermissionRequestStatus.APPLIED,
) -> PermissionRequestModel | None:
    permission = await session.get(PermissionRequestModel, request_id)
    if permission is None:
        return None
    permission.request_status = _coerce_permission_request_status(status).value
    permission.applied_at = _utcnow()
    await session.flush()
    return permission


async def expire_pending_permission_requests(
    session: AsyncSession,
    *,
    thread_id: str,
) -> int:
    stmt = select(PermissionRequestModel).where(
        PermissionRequestModel.thread_id == thread_id,
        PermissionRequestModel.request_status.in_(
            [
                PermissionRequestStatus.PENDING.value,
                PermissionRequestStatus.ANSWERED_PENDING_APPLY.value,
            ]
        ),
    )
    permissions = (await session.execute(stmt)).scalars().all()
    for permission in permissions:
        permission.request_status = (
            PermissionRequestStatus.EXPIRED_BY_TERMINAL_STATE.value
        )
        permission.applied_at = permission.applied_at or _utcnow()
    await session.flush()
    return len(permissions)


async def create_artifact(
    session: AsyncSession,
    *,
    thread_id: str,
    artifact_type: str,
    path: str,
    artifact_id: str | None = None,
) -> ArtifactModel:
    artifact = ArtifactModel(
        id=artifact_id or uuid4().hex,
        thread_id=thread_id,
        type=artifact_type,
        path=path,
    )
    return await save_model(session, artifact)


async def get_artifact(session: AsyncSession, artifact_id: str) -> ArtifactModel | None:
    return await session.get(ArtifactModel, artifact_id)


async def get_artifacts_by_thread(
    session: AsyncSession, thread_id: str
) -> Sequence[ArtifactModel]:
    stmt = (
        select(ArtifactModel)
        .where(ArtifactModel.thread_id == thread_id)
        .order_by(ArtifactModel.created_at)
    )
    return (await session.execute(stmt)).scalars().all()


async def append_permission_log(
    session: AsyncSession,
    *,
    thread_id: str,
    agent_id: str,
    tool_name: str,
    action: str,
) -> PermissionLogModel:
    log_entry = PermissionLogModel(
        id=uuid4().hex,
        thread_id=thread_id,
        agent_id=agent_id,
        tool_name=tool_name,
        action=action,
    )
    return await save_model(session, log_entry)


async def get_permission_logs_by_thread(
    session: AsyncSession, thread_id: str
) -> Sequence[PermissionLogModel]:
    stmt = (
        select(PermissionLogModel)
        .where(PermissionLogModel.thread_id == thread_id)
        .order_by(PermissionLogModel.responded_at)
    )
    return (await session.execute(stmt)).scalars().all()


async def append_cost_record(
    session: AsyncSession, record: CostTrackingModel
) -> CostTrackingModel:
    return await save_model(session, record)


async def sum_cost_by_thread(
    session: AsyncSession, thread_id: str
) -> dict[str, int | float]:
    stmt = select(
        func.coalesce(func.sum(CostTrackingModel.input_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.output_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.estimated_cost), 0.0),
    ).where(CostTrackingModel.thread_id == thread_id)
    row = (await session.execute(stmt)).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
        "estimated_cost": row[2],
    }


async def sum_cost_by_agent(
    session: AsyncSession, agent_id: str
) -> dict[str, int | float]:
    stmt = select(
        func.coalesce(func.sum(CostTrackingModel.input_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.output_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.estimated_cost), 0.0),
    ).where(CostTrackingModel.agent_id == agent_id)
    row = (await session.execute(stmt)).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
        "estimated_cost": row[2],
    }
