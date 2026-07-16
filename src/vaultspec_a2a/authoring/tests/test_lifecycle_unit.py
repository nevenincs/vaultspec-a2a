"""Unit tests for lifecycle SSE decoding and verdict extraction.

Pure logic, no I/O. Frame shapes are constructed from the engine's
``LifecycleEventFeedRecord`` / gap / error contracts (read from the Rust source
at ``authoring/events.rs`` and ``authoring/stream.rs``), never copied from a
recorded run.
"""

from __future__ import annotations

import json
from typing import Any

from ..lifecycle import (
    VERDICT_APPROVED,
    VERDICT_REJECTED,
    VERDICT_REQUEST_CHANGES,
    GapSignal,
    LifecycleEvent,
    StreamError,
    changeset_status_verdict,
    parse_sse_frame,
    verdict_from_event,
)


def _lifecycle_record(
    *,
    seq: int,
    event_kind: str,
    aggregate_kind: str,
    aggregate_id: str,
    data: dict[str, Any],
) -> str:
    """Render a lifecycle feed record as the engine serializes it into SSE data."""
    return json.dumps(
        {
            "seq": seq,
            "event_id": f"event:{seq}",
            "aggregate_kind": aggregate_kind,
            "aggregate_id": aggregate_id,
            "event_kind": event_kind,
            "schema_version": 1,
            "actor": {"id": "human:alice", "kind": "human"},
            "payload": {
                "schema": "authoring.lifecycle_event.v1",
                "schema_version": 1,
                "event_kind": event_kind,
                "data": data,
            },
            "payload_hash": "blob:abc",
            "created_at_ms": 1_775_000_000_000,
        }
    )


def test_parse_lifecycle_frame_extracts_inner_payload_data() -> None:
    frame = parse_sse_frame(
        "lifecycle",
        _lifecycle_record(
            seq=5,
            event_kind="approval.resolved",
            aggregate_kind="approval",
            aggregate_id="approval_1",
            data={"decision": "approve", "proposal_id": "prop_1", "comment": "ship"},
        ),
    )
    assert isinstance(frame, LifecycleEvent)
    assert frame.seq == 5
    assert frame.event_kind == "approval.resolved"
    assert frame.aggregate_id == "approval_1"
    assert frame.data["decision"] == "approve"


def test_correlation_ids_union_aggregate_and_payload_ids() -> None:
    frame = parse_sse_frame(
        "lifecycle",
        _lifecycle_record(
            seq=1,
            event_kind="approval.resolved",
            aggregate_kind="approval",
            aggregate_id="approval_1",
            data={
                "decision": "approve",
                "proposal_id": "prop_1",
                "changeset_id": "cs_1",
            },
        ),
    )
    assert isinstance(frame, LifecycleEvent)
    assert frame.correlation_ids() == {"approval_1", "prop_1", "cs_1"}


def test_verdict_approve_maps_to_approved_with_notes() -> None:
    frame = parse_sse_frame(
        "lifecycle",
        _lifecycle_record(
            seq=2,
            event_kind="approval.resolved",
            aggregate_kind="approval",
            aggregate_id="a",
            data={"decision": "approve", "comment": "looks good"},
        ),
    )
    assert isinstance(frame, LifecycleEvent)
    assert verdict_from_event(frame) == (VERDICT_APPROVED, "looks good")


def test_verdict_request_changes_is_distinguished_from_approve() -> None:
    frame = parse_sse_frame(
        "lifecycle",
        _lifecycle_record(
            seq=3,
            event_kind="approval.resolved",
            aggregate_kind="approval",
            aggregate_id="a",
            data={"decision": "request_changes", "comment": "tighten section 2"},
        ),
    )
    assert isinstance(frame, LifecycleEvent)
    assert verdict_from_event(frame) == (
        VERDICT_REQUEST_CHANGES,
        "tighten section 2",
    )


def test_verdict_reject_from_decision_field() -> None:
    frame = parse_sse_frame(
        "lifecycle",
        _lifecycle_record(
            seq=4,
            event_kind="approval.resolved",
            aggregate_kind="approval",
            aggregate_id="a",
            data={"decision": "reject"},
        ),
    )
    assert isinstance(frame, LifecycleEvent)
    assert verdict_from_event(frame) == (VERDICT_REJECTED, None)


def test_proposal_rejected_event_without_decision_reads_as_rejected() -> None:
    frame = parse_sse_frame(
        "lifecycle",
        _lifecycle_record(
            seq=6,
            event_kind="proposal.rejected",
            aggregate_kind="changeset",
            aggregate_id="cs_2",
            data={},
        ),
    )
    assert isinstance(frame, LifecycleEvent)
    assert verdict_from_event(frame) == (VERDICT_REJECTED, None)


def test_non_resolving_event_yields_no_verdict() -> None:
    frame = parse_sse_frame(
        "lifecycle",
        _lifecycle_record(
            seq=7,
            event_kind="approval.requested",
            aggregate_kind="changeset",
            aggregate_id="cs_3",
            data={},
        ),
    )
    assert isinstance(frame, LifecycleEvent)
    assert verdict_from_event(frame) is None


def test_gap_frame_parses_recovery_high_water() -> None:
    frame = parse_sse_frame(
        "gap",
        json.dumps(
            {
                "reason": "replay_window_exceeded",
                "requested_last_seq": 0,
                "latest_outbox_seq": 129,
                "next_recovery_seq": 130,
            }
        ),
    )
    assert isinstance(frame, GapSignal)
    assert frame.reason == "replay_window_exceeded"
    assert frame.latest_outbox_seq == 129
    assert frame.next_recovery_seq == 130


def test_error_frame_parses_error_kind() -> None:
    frame = parse_sse_frame(
        "error",
        json.dumps(
            {
                "error_kind": "authoring_store_unavailable",
                "error": "offline",
                "tiers": {},
            }
        ),
    )
    assert isinstance(frame, StreamError)
    assert frame.error_kind == "authoring_store_unavailable"


def test_malformed_and_unknown_frames_are_dropped() -> None:
    assert parse_sse_frame("lifecycle", "not-json") is None
    assert parse_sse_frame("lifecycle", json.dumps({"no": "seq"})) is None
    assert parse_sse_frame("message", json.dumps({"any": "thing"})) is None


def test_changeset_status_verdict_maps_only_terminal_decisions() -> None:
    assert changeset_status_verdict("approved") == VERDICT_APPROVED
    assert changeset_status_verdict("rejected") == VERDICT_REJECTED
    # Non-terminal / non-verdict statuses carry no reviewer decision.
    assert changeset_status_verdict("needs_review") is None
    assert changeset_status_verdict("draft") is None
    assert changeset_status_verdict("applied") is None
