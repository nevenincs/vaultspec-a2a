"""Run status must derive from one snapshot, not several.

Every field used to read the checkpoint for itself. A run advancing between
those reads produced a response carrying a status from one moment and a position
from another - internally inconsistent, which is worse than a stale but coherent
answer because a consumer cannot tell the difference.

The derivations are pure functions over an already-read tuple, so this asserts
what they produce from one snapshot rather than how many times they read. The
channel names come from the module rather than being spelled here: a rename would
otherwise turn every assertion into "field absent" and keep passing.
"""

from __future__ import annotations

from langgraph.checkpoint.base import CheckpointTuple

from ...control.thread_state_service import (
    ACTIVE_FEATURE_FIELD,
    AUTHORING_SESSION_FIELD,
    CHANGESET_ID_FIELD,
    PROPOSAL_ID_FIELD,
    derive_run_authoring_ids,
    derive_run_semantic_context,
)


def _snapshot(values: dict[str, object]) -> CheckpointTuple:
    """Build the concrete LangGraph tuple that production code receives."""
    return CheckpointTuple(
        config={"configurable": {"thread_id": "thread-1"}},
        checkpoint={
            "v": 1,
            "id": "checkpoint-1",
            "ts": "2026-08-02T00:00:00+00:00",
            "channel_values": values,
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": [],
        },
        metadata={"source": "loop", "step": 0, "parents": {}},
        pending_writes=[],
    )


def test_both_derivations_read_the_same_snapshot() -> None:
    """One tuple in, coherent fields out."""
    snapshot = _snapshot(
        {
            PROPOSAL_ID_FIELD: ["p-1", "p-2"],
            CHANGESET_ID_FIELD: ["c-1"],
            ACTIVE_FEATURE_FIELD: "my-feature",
            AUTHORING_SESSION_FIELD: "s-1",
        }
    )

    proposals, changesets = derive_run_authoring_ids(snapshot)
    semantic = derive_run_semantic_context(snapshot)

    assert proposals == ["p-1", "p-2"]
    assert changesets == ["c-1"]
    assert semantic.feature_tag == "my-feature"
    assert semantic.authoring_session_id == "s-1"


def test_an_absent_snapshot_degrades_every_field_rather_than_raising() -> None:
    """An unreadable checkpoint must not fail the whole run-status read."""
    proposals, changesets = derive_run_authoring_ids(None)
    semantic = derive_run_semantic_context(None)

    assert proposals == []
    assert changesets == []
    assert semantic.feature_tag is None
    assert semantic.authoring_session_id is None


def test_a_snapshot_with_empty_channel_values_is_tolerated() -> None:
    """A real checkpoint with no relevant channels degrades rather than raising."""
    snapshot = _snapshot({})

    assert derive_run_authoring_ids(snapshot) == ([], [])
    assert derive_run_semantic_context(snapshot).feature_tag is None


def test_missing_individual_fields_degrade_independently() -> None:
    """A run with proposals but no feature tag reports exactly that."""
    snapshot = _snapshot({PROPOSAL_ID_FIELD: ["p-1"]})

    proposals, changesets = derive_run_authoring_ids(snapshot)
    semantic = derive_run_semantic_context(snapshot)

    assert proposals == ["p-1"]
    assert changesets == []
    assert semantic.feature_tag is None


def test_the_derivations_do_not_mutate_the_snapshot() -> None:
    """Two derivations share one tuple; neither may disturb it for the other."""
    snapshot = _snapshot({PROPOSAL_ID_FIELD: ["p-1"], ACTIVE_FEATURE_FIELD: "f"})
    before = dict(snapshot.checkpoint["channel_values"])

    derive_run_authoring_ids(snapshot)
    derive_run_semantic_context(snapshot)

    assert snapshot.checkpoint["channel_values"] == before
