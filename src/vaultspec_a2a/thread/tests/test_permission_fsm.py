"""The permission state machine must settle a denial as a denial.

These exercise the real predicate and the real effect computations. The module is
pure decision logic, so nothing here needs a database: the durable options column
is passed as the JSON string the repository actually stores.

The central regression is a vocabulary confusion. An option's ``kind`` is drawn
from a closed enum; its ``id`` is free-form and provider-defined. The rejecting
*kinds* were once matched against the response *option id*, so a real denial --
Kimi's bare ``"reject"``, or the plan gate's ``"reject"`` -- computed as an
approval and was recorded as one.
"""

from __future__ import annotations

import json

from ...graph.enums import REJECT_OPTION_IDS, REJECT_OPTION_KINDS, is_rejection_response
from ..enums import ApprovalStatus, PermissionRequestStatus
from ..permission_fsm import (
    compute_permission_resolution_effects,
    compute_progress_applied_effects,
    response_is_rejection,
)

# The options the plan and document approval gates actually mint: a bare
# ``"reject"`` id whose kind is ``reject_once``.
_PLAN_OPTIONS = json.dumps(
    [
        {"option_id": "approve", "name": "Approve Plan", "kind": "allow_once"},
        {"option_id": "reject", "name": "Reject — Revise Plan", "kind": "reject_once"},
    ]
)

# Kimi's real offer, proving an option id is not its kind: the ACP wire spells the
# identity ``optionId``, and the id ``"reject"`` is not a PermissionOptionKind value.
_KIMI_OPTIONS = json.dumps(
    [
        {"optionId": "approve", "kind": "allow_once"},
        {"optionId": "approve_for_session", "kind": "allow_always"},
        {"optionId": "reject", "kind": "reject_once"},
    ]
)


def test_the_rejecting_kinds_and_ids_are_different_vocabularies() -> None:
    """The constant that holds kinds must not be mistaken for a set of ids."""
    assert sorted(REJECT_OPTION_KINDS) == ["reject_always", "reject_once"]
    # The bare ids production mints are exactly what the kind set does not cover.
    assert "reject" not in REJECT_OPTION_KINDS
    assert "reject" in REJECT_OPTION_IDS
    assert "deny_once" in REJECT_OPTION_IDS


def test_a_declared_kind_classifies_an_id_the_system_has_never_seen() -> None:
    """The verdict reads the closed vocabulary, so a novel provider id still lands."""
    options = [{"optionId": "nope-not-a-known-spelling", "kind": "reject_always"}]
    assert is_rejection_response(options, "nope-not-a-known-spelling") is True
    assert REJECT_OPTION_IDS.isdisjoint({"nope-not-a-known-spelling"})


def test_the_declared_kind_wins_over_a_rejecting_looking_id() -> None:
    """Precedence is documented as kind-first; pin it rather than leave it implied."""
    options = [{"optionId": "reject_once", "kind": "allow_once"}]
    assert is_rejection_response(options, "reject_once") is False


def test_an_unresolvable_option_falls_back_to_the_id_vocabulary() -> None:
    """A legacy or malformed row must not read as approved by default."""
    assert response_is_rejection(None, "reject") is True
    assert response_is_rejection("", "reject") is True
    assert response_is_rejection("{not json", "reject") is True
    assert response_is_rejection(json.dumps({"not": "a list"}), "reject") is True
    # An id offered by nobody and matching no known spelling is not a rejection.
    assert response_is_rejection(None, "something-else") is False


def test_no_chosen_option_is_not_a_rejection() -> None:
    """Nothing was answered, so there is no denial to record."""
    assert response_is_rejection(_PLAN_OPTIONS, None) is False
    assert response_is_rejection(_PLAN_OPTIONS, "") is False


def test_plan_rejection_resolves_to_rejected_on_the_primary_path() -> None:
    """The `permission_resolved` projection must not overwrite a denial."""
    effects = compute_permission_resolution_effects(
        "reject", "plan_approval_request", _PLAN_OPTIONS
    )
    assert effects.target_status == PermissionRequestStatus.REJECTED
    assert effects.is_plan_approval is True
    assert effects.approval_status == ApprovalStatus.REJECTED


def test_plan_rejection_resolves_to_rejected_on_the_progress_path() -> None:
    """Progress inference must reach the same verdict as the primary path."""
    effects = compute_progress_applied_effects(
        "reject", "plan_approval_request", _PLAN_OPTIONS
    )
    assert effects.target_status == PermissionRequestStatus.REJECTED
    assert effects.is_plan_approval is True
    assert effects.approval_status == ApprovalStatus.REJECTED


def test_plan_approval_still_resolves_to_applied_on_both_paths() -> None:
    """The fix must not invert the approving case it was not about."""
    primary = compute_permission_resolution_effects(
        "approve", "plan_approval_request", _PLAN_OPTIONS
    )
    progress = compute_progress_applied_effects(
        "approve", "plan_approval_request", _PLAN_OPTIONS
    )
    for effects in (primary, progress):
        assert effects.target_status == PermissionRequestStatus.APPLIED
        assert effects.approval_status == ApprovalStatus.APPROVED


def test_a_kimi_tool_denial_settles_as_rejected_on_both_paths() -> None:
    """A tool permission is not a plan approval, but a denial is still a denial.

    This is the escalation case: the option id ``"reject"`` is provider-defined and
    is not a ``PermissionOptionKind`` value, so a kind-set matched against the id
    read this real denial as an approval on both settlement paths.
    """
    primary = compute_permission_resolution_effects("reject", "bash", _KIMI_OPTIONS)
    progress = compute_progress_applied_effects("reject", "bash", _KIMI_OPTIONS)
    for effects in (primary, progress):
        assert effects.target_status == PermissionRequestStatus.REJECTED
        # A tool permission carries no plan approval state to stamp.
        assert effects.is_plan_approval is False
        assert effects.approval_status is None


def test_an_allowed_tool_call_settles_as_applied_on_both_paths() -> None:
    """The approving tool-permission case keeps its existing settlement."""
    primary = compute_permission_resolution_effects("approve", "bash", _KIMI_OPTIONS)
    progress = compute_progress_applied_effects("approve", "bash", _KIMI_OPTIONS)
    for effects in (primary, progress):
        assert effects.target_status == PermissionRequestStatus.APPLIED
        assert effects.approval_status is None
