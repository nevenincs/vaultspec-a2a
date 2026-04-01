"""Named repair-state transition functions for route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import set_thread_repair_state
from ..thread.enums import ControlActionType, RepairStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import ThreadModel


async def mark_ingest_requested(db: AsyncSession, thread_id: str) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_requested_action=ControlActionType.INGEST,
    )


async def mark_ingest_applied(db: AsyncSession, thread_id: str) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_applied_action=ControlActionType.INGEST,
    )


async def mark_permission_response_requested(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.PAUSED_RESUMABLE,
        execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
        last_requested_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
    )


async def mark_permission_response_applied(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_applied_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
    )


async def mark_message_followup_requested(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_requested_action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
    )


async def mark_message_followup_applied(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
        last_applied_action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
    )


async def mark_cancel_requested(db: AsyncSession, thread_id: str) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.CANCEL_PENDING,
        execution_readiness=RepairStatus.CANCEL_PENDING.value,
        last_requested_action=ControlActionType.CANCEL,
    )
