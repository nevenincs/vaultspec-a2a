"""The permission state machine must settle a denial as a denial.

These exercise the real effect computations. The module is pure decision logic,
so nothing here needs a database: the rejection verdict is decided by the owner
of the durable options column and handed in, and these pin what each verdict
settles into for a plan approval and for a tool permission.
"""

from __future__ import annotations

from ..enums import ApprovalStatus, PermissionRequestStatus
from ..permission_fsm import compute_permission_resolution_effects


def test_plan_rejection_resolves_to_rejected_on_the_primary_path() -> None:
    """The `permission_resolved` projection must not overwrite a denial."""
    effects = compute_permission_resolution_effects(
        "plan_approval_request", rejected=True
    )
    assert effects.target_status == PermissionRequestStatus.REJECTED
    assert effects.is_plan_approval is True
    assert effects.approval_status == ApprovalStatus.REJECTED


def test_plan_approval_still_resolves_to_applied() -> None:
    """Approval still settles as applied."""
    effects = compute_permission_resolution_effects(
        "plan_approval_request", rejected=False
    )
    assert effects.target_status == PermissionRequestStatus.APPLIED
    assert effects.approval_status == ApprovalStatus.APPROVED


def test_a_tool_denial_settles_as_rejected() -> None:
    """A tool permission is not a plan approval, but a denial is still a denial."""
    effects = compute_permission_resolution_effects("bash", rejected=True)
    assert effects.target_status == PermissionRequestStatus.REJECTED
    # A tool permission carries no plan approval state to stamp.
    assert effects.is_plan_approval is False
    assert effects.approval_status is None


def test_an_allowed_tool_call_settles_as_applied() -> None:
    """The approving tool-permission case keeps its existing settlement."""
    effects = compute_permission_resolution_effects("bash", rejected=False)
    assert effects.target_status == PermissionRequestStatus.APPLIED
    assert effects.approval_status is None
