"""Pure permission state-machine decision logic — no I/O, no database.

Computes the effects of permission request and resolution events as frozen
descriptor dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import (
    ApprovalStatus,
    ControlActionType,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
)
from .snapshots import PLAN_APPROVAL_PAUSE_CAUSES

__all__ = [
    "compute_permission_request_effects",
    "compute_permission_resolution_effects",
]


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
    pause_reason_type: str | None,
    *,
    rejected: bool,
) -> PermissionResolutionEffects:
    """Compute state-machine effects of a permission resolution event.

    *rejected* is the rejection verdict over the options the request offered.
    It is decided by the owner of the durable row, which holds those options,
    so this computation settles the verdict it is handed rather than deriving
    a second one.
    """
    target_status = (
        PermissionRequestStatus.REJECTED
        if rejected
        else PermissionRequestStatus.APPLIED
    )
    is_plan = (pause_reason_type or "") in PLAN_APPROVAL_PAUSE_CAUSES

    approval: ApprovalStatus | None = None
    if is_plan:
        approval = ApprovalStatus.REJECTED if rejected else ApprovalStatus.APPROVED

    return PermissionResolutionEffects(
        target_status=target_status,
        repair_status=RepairStatus.HEALTHY,
        repair_reason=None,
        last_applied_action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
        is_plan_approval=is_plan,
        approval_status=approval,
    )
