"""Named repair-state transition functions for route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import set_thread_repair_state
from ..thread.enums import ControlActionType, RepairStatus
from ..thread.repair_policy import repair_state_for_action

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import ThreadModel


async def mark_ingest_requested(db: AsyncSession, thread_id: str) -> ThreadModel | None:
    transition = repair_state_for_action(ControlActionType.INGEST, "requested")
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        execution_readiness=transition.execution_readiness,
        last_requested_action=ControlActionType.INGEST,
    )


async def mark_ingest_applied(db: AsyncSession, thread_id: str) -> ThreadModel | None:
    transition = repair_state_for_action(ControlActionType.INGEST, "applied")
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        execution_readiness=transition.execution_readiness,
        last_applied_action=ControlActionType.INGEST,
    )


async def mark_permission_response_requested(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    transition = repair_state_for_action(
        ControlActionType.PERMISSION_RESPONSE_SUBMITTED, "requested"
    )
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        execution_readiness=transition.execution_readiness,
        last_requested_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
    )


async def mark_permission_response_applied(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    transition = repair_state_for_action(
        ControlActionType.PERMISSION_RESPONSE_SUBMITTED, "applied"
    )
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        execution_readiness=transition.execution_readiness,
        last_applied_action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
    )


async def mark_message_followup_requested(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    transition = repair_state_for_action(
        ControlActionType.MESSAGE_FOLLOWUP_REQUESTED, "requested"
    )
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        execution_readiness=transition.execution_readiness,
        last_requested_action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
    )


async def mark_message_followup_applied(
    db: AsyncSession, thread_id: str
) -> ThreadModel | None:
    transition = repair_state_for_action(
        ControlActionType.MESSAGE_FOLLOWUP_APPLIED, "applied"
    )
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        execution_readiness=transition.execution_readiness,
        last_applied_action=ControlActionType.MESSAGE_FOLLOWUP_APPLIED,
    )


async def mark_cancel_requested(db: AsyncSession, thread_id: str) -> ThreadModel | None:
    transition = repair_state_for_action(ControlActionType.CANCEL, "requested")
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        execution_readiness=transition.execution_readiness,
        last_requested_action=ControlActionType.CANCEL,
    )


async def mark_dispatch_failed(
    db: AsyncSession,
    thread_id: str,
    *,
    reason: str = "Worker dispatch failed",
) -> ThreadModel | None:
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
        repair_reason=reason,
        execution_readiness=RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value,
    )
