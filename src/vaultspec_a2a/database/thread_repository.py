"""Thread repository — lifecycle, repair, approval, execution state, metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ApprovalStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
)
from ..thread.errors import NicknameConflictError
from ..thread.transitions import validate_transition
from ._helpers import (
    _UNSET,
    _coerce_approval_status,
    _coerce_control_action_type,
    _coerce_repair_status,
    _coerce_status,
    _UnsetType,
    _utcnow,
    save_model,
)
from .models import ThreadExecutionStateModel, ThreadModel

__all__ = [
    "ActiveThreadProjection",
    "create_thread",
    "delete_thread",
    "delete_thread_execution_state",
    "get_thread",
    "get_thread_execution_state",
    "get_thread_metadata",
    "list_active_thread_page",
    "list_non_terminal_threads",
    "list_threads",
    "record_thread_execution_state",
    "set_thread_approval_state",
    "set_thread_repair_state",
    "update_thread_metadata",
    "update_thread_status",
]


@dataclass(frozen=True, slots=True)
class ActiveThreadProjection:
    """Narrow durable fields needed by active-run discovery."""

    id: str
    status: str
    thread_metadata: str | None
    created_at: datetime


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


async def list_active_thread_page(
    session: AsyncSession,
    *,
    limit: int,
    metadata_prefix_length: int,
    after_created_at: datetime | None = None,
    after_id: str | None = None,
) -> Sequence[ActiveThreadProjection]:
    """Return one narrow, keyset-paginated page of durable active threads."""
    if not 1 <= limit <= 101:
        msg = "active-thread page limit must be between 1 and 101"
        raise ValueError(msg)
    if not 1 <= metadata_prefix_length <= 65_536:
        msg = "active-thread metadata prefix must be between 1 and 65536"
        raise ValueError(msg)
    if (after_created_at is None) != (after_id is None):
        msg = "active-thread keyset cursor requires both created_at and id"
        raise ValueError(msg)

    stmt = (
        select(
            ThreadModel.id,
            ThreadModel.status,
            func.substr(
                ThreadModel.thread_metadata,
                1,
                metadata_prefix_length,
            ).label("thread_metadata"),
            ThreadModel.created_at,
        )
        .where(
            ThreadModel.status.not_in(
                [thread_status.value for thread_status in NON_ACTIVE_STATUSES]
            )
        )
        .order_by(ThreadModel.created_at.desc(), ThreadModel.id.asc())
        .limit(limit)
    )
    if after_created_at is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                ThreadModel.created_at < after_created_at,
                and_(
                    ThreadModel.created_at == after_created_at,
                    ThreadModel.id > after_id,
                ),
            )
        )
    result = await session.execute(stmt)
    return [
        ActiveThreadProjection(
            id=row.id,
            status=row.status,
            thread_metadata=row.thread_metadata,
            created_at=row.created_at,
        )
        for row in result.all()
    ]


async def delete_thread(session: AsyncSession, thread_id: str) -> bool:
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return False
    await session.delete(thread)
    await session.flush()
    return True


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

    validate_transition(current, coerced_status, thread_id=thread_id)

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
            existing.recovery_epoch = thread.recovery_epoch
        existing.recorded_at = _utcnow()
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
