"""Pure permission state-machine decision logic — no I/O, no database.

Computes the effects of permission request, resolution, and
progress-applied events as frozen descriptor dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..graph.enums import REJECT_OPTION_IDS
from .enums import (
    ApprovalStatus,
    ControlActionType,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
)
from .snapshots import PLAN_APPROVAL_PAUSE_CAUSES


@dataclass(frozen=True, slots=True)
class PermissionRequestEffects:
    """Descriptor for DB mutations after a permission_request event."""

    thread_status: ThreadStatus
    repair_status: RepairStatus
    repair_reason: str
    last_applied_action: ControlActionType
    is_plan_approval: bool
    approval_status: ApprovalStatus | None


def compute_permission_request_effects(
    pause_reason_type: str,
) -> PermissionRequestEffects:
    """Compute state-machine effects of a new permission request."""
    is_plan = pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES
    return PermissionRequestEffects(
        thread_status=ThreadStatus.INPUT_REQUIRED,
        repair_status=RepairStatus.PAUSED_RESUMABLE,
        repair_reason="Worker reported a pending permission request",
        last_applied_action=ControlActionType.PERMISSION_REQUEST_CREATED,
        is_plan_approval=is_plan,
        approval_status=ApprovalStatus.PENDING if is_plan else None,
    )


@dataclass(frozen=True, slots=True)
class PermissionResolutionEffects:
    """Descriptor for DB mutations after a permission_resolved event."""

    target_status: PermissionRequestStatus
    repair_status: RepairStatus
    repair_reason: None
    last_applied_action: ControlActionType
    is_plan_approval: bool
    approval_status: ApprovalStatus | None


def compute_permission_resolution_effects(
    response_option_id: str | None,
    pause_reason_type: str | None,
) -> PermissionResolutionEffects:
    """Compute state-machine effects of a permission resolution event."""
    is_rejected = (
        response_option_id is not None and response_option_id in REJECT_OPTION_IDS
    )
    target_status = (
        PermissionRequestStatus.REJECTED
        if is_rejected
        else PermissionRequestStatus.APPLIED
    )
    is_plan = (pause_reason_type or "") in PLAN_APPROVAL_PAUSE_CAUSES

    approval: ApprovalStatus | None = None
    if is_plan:
        approval = ApprovalStatus.REJECTED if is_rejected else ApprovalStatus.APPROVED

    return PermissionResolutionEffects(
        target_status=target_status,
        repair_status=RepairStatus.HEALTHY,
        repair_reason=None,
        last_applied_action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
        is_plan_approval=is_plan,
        approval_status=approval,
    )


@dataclass(frozen=True, slots=True)
class ProgressAppliedEffects:
    """Descriptor for a single answered permission inferred from progress."""

    target_status: PermissionRequestStatus
    last_applied_action: ControlActionType
    is_plan_approval: bool
    approval_status: ApprovalStatus | None


def compute_progress_applied_effects(
    response_option_id: str | None,
    pause_reason_type: str | None,
) -> ProgressAppliedEffects:
    """Compute per-permission effects when progress implies application."""
    is_plan = (pause_reason_type or "") in PLAN_APPROVAL_PAUSE_CAUSES

    approval: ApprovalStatus | None = None
    if is_plan:
        approval = (
            ApprovalStatus.REJECTED
            if response_option_id == "reject"
            else ApprovalStatus.APPROVED
        )

    return ProgressAppliedEffects(
        target_status=PermissionRequestStatus.APPLIED,
        last_applied_action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
        is_plan_approval=is_plan,
        approval_status=approval,
    )


@dataclass(frozen=True, slots=True)
class ProgressBatchEffects:
    """Descriptor for the aggregate effects when any permissions were applied."""

    thread_status: ThreadStatus
    repair_status: RepairStatus
    repair_reason: None
    last_applied_action: ControlActionType


PROGRESS_BATCH_EFFECTS = ProgressBatchEffects(
    thread_status=ThreadStatus.RUNNING,
    repair_status=RepairStatus.HEALTHY,
    repair_reason=None,
    last_applied_action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
)
"""Singleton: the aggregate effects are always the same when any permissions
were applied by progress inference."""
