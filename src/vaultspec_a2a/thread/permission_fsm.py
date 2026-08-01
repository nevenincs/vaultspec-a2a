"""Pure permission state-machine decision logic — no I/O, no database.

Computes the effects of permission request, resolution, and
progress-applied events as frozen descriptor dataclasses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..graph.enums import is_rejection_response
from .enums import (
    ApprovalStatus,
    ControlActionType,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
)
from .snapshots import PLAN_APPROVAL_PAUSE_CAUSES

__all__ = [
    "PROGRESS_BATCH_EFFECTS",
    "PermissionRequestEffects",
    "PermissionResolutionEffects",
    "ProgressAppliedEffects",
    "ProgressBatchEffects",
    "compute_permission_request_effects",
    "compute_permission_resolution_effects",
    "compute_progress_applied_effects",
    "response_is_rejection",
]


def response_is_rejection(
    allowed_options_json: str | None,
    response_option_id: str | None,
) -> bool:
    """Decode a durable options column and return the one rejection verdict.

    The offered options are stored as a JSON string, so this owns only the decode
    and delegates the actual judgement to :func:`~..graph.enums.is_rejection_response`.
    It exists so the three settlement sites — the submission stamp in the control
    service, the ``permission_resolved`` projection, and the progress-inferred
    fallback — share one decode *and* one verdict instead of each re-deriving
    rejection from whichever field it happened to have in scope.

    A column that is absent, empty, or malformed JSON yields no options, which
    routes the verdict to the option-id fallback rather than reading as approved.
    """
    options: object = None
    if isinstance(allowed_options_json, str) and allowed_options_json:
        try:
            options = json.loads(allowed_options_json)
        except json.JSONDecodeError:
            options = None
    return is_rejection_response(options, response_option_id)


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
    allowed_options_json: str | None = None,
) -> PermissionResolutionEffects:
    """Compute state-machine effects of a permission resolution event."""
    is_rejected = response_is_rejection(allowed_options_json, response_option_id)
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
    allowed_options_json: str | None = None,
) -> ProgressAppliedEffects:
    """Compute per-permission effects when progress implies application.

    Progress only tells us the worker moved on, never *how* the human answered,
    so the settled status is derived from the recorded response exactly as the
    primary resolution path derives it. A denial inferred from progress therefore
    settles as REJECTED, not as the repository's applied default.
    """
    is_plan = (pause_reason_type or "") in PLAN_APPROVAL_PAUSE_CAUSES
    is_rejected = response_is_rejection(allowed_options_json, response_option_id)

    approval: ApprovalStatus | None = None
    if is_plan:
        approval = ApprovalStatus.REJECTED if is_rejected else ApprovalStatus.APPROVED

    return ProgressAppliedEffects(
        target_status=(
            PermissionRequestStatus.REJECTED
            if is_rejected
            else PermissionRequestStatus.APPLIED
        ),
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
