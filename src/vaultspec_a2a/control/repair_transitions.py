"""Named repair-state transition functions for route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import set_thread_repair_state, update_thread_status
from ..thread.enums import ControlActionType, ThreadStatus
from ..thread.repair_policy import DISPATCH_FAILED_TRANSITION, repair_state_for_action

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import ThreadModel


async def apply_dispatch_failure(
    db: AsyncSession, thread_id: str, *, failed_status: ThreadStatus
) -> ThreadModel | None:
    """Apply the shared dispatch-failure state transition.

    Run creation, message follow-up, and permission resume all react to a
    should-mark-failed dispatch outcome by pairing a thread-status change with
    the dispatch-failed repair transition. Centralizing the pair keeps a caller
    from updating one without the other.
    """
    await update_thread_status(db, thread_id, failed_status)
    return await mark_dispatch_failed(db, thread_id)


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
    transition = DISPATCH_FAILED_TRANSITION
    return await set_thread_repair_state(
        db,
        thread_id,
        repair_status=transition.repair_status,
        repair_reason=reason,
        execution_readiness=transition.execution_readiness,
    )
