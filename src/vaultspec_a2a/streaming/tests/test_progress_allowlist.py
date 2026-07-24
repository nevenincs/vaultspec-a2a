"""The progress edge is a positive allowlist, enforced at the encode boundary.

The public run-stream relays a run's identifiers, lifecycle, tool and artifact
identity, and a bounded token stream. It must never relay a prompt, a document or
artifact body, an edit diff, or a raw provider payload. These drive the real
projection and the real encoder against payloads shaped exactly like the worker's
relay dicts, and each exclusion assertion is paired with a permitted-field
assertion so an empty frame cannot satisfy it.
"""

from __future__ import annotations

from ..sse_frames import (
    MAX_PROGRESS_CONTENT_CHARS,
    encode_sse_frame,
    enforce_progress_allowlist,
)
from ..transformer import project_run_progress

_ARTIFACT_BODY = "SECRET-ARTIFACT-BODY-8f21c9"
_DIFF_BODY = "SECRET-EDIT-DIFF-3a7be1"
_PROVIDER_PAYLOAD = "SECRET-PROVIDER-PAYLOAD-b52d0e"


def test_artifact_update_drops_the_body_and_keeps_identity() -> None:
    """An artifact frame carries its identity, never its content body."""
    frame = enforce_progress_allowlist(
        {
            "type": "artifact_update",
            "event_type": "artifact_update",
            "thread_id": "run-1",
            "artifact_id": "art-1",
            "filename": "report.md",
            "content": _ARTIFACT_BODY,
            "append": False,
            "last_chunk": True,
        }
    )

    assert "content" not in frame
    assert frame["artifact_id"] == "art-1"
    assert frame["filename"] == "report.md"
    assert frame["last_chunk"] is True


def test_tool_call_update_drops_content_blocks_and_keeps_metadata() -> None:
    """Tool-call content blocks (edit diffs, raw output) never cross; metadata does."""
    frame = enforce_progress_allowlist(
        {
            "type": "tool_call_update",
            "thread_id": "run-1",
            "tool_call_id": "call-1",
            "title": "Edit report.md",
            "kind": "edit",
            "status": "completed",
            "content": [
                {
                    "content_type": "diff",
                    "path": "report.md",
                    "old_text": "old",
                    "new_text": _DIFF_BODY,
                }
            ],
        }
    )

    assert "content" not in frame
    assert frame["tool_call_id"] == "call-1"
    assert frame["title"] == "Edit report.md"
    assert frame["status"] == "completed"


def test_message_chunk_keeps_bounded_token_content() -> None:
    """The permitted token stream survives but is length-bounded per frame."""
    oversized = "x" * (MAX_PROGRESS_CONTENT_CHARS + 4096)
    frame = enforce_progress_allowlist(
        {
            "type": "message_chunk",
            "thread_id": "run-1",
            "content": oversized,
            "message_id": "m-1",
            "finish_reason": None,
        }
    )

    content = frame["content"]
    assert isinstance(content, str)
    assert len(content) == MAX_PROGRESS_CONTENT_CHARS
    assert frame["message_id"] == "m-1"


def test_thought_chunk_content_is_bounded_too() -> None:
    """Reasoning tokens are a permitted-but-bounded stream, same as messages."""
    frame = enforce_progress_allowlist(
        {
            "type": "thought_chunk",
            "thread_id": "run-1",
            "content": "y" * (MAX_PROGRESS_CONTENT_CHARS + 1),
        }
    )

    content = frame["content"]
    assert isinstance(content, str)
    assert len(content) == MAX_PROGRESS_CONTENT_CHARS


def test_an_unlisted_key_on_a_content_frame_is_dropped() -> None:
    """A raw provider payload smuggled under a content frame is dropped by omission."""
    frame = enforce_progress_allowlist(
        {
            "type": "message_chunk",
            "thread_id": "run-1",
            "content": "hi",
            "raw_provider_payload": _PROVIDER_PAYLOAD,
        }
    )

    assert "raw_provider_payload" not in frame
    assert frame["content"] == "hi"


def test_a_non_content_frame_passes_through_unchanged() -> None:
    """Lifecycle frames carry no body, so they are not projected away."""
    frame = enforce_progress_allowlist(
        {
            "type": "agent_status",
            "thread_id": "run-1",
            "node_name": "synthesis",
            "state": "working",
            "detail": "thinking",
        }
    )

    assert frame["state"] == "working"
    assert frame["detail"] == "thinking"
    assert frame["node_name"] == "synthesis"


def test_the_producer_projection_matches_the_boundary() -> None:
    """The relay-seam projection strips the same body the boundary would."""
    payload = {
        "type": "artifact_update",
        "thread_id": "run-1",
        "artifact_id": "art-1",
        "filename": "report.md",
        "content": _ARTIFACT_BODY,
    }

    assert project_run_progress(payload) == enforce_progress_allowlist(payload)


def test_a_non_mapping_relay_payload_is_left_alone() -> None:
    """The projection only reshapes mappings; other payloads pass untouched."""
    assert project_run_progress("not-a-mapping") == "not-a-mapping"


def test_forbidden_bodies_never_reach_the_encoded_frame() -> None:
    """The encoded SSE bytes carry the identity but none of the forbidden body."""
    encoded = encode_sse_frame(
        {
            "type": "artifact_update",
            "thread_id": "run-1",
            "artifact_id": "art-1",
            "filename": "report.md",
            "content": _ARTIFACT_BODY,
        },
        event="artifact_update",
        thread_id="run-1",
    ).decode("utf-8")

    assert _ARTIFACT_BODY not in encoded
    assert "report.md" in encoded
    assert '"api_version":"v1"' in encoded


def test_encoded_tool_diff_bytes_exclude_the_diff() -> None:
    """An edit diff cannot cross the encoded boundary even as raw bytes."""
    encoded = encode_sse_frame(
        {
            "type": "tool_call_update",
            "thread_id": "run-1",
            "tool_call_id": "call-1",
            "title": "Edit report.md",
            "status": "completed",
            "content": [
                {"content_type": "diff", "path": "report.md", "new_text": _DIFF_BODY}
            ],
        },
        event="tool_call_update",
        thread_id="run-1",
    ).decode("utf-8")

    assert _DIFF_BODY not in encoded
    assert "Edit report.md" in encoded
