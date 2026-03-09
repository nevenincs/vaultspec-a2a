"""Startup reconciliation for durable orchestration state."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.checkpoints import Checkpointer
from ..database.crud import (
    ControlActionResultStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
    create_control_action,
    get_pending_permission_requests,
    list_non_terminal_threads,
    set_thread_repair_state,
    update_thread_status,
)


async def reconcile_threads_on_startup(
    session: AsyncSession,
    checkpointer: Checkpointer,
) -> dict[str, int]:
    """Classify non-terminal threads after a gateway restart."""
    threads = await list_non_terminal_threads(session)
    backlog = 0
    paused = 0
    checkpoint_issues = 0

    for thread in threads:
        backlog += 1
        repair_action = await create_control_action(
            session,
            thread_id=thread.id,
            action_type=ControlActionType.REPAIR_STARTED,
            idempotency_key=f"startup-repair:{thread.id}:{thread.recovery_epoch + 1}",
            payload={"status": thread.status},
        )

        pending_permissions = await get_pending_permission_requests(
            session, thread_id=thread.id
        )
        checkpoint_error: str | None = None
        try:
            checkpoint_tuple = await asyncio.wait_for(
                checkpointer.aget_tuple({"configurable": {"thread_id": thread.id}}),
                timeout=5.0,
            )
            checkpoint_available = checkpoint_tuple is not None
        except TimeoutError:
            checkpoint_available = False
            checkpoint_error = "checkpoint_timeout"
        except Exception:
            checkpoint_available = False
            checkpoint_error = "checkpoint_unavailable"

        if pending_permissions:
            paused += 1
            if thread.status not in (
                ThreadStatus.INPUT_REQUIRED.value,
                ThreadStatus.REPAIR_NEEDED.value,
            ):
                await update_thread_status(
                    session, thread.id, ThreadStatus.INPUT_REQUIRED
                )
            await set_thread_repair_state(
                session,
                thread.id,
                repair_status=RepairStatus.PAUSED_RESUMABLE,
                repair_reason="Pending permission request survived restart",
                execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
                last_applied_action=ControlActionType.PERMISSION_REQUEST_CREATED,
                increment_recovery_epoch=True,
            )
        elif thread.status == ThreadStatus.CANCELLING.value:
            await set_thread_repair_state(
                session,
                thread.id,
                repair_status=RepairStatus.CANCEL_PENDING,
                repair_reason="Cancellation is pending confirmation after restart",
                execution_readiness=RepairStatus.CANCEL_PENDING.value,
                increment_recovery_epoch=True,
            )
        elif not checkpoint_available:
            checkpoint_issues += 1
            await update_thread_status(session, thread.id, ThreadStatus.REPAIR_NEEDED)
            await set_thread_repair_state(
                session,
                thread.id,
                repair_status=RepairStatus.CHECKPOINT_UNAVAILABLE,
                repair_reason=checkpoint_error or "checkpoint_unavailable",
                execution_readiness=RepairStatus.CHECKPOINT_UNAVAILABLE.value,
                increment_generation=True,
                increment_recovery_epoch=True,
            )
        else:
            await update_thread_status(session, thread.id, ThreadStatus.RECONCILING)
            await set_thread_repair_state(
                session,
                thread.id,
                repair_status=RepairStatus.NEEDS_RECONCILIATION,
                repair_reason="Gateway restarted with an active thread",
                execution_readiness=RepairStatus.NEEDS_RECONCILIATION.value,
                increment_generation=True,
                increment_recovery_epoch=True,
            )

        repair_action.result_status = ControlActionResultStatus.APPLIED.value
        repair_action.applied_at = thread.updated_at

        await create_control_action(
            session,
            thread_id=thread.id,
            action_type=ControlActionType.REPAIR_FINISHED,
            idempotency_key=f"startup-repair-finished:{thread.id}:{thread.recovery_epoch}",
            payload={
                "repair_status": thread.repair_status,
                "execution_readiness": thread.execution_readiness,
            },
            result_status=ControlActionResultStatus.APPLIED,
        )

    return {
        "repair_backlog": backlog,
        "paused_resumable": paused,
        "checkpoint_unavailable": checkpoint_issues,
    }
