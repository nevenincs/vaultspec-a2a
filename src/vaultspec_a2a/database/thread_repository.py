"""Thread repository — lifecycle, repair, approval, execution state, metadata."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Select
    from sqlalchemy.sql.elements import ColumnElement

from ..thread.enums import (
    ACTIVE_STATUSES,
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
    feature_tag: str | None
    created_at: datetime


_MAX_DISCOVERY_WORKSPACE_ROOT_LENGTH = 4096
_MAX_DISCOVERY_FEATURE_TAG_LENGTH = 128


def _path_safe_run_id_clause() -> ColumnElement[bool]:
    """Return the cross-dialect persisted run-id grammar predicate."""
    return ThreadModel.id.regexp_match(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$")


def _discovery_selectors(metadata: str | None) -> tuple[str | None, str | None]:
    """Project bounded discovery selectors once at the metadata write seam."""
    if not metadata:
        return None, None
    try:
        value = json.loads(metadata)
    except (json.JSONDecodeError, RecursionError, TypeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    workspace = value.get("workspace_root")
    feature = value.get("feature_tag")
    if (
        not isinstance(workspace, str)
        or not os.path.isabs(workspace)
        or not 1 <= len(workspace) <= _MAX_DISCOVERY_WORKSPACE_ROOT_LENGTH
    ):
        workspace = None
    else:
        workspace = os.path.normcase(os.path.realpath(workspace))
    if (
        not isinstance(feature, str)
        or not 1 <= len(feature) <= _MAX_DISCOVERY_FEATURE_TAG_LENGTH
    ):
        feature = None
    return workspace, feature


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

    workspace_root, feature_tag = _discovery_selectors(metadata)
    thread = ThreadModel(
        id=thread_id or uuid4().hex,
        title=title,
        status=coerced_status.value,
        is_active=coerced_status in ACTIVE_STATUSES,
        repair_status=coerced_repair_status.value,
        repair_reason=repair_reason,
        execution_readiness=execution_readiness,
        thread_metadata=metadata,
        workspace_root=workspace_root,
        feature_tag=feature_tag,
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
    workspace_root: str | None = None,
    feature_tag: str | None = None,
    after_created_at: datetime | None = None,
    after_id: str | None = None,
) -> Sequence[ActiveThreadProjection]:
    """Return one narrow, keyset-paginated page of durable active threads."""
    if not 1 <= limit <= 101:
        msg = "active-thread page limit must be between 1 and 101"
        raise ValueError(msg)
    if workspace_root is not None and not 1 <= len(workspace_root) <= 4096:
        msg = "active-thread workspace selector must be between 1 and 4096 characters"
        raise ValueError(msg)
    if feature_tag is not None and not 1 <= len(feature_tag) <= 128:
        msg = "active-thread feature selector must be between 1 and 128 characters"
        raise ValueError(msg)
    if (after_created_at is None) != (after_id is None):
        msg = "active-thread keyset cursor requires both created_at and id"
        raise ValueError(msg)

    stmt = _active_thread_page_statement(
        limit=limit,
        workspace_root=workspace_root,
        feature_tag=feature_tag,
        after_created_at=after_created_at,
        after_id=after_id,
    )
    result = await session.execute(stmt)
    return [
        ActiveThreadProjection(
            id=row.id,
            status=row.status,
            feature_tag=row.feature_tag,
            created_at=row.created_at,
        )
        for row in result.all()
    ]


def _active_thread_page_statement(
    *,
    limit: int,
    workspace_root: str | None,
    feature_tag: str | None,
    after_created_at: datetime | None,
    after_id: str | None,
) -> Select[tuple[str, str, str | None, datetime]]:
    """Build the production discovery query for execution and plan inspection."""
    stmt = (
        select(
            ThreadModel.id,
            ThreadModel.status,
            ThreadModel.feature_tag,
            ThreadModel.created_at,
        )
        .where(
            ThreadModel.is_active.is_(True),
            ThreadModel.status.in_(sorted(status.value for status in ACTIVE_STATUSES)),
            # SQLAlchemy renders this portable operator as ``REGEXP`` on
            # SQLite (whose dialect installs a Python regexp function) and
            # ``~`` on PostgreSQL. Keep legacy invalid identifiers out of the
            # bounded page in the database, before LIMIT is applied.
            _path_safe_run_id_clause(),
        )
        .order_by(ThreadModel.created_at.desc(), ThreadModel.id.desc())
        .limit(limit)
    )
    if workspace_root is not None:
        stmt = stmt.where(ThreadModel.workspace_root == workspace_root)
    if feature_tag is not None:
        stmt = stmt.where(ThreadModel.feature_tag == feature_tag)
    if after_created_at is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                ThreadModel.created_at < after_created_at,
                and_(
                    ThreadModel.created_at == after_created_at,
                    ThreadModel.id < after_id,
                ),
            )
        )
    return stmt


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
        # Idempotent writes also repair a stale denormalized selector (for
        # example after an interrupted migration or legacy direct write).
        thread.is_active = coerced_status in ACTIVE_STATUSES
        thread.updated_at = _utcnow()
        await session.flush()
        return thread

    validate_transition(current, coerced_status, thread_id=thread_id)

    thread.status = coerced_status.value
    thread.is_active = coerced_status in ACTIVE_STATUSES
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
    workspace_root, feature_tag = _discovery_selectors(metadata)
    thread.thread_metadata = metadata
    thread.workspace_root = workspace_root
    thread.feature_tag = feature_tag
    thread.updated_at = _utcnow()
    await session.flush()
    return thread


async def get_thread_metadata(session: AsyncSession, thread_id: str) -> str | None:
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    return thread.thread_metadata
