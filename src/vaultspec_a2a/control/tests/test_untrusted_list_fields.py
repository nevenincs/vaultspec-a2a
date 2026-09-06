"""Control readers fail safely on untrusted persisted collection fields."""

from __future__ import annotations

import json

import pytest
from langgraph.checkpoint.base import CheckpointTuple

from ..execution_authority import (
    ExecutionAuthorityError,
    ExecutionAuthorityFailure,
    resolve_execution_authority,
)
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


class TestRetiredRoleFallbackChain:
    @pytest.mark.parametrize("fallback", (["openai"], [], ["openai", 7], "openai"))
    def test_every_retired_assignment_shape_is_refused(self, fallback: object) -> None:
        with pytest.raises(ExecutionAuthorityError) as raised:
            resolve_execution_authority(json.dumps(_legacy_metadata(fallback)))
        assert raised.value.reason is ExecutionAuthorityFailure.RETIRED


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
