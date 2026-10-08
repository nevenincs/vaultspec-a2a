"""Pure permission state-machine decision logic — no I/O, no database.

Computes the effects of permission request and resolution events as frozen
descriptor dataclasses. The repair state each event leaves belongs to the
repair policy, keyed by the action the event records.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import (
    ApprovalStatus,
    ControlActionType,
    PermissionRequestStatus,
)
from .snapshots import PLAN_APPROVAL_PAUSE_CAUSES

__all__ = [
    "compute_permission_request_effects",
    "compute_permission_resolution_effects",
]


@dataclass(frozen=True, slots=True)
class PermissionRequestEffects:
    """Descriptor for DB mutations after a permission_request event."""

    last_applied_action: ControlActionType
    is_plan_approval: bool


def compute_permission_request_effects(
    pause_reason_type: str,
) -> PermissionRequestEffects:
    """Compute state-machine effects of a new permission request."""
    return PermissionRequestEffects(
        last_applied_action=ControlActionType.PERMISSION_REQUEST_CREATED,
        is_plan_approval=pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES,
    )


@dataclass(frozen=True, slots=True)
class PermissionResolutionEffects:
    """Descriptor for DB mutations after a permission_resolved event."""

    target_status: PermissionRequestStatus
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
        last_applied_action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
        is_plan_approval=is_plan,
        approval_status=approval,
    )
