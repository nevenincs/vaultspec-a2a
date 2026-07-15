"""Versioning and bounding of SSE progress frames (ADR R6)."""

from __future__ import annotations

import json

from ..sse_frames import MAX_SSE_FRAME_BYTES, SSE_FRAME_VERSION, encode_sse_frame


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
