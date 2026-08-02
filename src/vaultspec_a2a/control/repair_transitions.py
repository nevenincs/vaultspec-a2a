"""Named repair-state transition functions for route handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database import set_thread_repair_state, update_thread_status
from ..providers.conditions import ProviderCondition
from ..thread.enums import ControlActionType, ThreadStatus
from ..thread.repair_policy import DISPATCH_FAILED_TRANSITION, repair_state_for_action

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import ThreadModel


async def apply_dispatch_failure(
    db: AsyncSession,
    thread_id: str,
    *,
    failed_status: ThreadStatus,
    reason: str | None = None,
) -> ThreadModel | None:
    """Apply the shared dispatch-failure state transition.

    Run creation, message follow-up, and permission resume all react to a
    should-mark-failed dispatch outcome by pairing a thread-status change with
    the dispatch-failed repair transition. Centralizing the pair keeps a caller
    from updating one without the other.

    ``reason`` is the caller's own account of why the dispatch failed, and every
    caller has one - it was previously spent on an HTTP response body and then
    discarded, so a client that reloaded saw a failed run with no reason at all.
    It is recorded durably here alongside the repair reason.

    The provider condition recorded with it is always the floor, and that is a
    decision rather than an omission: a dispatch that never reached the worker
    engaged no provider, so there is no provider condition to report. Naming one
    - unreachable, overloaded - would describe the LOCAL worker as though it were
    the model vendor and send the reader after the wrong remedy. The dispatch
    layer's own failure vocabulary stays where it already is, in the reason text.
    """
    await update_thread_status(
        db,
        thread_id,
        failed_status,
        failure_reason=reason,
        provider_condition=ProviderCondition.UNKNOWN.value if reason else None,
    )
    return await mark_dispatch_failed(
        db, thread_id, reason=reason or "Worker dispatch failed"
    )


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
