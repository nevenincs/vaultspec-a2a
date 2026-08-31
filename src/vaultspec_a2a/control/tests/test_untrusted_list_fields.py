"""What the control layer does with a stored list-of-strings it did not write.

Two control readers pull a list of strings out of a record another process
persisted - a legacy frozen model assignment's per-role fallback chain, and a
run's authoring proposal and changeset ids off a checkpoint channel. Each had
grown its own validator, and the two disagreed on both axes that matter: what a
malformed value becomes, and whether the empty string is a name.

These tests drive the real readers, not the shared validator, so they answer a
question the validator's own tests cannot: that each reader still asks it. They
also pin the disagreement in the direction each reader actually needs - the
assignment reader keeps whatever strings were stored and refuses a mixed list
outright, the authoring reader drops blanks and degrades to an empty list -
because a single validator serving both is only correct if both settings stay
reachable through it.
"""

from __future__ import annotations

from langgraph.checkpoint.base import CheckpointTuple

from ..dispatch import _frozen_model_assignment
from ..thread_state_service import (
    CHANGESET_ID_FIELD,
    PROPOSAL_ID_FIELD,
    derive_run_authoring_ids,
)


def _legacy_metadata(fallback: object) -> dict[str, object]:
    """A persisted legacy frozen assignment whose one role carries *fallback*."""
    return {
        "model_profile": {
            "profile_id": "profile-1",
            "roles": {
                "coder": {
                    "provider": "anthropic",
                    "capability": "code",
                    "fallback": fallback,
                }
            },
        }
    }


def _snapshot(values: dict[str, object]) -> CheckpointTuple:
    """Build the concrete LangGraph tuple production code receives."""
    return CheckpointTuple(
        config={"configurable": {"thread_id": "thread-1"}},
        checkpoint={
            "v": 1,
            "id": "checkpoint-1",
            "ts": "2026-08-03T00:00:00+00:00",
            "channel_values": values,
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": [],
        },
        metadata={"source": "loop", "step": 0, "parents": {}},
        pending_writes=[],
    )


class TestALegacyRoleFallbackChain:
    """The assignment reader keeps stored strings verbatim, or drops the role."""

    def test_a_stored_chain_survives_into_the_recompiled_assignment(self) -> None:
        """The admitted case: a well-formed chain reaches the compiler map."""
        profile_id, assignment = _frozen_model_assignment(
            _legacy_metadata(["openai", "google"])
        )

        assert profile_id == "profile-1"
        assert assignment["coder"]["fallback"] == ["openai", "google"]

    def test_an_empty_chain_is_admitted_and_is_not_a_refusal(self) -> None:
        """A role legitimately naming no fallback still recompiles."""
        _, assignment = _frozen_model_assignment(_legacy_metadata([]))

        assert assignment["coder"]["fallback"] == []

    def test_a_blank_entry_is_kept_because_this_reader_never_asked_to_filter(
        self,
    ) -> None:
        """Filtering is the OTHER reader's need, and must not leak into this one.

        Silently dropping it here would change which chain a restarted run
        recompiles against what was frozen at launch.
        """
        _, assignment = _frozen_model_assignment(_legacy_metadata(["openai", ""]))

        assert assignment["coder"]["fallback"] == ["openai", ""]

    def test_a_mixed_chain_drops_the_whole_role_rather_than_its_bad_entry(
        self,
    ) -> None:
        """Refusal, and specifically refusal of the value rather than the member.

        A reader that kept the string members would yield ``["openai"]`` and
        recompile the run against a chain nobody froze; the role is dropped
        instead, so the run falls back to no stored assignment for it.
        """
        _, assignment = _frozen_model_assignment(_legacy_metadata(["openai", 7]))

        assert assignment == {}

    def test_a_chain_that_is_not_a_list_drops_the_role(self) -> None:
        """A scalar where a chain was stored is malformed, not a one-item chain."""
        _, assignment = _frozen_model_assignment(_legacy_metadata("openai"))

        assert assignment == {}


class TestRunAuthoringIds:
    """The authoring reader drops blank ids and degrades rather than refusing."""

    def test_stored_ids_survive_onto_the_run_status_read(self) -> None:
        """The admitted case, without which every assertion below is vacuous."""
        snapshot = _snapshot(
            {PROPOSAL_ID_FIELD: ["p-1", "p-2"], CHANGESET_ID_FIELD: ["c-1"]}
        )

        assert derive_run_authoring_ids(snapshot) == (["p-1", "p-2"], ["c-1"])

    def test_a_blank_id_is_dropped_rather_than_reported_as_an_id(self) -> None:
        """An empty string is not a name, and must not travel on as one."""
        snapshot = _snapshot(
            {PROPOSAL_ID_FIELD: ["p-1", "", "p-2"], CHANGESET_ID_FIELD: ["", "c-1"]}
        )

        assert derive_run_authoring_ids(snapshot) == (["p-1", "p-2"], ["c-1"])

    def test_a_mixed_channel_degrades_to_no_ids_rather_than_a_partial_answer(
        self,
    ) -> None:
        """run-status must stay readable, and must not report ids it half-read."""
        snapshot = _snapshot({PROPOSAL_ID_FIELD: ["p-1", 3], CHANGESET_ID_FIELD: None})

        assert derive_run_authoring_ids(snapshot) == ([], [])

    def test_a_channel_holding_only_blanks_reports_no_ids(self) -> None:
        """Filtering runs to completion; it does not leave an empty name behind."""
        snapshot = _snapshot({PROPOSAL_ID_FIELD: ["", ""]})

        assert derive_run_authoring_ids(snapshot) == ([], [])
