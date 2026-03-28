"""Permission repository — permission request lifecycle and control action journal."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
)
from ._helpers import (
    _coerce_control_action_type,
    _coerce_control_result,
    _coerce_permission_request_status,
    _utcnow,
    save_model,
)
from .models import ControlActionModel, PermissionRequestModel

__all__ = [
    "create_control_action",
    "expire_pending_permission_requests",
    "get_control_action_by_idempotency_key",
    "get_latest_control_action",
    "get_pending_permission_requests",
    "get_permission_request",
    "mark_control_action_applied",
    "mark_control_action_duplicate",
    "mark_control_action_superseded",
    "mark_permission_request_applied",
    "record_permission_request",
    "record_permission_response_submission",
    "supersede_permission_requests",
]


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
