"""Pure reconciliation decision logic — no I/O, no database imports.

Given thread state snapshots, computes the set of actions needed to bring
non-terminal threads into a consistent state after a gateway restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..thread.enums import ControlActionType, RepairStatus, ThreadStatus

STARTUP_REPAIR_REASON: str = "Gateway restarted with an active thread"


@dataclass(frozen=True, slots=True)
class ThreadSnapshot:
    """Minimal view of a non-terminal thread needed for reconciliation."""

    thread_id: str
    status: str
    recovery_epoch: int


@dataclass(frozen=True, slots=True)
class ReconciliationAction:
    """Describes a single reconciliation mutation to apply.

    The I/O executor reads these descriptors and translates them into
    database calls — keeping this module free of async and DB dependencies.
    """

    thread_id: str
    new_thread_status: str | None
    """Target ThreadStatus value, or None to skip status update."""
    repair_status: str
    repair_reason: str
    execution_readiness: str
    last_applied_action: str | None = None
    increment_generation: bool = False
    increment_recovery_epoch: bool = False


def compute_reconciliation_actions(
    threads: list[ThreadSnapshot],
    checkpoint_results: dict[str, bool],
    checkpoint_errors: dict[str, str | None],
    pending_permissions: dict[str, bool],
    *,
    strategy: Literal["conservative", "mark_repair_needed"] = "conservative",
) -> list[ReconciliationAction]:
    """Compute reconciliation actions for non-terminal threads.

    Args:
        threads: Snapshot of each non-terminal thread.
        checkpoint_results: ``{thread_id: available}`` from checkpoint probing.
        checkpoint_errors: ``{thread_id: error_description | None}``.
        pending_permissions: ``{thread_id: has_pending}``.
        strategy: Reconciliation strategy.

    Returns:
        Ordered list of actions the I/O executor should apply.
    """
    actions: list[ReconciliationAction] = []

    for thread in threads:
        tid = thread.thread_id
        has_pending = pending_permissions.get(tid, False)
        checkpoint_available = checkpoint_results.get(tid, False)
        checkpoint_error = checkpoint_errors.get(tid)

        if has_pending and checkpoint_available:
            new_status: str | None = None
            if thread.status not in (
                ThreadStatus.INPUT_REQUIRED.value,
                ThreadStatus.REPAIR_NEEDED.value,
            ):
                new_status = ThreadStatus.INPUT_REQUIRED.value

            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=new_status,
                    repair_status=RepairStatus.PAUSED_RESUMABLE.value,
                    repair_reason=("Pending permission request survived restart"),
                    execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
                    last_applied_action=(
                        ControlActionType.PERMISSION_REQUEST_CREATED.value
                    ),
                    # Advance the recovery epoch like every other applied outcome:
                    # it seeds the startup-repair idempotency key, so leaving it at
                    # the prior value made the next boot re-derive the SAME key and
                    # crash on the control_actions UNIQUE constraint. Generation is
                    # deliberately NOT bumped here - a paused_resumable thread must
                    # resume its pending permission from the existing checkpoint.
                    increment_recovery_epoch=True,
                ),
            )
        elif thread.status == ThreadStatus.CANCELLING.value and checkpoint_available:
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=None,
                    repair_status=RepairStatus.CANCEL_PENDING.value,
                    repair_reason=(
                        "Cancellation is pending confirmation after restart"
                    ),
                    execution_readiness=RepairStatus.CANCEL_PENDING.value,
                    increment_recovery_epoch=True,
                ),
            )
        elif not checkpoint_available:
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=ThreadStatus.REPAIR_NEEDED.value,
                    repair_status=RepairStatus.CHECKPOINT_UNAVAILABLE.value,
                    repair_reason=(checkpoint_error or "checkpoint_unavailable"),
                    execution_readiness=(RepairStatus.CHECKPOINT_UNAVAILABLE.value),
                    increment_generation=True,
                    increment_recovery_epoch=True,
                ),
            )
        elif strategy == "mark_repair_needed":
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=ThreadStatus.REPAIR_NEEDED.value,
                    repair_status=RepairStatus.CHECKPOINT_UNAVAILABLE.value,
                    repair_reason=("Marked repair_needed by startup strategy"),
                    execution_readiness=(RepairStatus.CHECKPOINT_UNAVAILABLE.value),
                    increment_generation=True,
                    increment_recovery_epoch=True,
                ),
            )
        else:
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=ThreadStatus.RECONCILING.value,
                    repair_status=RepairStatus.NEEDS_RECONCILIATION.value,
                    repair_reason=STARTUP_REPAIR_REASON,
                    execution_readiness=(RepairStatus.NEEDS_RECONCILIATION.value),
                    increment_generation=True,
                    increment_recovery_epoch=True,
                ),
            )

    return actions
