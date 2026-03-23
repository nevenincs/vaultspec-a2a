"""Pure reconciliation decision logic — no I/O, no database imports.

Given thread state snapshots, computes the set of actions needed to bring
non-terminal threads into a consistent state after a gateway restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class _ThreadStatus(StrEnum):
    """Subset of ThreadStatus values relevant to reconciliation decisions."""

    INPUT_REQUIRED = "input_required"
    REPAIR_NEEDED = "repair_needed"
    CANCELLING = "cancelling"
    RECONCILING = "reconciling"


class _RepairStatus(StrEnum):
    """Subset of RepairStatus values used in reconciliation actions."""

    PAUSED_RESUMABLE = "paused_resumable"
    CANCEL_PENDING = "cancel_pending"
    CHECKPOINT_UNAVAILABLE = "checkpoint_unavailable"
    NEEDS_RECONCILIATION = "needs_reconciliation"


class _ControlActionType(StrEnum):
    """Subset of ControlActionType values referenced in reconciliation."""

    PERMISSION_REQUEST_CREATED = "permission_request_created"


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

        if has_pending:
            new_status: str | None = None
            if thread.status not in (
                _ThreadStatus.INPUT_REQUIRED.value,
                _ThreadStatus.REPAIR_NEEDED.value,
            ):
                new_status = _ThreadStatus.INPUT_REQUIRED.value

            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=new_status,
                    repair_status=_RepairStatus.PAUSED_RESUMABLE.value,
                    repair_reason=("Pending permission request survived restart"),
                    execution_readiness=_RepairStatus.PAUSED_RESUMABLE.value,
                    last_applied_action=(
                        _ControlActionType.PERMISSION_REQUEST_CREATED.value
                    ),
                ),
            )
        elif thread.status == _ThreadStatus.CANCELLING.value:
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=None,
                    repair_status=_RepairStatus.CANCEL_PENDING.value,
                    repair_reason=(
                        "Cancellation is pending confirmation after restart"
                    ),
                    execution_readiness=_RepairStatus.CANCEL_PENDING.value,
                    increment_recovery_epoch=True,
                ),
            )
        elif not checkpoint_available:
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=_ThreadStatus.REPAIR_NEEDED.value,
                    repair_status=_RepairStatus.CHECKPOINT_UNAVAILABLE.value,
                    repair_reason=(checkpoint_error or "checkpoint_unavailable"),
                    execution_readiness=(_RepairStatus.CHECKPOINT_UNAVAILABLE.value),
                    increment_generation=True,
                    increment_recovery_epoch=True,
                ),
            )
        elif strategy == "mark_repair_needed":
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=_ThreadStatus.REPAIR_NEEDED.value,
                    repair_status=_RepairStatus.CHECKPOINT_UNAVAILABLE.value,
                    repair_reason=("Marked repair_needed by startup strategy"),
                    execution_readiness=(_RepairStatus.CHECKPOINT_UNAVAILABLE.value),
                    increment_generation=True,
                    increment_recovery_epoch=True,
                ),
            )
        else:
            actions.append(
                ReconciliationAction(
                    thread_id=tid,
                    new_thread_status=_ThreadStatus.RECONCILING.value,
                    repair_status=_RepairStatus.NEEDS_RECONCILIATION.value,
                    repair_reason=("Gateway restarted with an active thread"),
                    execution_readiness=(_RepairStatus.NEEDS_RECONCILIATION.value),
                    increment_generation=True,
                    increment_recovery_epoch=True,
                ),
            )

    return actions
