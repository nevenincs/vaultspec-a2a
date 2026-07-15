"""Versioning and bounding of SSE progress frames (ADR R6)."""

from __future__ import annotations

import json

from ..sse_frames import (
    MAX_SSE_FRAME_BYTES,
    SSE_FRAME_VERSION,
    encode_sse_frame,
    semantic_phase_for_node,
)


def _data_payload(frame: bytes) -> dict[str, object]:
    """Extract the JSON object from the ``data:`` lines of one SSE frame."""
    text = frame.decode("utf-8")
    data = "".join(
        line.removeprefix("data: ")
        for line in text.splitlines()
        if line.startswith("data: ")
    )
    return json.loads(data)


def test_frame_is_stamped_with_the_contract_version() -> None:
    frame = encode_sse_frame({"type": "progress", "step": 1}, event="progress")
    payload = _data_payload(frame)
    assert payload["api_version"] == SSE_FRAME_VERSION
    assert payload["type"] == "progress"
    assert frame.startswith(b"event: progress\n")


def test_version_stamp_is_idempotent() -> None:
    already = {"api_version": SSE_FRAME_VERSION, "type": "progress"}
    payload = _data_payload(encode_sse_frame(already))
    # No nested/duplicated version wrapper is introduced.
    assert payload == already


def test_oversized_frame_degrades_to_a_versioned_drop_sentinel() -> None:
    huge = {"type": "artifact", "content": "x" * (MAX_SSE_FRAME_BYTES + 1024)}
    frame = encode_sse_frame(huge, event="artifact", thread_id="run-1")
    assert len(frame) <= MAX_SSE_FRAME_BYTES
    payload = _data_payload(frame)
    assert payload["api_version"] == SSE_FRAME_VERSION
    assert payload["type"] == "progress_dropped"
    assert payload["dropped_type"] == "artifact"
    assert payload["thread_id"] == "run-1"
    assert frame.startswith(b"event: progress_dropped\n")


def test_within_bound_frame_passes_through_verbatim() -> None:
    frame = encode_sse_frame({"type": "progress", "n": 2}, event="progress")
    payload = _data_payload(frame)
    assert payload["type"] == "progress"
    assert payload["n"] == 2


# ---------------------------------------------------------------------------
# Semantic phase stamping (a2a-edge-conformance P02.S05)
# ---------------------------------------------------------------------------


def test_semantic_phase_for_node_maps_research_adr_nodes() -> None:
    assert semantic_phase_for_node("research_dispatch") == "researching"
    assert semantic_phase_for_node("research_dispatch_researcher_00") == "researching"
    assert semantic_phase_for_node("mount_synthesis") == "synthesizing_research"
    assert semantic_phase_for_node("research_gate") == "awaiting_research_decision"
    assert semantic_phase_for_node("adr_gate") == "awaiting_adr_decision"


def test_semantic_phase_for_node_returns_none_for_non_research_adr() -> None:
    assert semantic_phase_for_node("vaultspec-coder") is None
    assert semantic_phase_for_node("supervisor") is None
    assert semantic_phase_for_node("__end__") is None
    assert semantic_phase_for_node("") is None


def test_frame_is_stamped_with_semantic_phase_from_node_name() -> None:
    frame = encode_sse_frame(
        {"type": "agent_status", "node_name": "synthesis", "state": "working"},
        event="agent_status",
    )
    payload = _data_payload(frame)
    assert payload["semantic_phase"] == "synthesizing_research"


def test_frame_semantic_phase_falls_back_to_agent_id() -> None:
    frame = encode_sse_frame(
        {"type": "agent_status", "agent_id": "adr_review", "state": "working"}
    )
    payload = _data_payload(frame)
    assert payload["semantic_phase"] == "reviewing_adr"


def test_non_research_adr_frame_carries_no_semantic_phase() -> None:
    frame = encode_sse_frame(
        {"type": "agent_status", "node_name": "vaultspec-coder", "state": "working"}
    )
    payload = _data_payload(frame)
    assert "semantic_phase" not in payload


def test_frame_without_node_carries_no_semantic_phase() -> None:
    frame = encode_sse_frame({"type": "heartbeat"}, event="heartbeat")
    payload = _data_payload(frame)
    assert "semantic_phase" not in payload


def test_existing_semantic_phase_is_not_overwritten() -> None:
    frame = encode_sse_frame(
        {"type": "agent_status", "node_name": "synthesis", "semantic_phase": "custom"}
    )
    payload = _data_payload(frame)
    assert payload["semantic_phase"] == "custom"
