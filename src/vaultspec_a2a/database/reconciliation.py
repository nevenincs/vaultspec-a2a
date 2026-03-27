"""I/O executor for startup reconciliation — database + checkpoint probing.

Pairs with :mod:`vaultspec_a2a.lifecycle.reconciliation` which computes pure
action descriptors.  This module handles the async I/O: checkpoint probing,
CRUD calls, and control-action journaling.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .checkpoints import Checkpointer

from ..lifecycle.reconciliation import (
    ReconciliationAction,
    ThreadSnapshot,
    compute_reconciliation_actions,
)
from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
)
from .crud import (
    create_control_action,
    get_pending_permission_requests,
    list_non_terminal_threads,
    set_thread_repair_state,
    update_thread_status,
)


async def probe_checkpoints(
    checkpointer: Checkpointer,
    thread_ids: list[str],
    *,
    timeout: float = 5.0,
) -> tuple[dict[str, bool], dict[str, str | None]]:
    """Probe checkpoint availability for a batch of threads.

    Returns:
        A tuple of ``(availability, errors)`` dicts keyed by thread_id.
    """
    availability: dict[str, bool] = {}
    errors: dict[str, str | None] = {}

    for tid in thread_ids:
        error: str | None = None
        try:
            checkpoint_tuple = await asyncio.wait_for(
                checkpointer.aget_tuple(
                    {"configurable": {"thread_id": tid}},
                ),
                timeout=timeout,
            )
            available = checkpoint_tuple is not None
        except TimeoutError:
            available = False
            error = "checkpoint_timeout"
        except Exception:
            available = False
            error = "checkpoint_unavailable"
        availability[tid] = available
        errors[tid] = error

    return availability, errors


async def execute_reconciliation(
    session: AsyncSession,
    actions: list[ReconciliationAction],
    thread_epochs: dict[str, int],
) -> None:
    """Apply reconciliation actions to the database.

    Args:
        session: Active database session.
        actions: Pure action descriptors from ``compute_reconciliation_actions``.
        thread_epochs: ``{thread_id: recovery_epoch}`` for idempotency keys.
    """
    for action in actions:
        tid = action.thread_id
        epoch = thread_epochs.get(tid, 0)

        repair_action = await create_control_action(
            session,
            thread_id=tid,
            action_type=ControlActionType.REPAIR_STARTED,
            idempotency_key=f"startup-repair:{tid}:{epoch + 1}",
            payload={"status": action.new_thread_status or "unchanged"},
        )

        if action.new_thread_status is not None:
            await update_thread_status(
                session,
                tid,
                ThreadStatus(action.new_thread_status),
            )

        repair_kwargs: dict = {
            "repair_status": RepairStatus(action.repair_status),
            "repair_reason": action.repair_reason,
            "execution_readiness": action.execution_readiness,
        }
        if action.last_applied_action is not None:
            repair_kwargs["last_applied_action"] = ControlActionType(
                action.last_applied_action,
            )
        if action.increment_generation:
            repair_kwargs["increment_generation"] = True
        if action.increment_recovery_epoch:
            repair_kwargs["increment_recovery_epoch"] = True

        await set_thread_repair_state(session, tid, **repair_kwargs)

        repair_action.result_status = ControlActionResultStatus.APPLIED.value
        repair_action.applied_at = None  # filled by caller/commit

        await create_control_action(
            session,
            thread_id=tid,
            action_type=ControlActionType.REPAIR_FINISHED,
            idempotency_key=f"startup-repair-finished:{tid}:{epoch}",
            payload={
                "repair_status": action.repair_status,
                "execution_readiness": action.execution_readiness,
            },
            result_status=ControlActionResultStatus.APPLIED,
        )


async def reconcile_threads_on_startup(
    session: AsyncSession,
    checkpointer: Checkpointer,
    *,
    strategy: Literal["conservative", "mark_repair_needed"] = "conservative",
) -> dict[str, int]:
    """Full reconciliation pipeline: probe + decide + execute.

    Drop-in replacement for the original monolithic function.
    """
    threads_rows = await list_non_terminal_threads(session)

    snapshots: list[ThreadSnapshot] = []
    thread_epochs: dict[str, int] = {}

    for t in threads_rows:
        snapshots.append(
            ThreadSnapshot(
                thread_id=t.id,
                status=t.status,
                recovery_epoch=t.recovery_epoch,
            ),
        )
        thread_epochs[t.id] = t.recovery_epoch

    thread_ids = [s.thread_id for s in snapshots]

    checkpoint_results, checkpoint_errors = await probe_checkpoints(
        checkpointer,
        thread_ids,
    )

    pending_map: dict[str, bool] = {}
    for tid in thread_ids:
        perms = await get_pending_permission_requests(session, thread_id=tid)
        pending_map[tid] = bool(perms)

    actions = compute_reconciliation_actions(
        snapshots,
        checkpoint_results,
        checkpoint_errors,
        pending_map,
        strategy=strategy,
    )

    await execute_reconciliation(session, actions, thread_epochs)

    paused = sum(1 for a in actions if a.repair_status == "paused_resumable")
    checkpoint_issues = sum(
        1
        for a in actions
        if a.repair_status == "checkpoint_unavailable"
        and a.repair_reason != "Marked repair_needed by startup strategy"
    )

    return {
        "repair_backlog": len(snapshots),
        "paused_resumable": paused,
        "checkpoint_unavailable": checkpoint_issues,
    }
