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

from dataclasses import dataclass
from typing import Any

from vaultspec_a2a.control.thread_state_service import (
    _ACTIVE_FEATURE_FIELD,
    _AUTHORING_SESSION_FIELD,
    _CHANGESET_ID_FIELD,
    _PROPOSAL_ID_FIELD,
    derive_run_authoring_ids,
    derive_run_semantic_context,
)


@dataclass(frozen=True)
class _Tuple:
    """A checkpoint tuple shaped exactly as the library returns one."""

    checkpoint: dict[str, Any]


def _snapshot(**values: Any) -> _Tuple:
    return _Tuple(checkpoint={"channel_values": dict(values)})


def test_both_derivations_read_the_same_snapshot() -> None:
    """One tuple in, coherent fields out."""
    snapshot = _snapshot(
        **{
            _PROPOSAL_ID_FIELD: ["p-1", "p-2"],
            _CHANGESET_ID_FIELD: ["c-1"],
            _ACTIVE_FEATURE_FIELD: "my-feature",
            _AUTHORING_SESSION_FIELD: "s-1",
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


def test_a_snapshot_without_channel_values_is_tolerated() -> None:
    """A checkpoint of an unexpected shape degrades rather than raising."""
    assert derive_run_authoring_ids(_Tuple(checkpoint={})) == ([], [])
    assert derive_run_semantic_context(_Tuple(checkpoint={})).feature_tag is None


def test_missing_individual_fields_degrade_independently() -> None:
    """A run with proposals but no feature tag reports exactly that."""
    snapshot = _snapshot(**{_PROPOSAL_ID_FIELD: ["p-1"]})

    proposals, changesets = derive_run_authoring_ids(snapshot)
    semantic = derive_run_semantic_context(snapshot)

    assert proposals == ["p-1"]
    assert changesets == []
    assert semantic.feature_tag is None


def test_the_derivations_do_not_mutate_the_snapshot() -> None:
    """Two derivations share one tuple; neither may disturb it for the other."""
    snapshot = _snapshot(**{_PROPOSAL_ID_FIELD: ["p-1"], _ACTIVE_FEATURE_FIELD: "f"})
    before = dict(snapshot.checkpoint["channel_values"])

    derive_run_authoring_ids(snapshot)
    derive_run_semantic_context(snapshot)

    assert snapshot.checkpoint["channel_values"] == before
