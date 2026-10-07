"""Tests for the control layer's policy over a durable permission row's options.

``decode_allowed_options`` owns the one JSON decode of the
``allowed_options_json`` column; the valid ids and the rejection verdict are
answered by the canonical Layer 1 option rules over what it decodes, and over an
offer that never went through the column. These tests pin the decode boundary,
prove the two spellings survive the round trip through the column, and pin the
verdict every settlement site shares.

The central verdict regression is a vocabulary confusion. An option's ``kind`` is
drawn from a closed enum; its ``id`` is free-form and provider-defined. The
rejecting *kinds* were once matched against the response *option id*, so a real
denial -- Kimi's bare ``"reject"``, or the plan gate's ``"reject"`` -- computed as
an approval and was recorded as one.
"""

from __future__ import annotations

import json

import pytest

from ...database import decode_allowed_options
from ...graph.acp_options import valid_option_ids
from ...thread.enums import PermissionRequestStatus
from ...thread.permission_fsm import compute_permission_resolution_effects
from ..permission_options import answer_is_rejection, response_is_rejection

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


@pytest.mark.parametrize("key", ["optionId", "option_id"])
def test_either_spelling_survives_the_json_column(key: str) -> None:
    """A row written by the ACP wire and one written by our own edge agree."""
    raw = json.dumps([{key: "allow_once", "name": "Allow"}])

    assert valid_option_ids(decode_allowed_options(raw)) == {"allow_once"}


def test_a_mixed_spelling_row_yields_both_ids() -> None:
    """A durable row may carry options recorded through different transports."""
    raw = json.dumps([{"optionId": "approve"}, {"option_id": "reject_once"}])

    assert valid_option_ids(decode_allowed_options(raw)) == {"approve", "reject_once"}


def test_an_option_without_a_usable_id_contributes_nothing() -> None:
    """A malformed stored option never admits a null answer as valid."""
    raw = json.dumps([{"optionId": "approve"}, {"label": "Nameless"}, {"optionId": ""}])

    valid = valid_option_ids(decode_allowed_options(raw))

    assert valid == {"approve"}
    assert None not in valid


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not json at all",
        "{}",
        '{"options": []}',
        '"a string"',
        "[]",
    ],
)
def test_an_unusable_column_offers_no_ids(raw: str | None) -> None:
    """Absent, malformed, or non-list columns fail closed rather than raise."""
    assert valid_option_ids(decode_allowed_options(raw)) == set()


def test_an_absent_column_is_told_apart_from_an_unreadable_one() -> None:
    """A row that offered nothing is readable; a broken row is not."""
    assert decode_allowed_options(None) == []
    assert decode_allowed_options("[]") == []
    for broken in ("", "not json at all", "{}", '"a string"'):
        assert decode_allowed_options(broken) is None


def test_an_offer_that_never_met_the_column_is_judged_by_the_same_rule() -> None:
    """The checkpoint's live offer and the column's copy of it cannot disagree."""
    offered: list[object] = json.loads(_KIMI_OPTIONS)

    assert answer_is_rejection(offered, "reject") is True
    assert answer_is_rejection(offered, "approve_for_session") is False
    assert answer_is_rejection(offered, None) is False
    assert answer_is_rejection(None, "deny_once") is True


def test_a_declared_kind_classifies_an_id_the_system_has_never_seen() -> None:
    """The verdict reads the closed vocabulary, so a novel provider id still lands."""
    raw = json.dumps(
        [{"optionId": "nope-not-a-known-spelling", "kind": "reject_always"}]
    )

    assert response_is_rejection(raw, "nope-not-a-known-spelling") is True


def test_the_declared_kind_wins_over_a_rejecting_looking_id() -> None:
    """Precedence is documented as kind-first; pin it rather than leave it implied."""
    raw = json.dumps([{"optionId": "reject_once", "kind": "allow_once"}])

    assert response_is_rejection(raw, "reject_once") is False


def test_an_unresolvable_option_falls_back_to_the_id_spelling() -> None:
    """A legacy or malformed row must not read as approved by default."""
    assert response_is_rejection(None, "reject") is True
    assert response_is_rejection("", "reject") is True
    assert response_is_rejection("{not json", "reject") is True
    assert response_is_rejection(json.dumps({"not": "a list"}), "reject") is True
    assert response_is_rejection(None, "deny_once") is True
    # An id offered by nobody and spelling no denial is not a rejection.
    assert response_is_rejection(None, "something-else") is False


def test_no_chosen_option_is_not_a_rejection() -> None:
    """Nothing was answered, so there is no denial to record."""
    assert response_is_rejection(_PLAN_OPTIONS, None) is False
    assert response_is_rejection(_PLAN_OPTIONS, "") is False


def test_the_plan_gate_denial_is_a_rejection() -> None:
    """The gate's bare ``"reject"`` id is a denial by its declared kind."""
    assert response_is_rejection(_PLAN_OPTIONS, "reject") is True
    assert response_is_rejection(_PLAN_OPTIONS, "approve") is False


def test_a_kimi_tool_denial_settles_as_rejected() -> None:
    """The escalation case, from the stored column to the settled status.

    The option id ``"reject"`` is provider-defined and is not a
    ``PermissionOptionKind`` value, so a kind-set matched against the id read this
    real denial as an approval.
    """
    effects = compute_permission_resolution_effects(
        "bash", rejected=response_is_rejection(_KIMI_OPTIONS, "reject")
    )
    assert effects.target_status == PermissionRequestStatus.REJECTED
    assert effects.approval_status is None


def test_a_kimi_tool_approval_settles_as_applied() -> None:
    """The approving answer to the same offer keeps its settlement."""
    effects = compute_permission_resolution_effects(
        "bash", rejected=response_is_rejection(_KIMI_OPTIONS, "approve")
    )
    assert effects.target_status == PermissionRequestStatus.APPLIED
