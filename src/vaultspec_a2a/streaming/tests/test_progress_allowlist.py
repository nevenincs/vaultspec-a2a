"""The progress edge is a CLOSED per-event catalog, enforced at the encode boundary.

The public run-stream relays a run's identifiers, lifecycle, tool and artifact
identity, and bounded text. It must never relay a prompt, a document or artifact
body, an edit diff, or a raw provider payload - and, since the catalog closed, it
must not relay the fields of a frame type nobody enumerated either. These drive
the real projection and the real encoder against payloads shaped exactly like the
worker's relay dicts, and each exclusion assertion is paired with a
permitted-field assertion so an empty frame cannot satisfy it.
"""

from __future__ import annotations

import pytest

from ...api.schemas import ServerEventType
from ..sse_frames import (
    _ALWAYS_SAFE_KEYS,
    _PROGRESS_CATALOG,
    MAX_PROGRESS_CONTENT_CHARS,
    MAX_SSE_FRAME_BYTES,
    encode_sse_frame,
    enforce_progress_allowlist,
)
from ..transformer import project_run_progress

_ARTIFACT_BODY = "SECRET-ARTIFACT-BODY-8f21c9"
_DIFF_BODY = "SECRET-EDIT-DIFF-3a7be1"
_PROVIDER_PAYLOAD = "SECRET-PROVIDER-PAYLOAD-b52d0e"
_PLAN_BODY = "SECRET-PLAN-PROSE-64c1af"
_METADATA_BODY = "SECRET-METADATA-VALUE-19dd73"


# ---------------------------------------------------------------------------
# Forbidden bodies on the content-bearing families
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# The closed default: an unenumerated type keeps identity keys and nothing else
# ---------------------------------------------------------------------------


def test_an_uncatalogued_frame_keeps_only_its_identity_keys() -> None:
    """The default is CLOSED: a type nobody enumerated is degraded, not relayed.

    This inverts the pre-catalog behaviour, where an unmapped type returned
    verbatim. The identity keys still survive - the frame is degraded, never
    refused - so a consumer keeps the routing signal it classifies on.
    """
    frame = enforce_progress_allowlist(
        {
            "type": "some_future_event",
            "event_type": "some_future_event",
            "thread_id": "run-1",
            "agent_id": "worker",
            "sequence": 7,
            "raw_provider_payload": _PROVIDER_PAYLOAD,
            "prompt": "SECRET-PROMPT",
        }
    )

    assert frame == {
        "type": "some_future_event",
        "event_type": "some_future_event",
        "thread_id": "run-1",
        "agent_id": "worker",
        "sequence": 7,
    }


def test_a_frame_naming_no_type_is_degraded_too() -> None:
    """Omitting ``type`` is the same hole from the other side, and is closed."""
    frame = enforce_progress_allowlist(
        {"thread_id": "run-1", "raw_provider_payload": _PROVIDER_PAYLOAD}
    )

    assert frame == {"thread_id": "run-1"}


def test_the_execution_state_projection_is_deliberately_uncatalogued() -> None:
    """It never reaches a subscriber queue; a leaked one degrades to identity."""
    assert "execution_state_projection" not in _PROGRESS_CATALOG

    frame = enforce_progress_allowlist(
        {
            "type": "execution_state_projection",
            "thread_id": "run-1",
            "snapshot": {"prompt": "SECRET-PROMPT"},
            "degraded_reasons": ["stale"],
        }
    )

    assert frame == {"type": "execution_state_projection", "thread_id": "run-1"}


# ---------------------------------------------------------------------------
# Consumer-proven fields must survive the flipped default
# ---------------------------------------------------------------------------


def test_agent_status_keeps_the_live_activity_state() -> None:
    """``state`` drives the consumer's activity indicator and must survive."""
    frame = enforce_progress_allowlist(
        {
            "type": "agent_status",
            "thread_id": "run-1",
            "node_name": "synthesis",
            "state": "working",
            "detail": "thinking",
            "prompt": "SECRET-PROMPT",
        }
    )

    assert frame["state"] == "working"
    assert frame["node_name"] == "synthesis"
    assert frame["detail"] == "thinking"
    assert "prompt" not in frame


def test_team_status_keeps_the_roster_liveness_fields() -> None:
    """The consumer's roster reads ``agents[].agent_id`` and ``agents[].state``."""
    frame = enforce_progress_allowlist(
        {
            "type": "team_status",
            "thread_id": "run-1",
            "active_thread_ids": ["run-1", "run-2"],
            "agents": [
                {
                    "agent_id": "researcher_00",
                    "state": "working",
                    "node_name": "research_dispatch",
                    "provider": "anthropic",
                    "model": "sonnet",
                    "role": "researcher",
                    "display_name": "Researcher",
                    "description": "Reads sources",
                    "raw_provider_payload": _PROVIDER_PAYLOAD,
                }
            ],
        }
    )

    # Asserted as the whole rebuilt item: the two consumer-read fields are
    # present and the smuggled provider payload has no place to hide.
    assert frame["agents"] == [
        {
            "agent_id": "researcher_00",
            "state": "working",
            "node_name": "research_dispatch",
            "provider": "anthropic",
            "model": "sonnet",
            "role": "researcher",
            "display_name": "Researcher",
            "description": "Reads sources",
        }
    ]
    assert frame["active_thread_ids"] == ["run-1", "run-2"]


def test_error_keeps_the_rendered_fault_reason() -> None:
    """The consumer renders ``message``; without it the fault reason is generic."""
    frame = enforce_progress_allowlist(
        {
            "type": "error",
            "thread_id": "run-1",
            "code": "worker_failed",
            "message": "provider returned 502",
            "recoverable": True,
            "traceback": _PROVIDER_PAYLOAD,
        }
    )

    assert frame["message"] == "provider returned 502"
    assert frame["code"] == "worker_failed"
    assert frame["recoverable"] is True
    assert "traceback" not in frame


def test_thread_terminal_keeps_its_status_under_the_event_type_alias() -> None:
    """Terminal frames from the worker name only ``event_type``; both resolve."""
    frame = enforce_progress_allowlist(
        {
            "event_type": "thread_terminal",
            "thread_id": "run-1",
            "status": "failed",
            "error_detail": "compilation failed",
        }
    )

    assert frame["event_type"] == "thread_terminal"
    assert frame["status"] == "failed"
    assert frame["error_detail"] == "compilation failed"


@pytest.mark.parametrize(
    ("payload", "kept"),
    [
        (
            {"type": "heartbeat", "server_uptime_seconds": 12.5},
            ("server_uptime_seconds", 12.5),
        ),
        (
            {"type": "stream_rejected", "reason": "stream_limit_exceeded"},
            ("reason", "stream_limit_exceeded"),
        ),
        (
            {"type": "progress_dropped", "dropped_type": "artifact_update"},
            ("dropped_type", "artifact_update"),
        ),
        (
            {"type": "permission_request", "description": "Allow edit?"},
            ("description", "Allow edit?"),
        ),
    ],
)
def test_each_catalogued_lifecycle_field_survives(
    payload: dict[str, object], kept: tuple[str, object]
) -> None:
    """Enumerating a type is what keeps its field on the wire after the flip."""
    frame = enforce_progress_allowlist(payload)
    key, value = kept
    assert frame[key] == value


# ---------------------------------------------------------------------------
# The catalog enumerates only frame kinds something actually emits
# ---------------------------------------------------------------------------

# The frame kinds the SSE transport synthesises itself instead of projecting from
# a domain event, so they carry no ``ServerEventType`` discriminator and cannot be
# derived from that enum. Each has a real producer: ``thread_terminal`` and
# ``stream_rejected`` are yielded by ``api.thread_stream._stream_thread_events``
# (both driven live by ``api/tests/test_thread_stream.py`` and
# ``api/tests/test_stream_slot_release.py``), and ``progress_dropped`` is the
# over-cap sentinel, emitted for real by the test below rather than taken on
# trust. A name belongs in this set only when a producer can be pointed at.
_TRANSPORT_FRAME_KINDS = frozenset(
    {"thread_terminal", "stream_rejected", "progress_dropped"}
)


def test_the_over_cap_sentinel_really_emits_its_transport_frame_kind() -> None:
    """``progress_dropped`` is claimed as a transport kind, so it is proven here.

    Driven over the cap through an identity key rather than the content field:
    identity keys are copied verbatim by the projection while ``content`` is
    truncated to its declared cap first, so an oversized body alone can no longer
    reach the byte gate. That makes the unbounded identity keys the honest way in.
    """
    frame = encode_sse_frame(
        {
            "type": "message_chunk",
            "thread_id": "run-" + "x" * (MAX_SSE_FRAME_BYTES + 1),
            "content": "hello",
        },
        event="message_chunk",
        thread_id="run-1",
    )

    assert b'"type":"progress_dropped"' in frame
    assert b'"dropped_type":"message_chunk"' in frame
    assert b'"reason":"frame_exceeds_cap"' in frame


def test_the_catalog_enumerates_exactly_the_frame_kinds_that_can_be_produced() -> None:
    """A catalogued kind nobody emits is a consumer-facing promise nobody keeps.

    The catalog is the public wire contract, so a client written against it may
    wait for a handshake frame that never arrives - which is how a deleted
    surface's vocabulary outlives the surface. Asserted as an equality, in both
    directions, because each direction fails differently: an entry with no
    producer advertises a frame that never comes, while a producible kind with no
    entry loses every one of its fields to the closed default the moment it is
    emitted.

    Both sides are derived, not listed: the projected kinds come from the live
    ``ServerEvent`` discriminator enum, and the transport kinds from the set
    above, whose members each name a producer.
    """
    projected = {kind.value for kind in ServerEventType}

    assert set(_PROGRESS_CATALOG) == projected | _TRANSPORT_FRAME_KINDS


# ---------------------------------------------------------------------------
# ``metadata`` is the unbounded payload hole and is allowlisted nowhere
# ---------------------------------------------------------------------------


def test_no_catalog_entry_admits_metadata() -> None:
    """The free-form envelope dict has no entry anywhere in the catalog."""
    admitting = [
        frame_type
        for frame_type, fields in _PROGRESS_CATALOG.items()
        if "metadata" in fields
    ]
    assert admitting == []
    assert "metadata" not in _ALWAYS_SAFE_KEYS


@pytest.mark.parametrize("frame_type", sorted(_PROGRESS_CATALOG))
def test_metadata_never_survives_any_catalogued_type(frame_type: str) -> None:
    """Every enumerated type drops the free-form dict, not just the old five."""
    frame = enforce_progress_allowlist(
        {
            "type": frame_type,
            "thread_id": "run-1",
            "metadata": {"leaked": _METADATA_BODY},
        }
    )

    assert "metadata" not in frame
    assert frame["thread_id"] == "run-1"


def test_metadata_never_survives_an_uncatalogued_type() -> None:
    """The type that used to pass ``metadata`` verbatim no longer does."""
    frame = enforce_progress_allowlist(
        {
            "type": "some_future_event",
            "thread_id": "run-1",
            "metadata": {"leaked": _METADATA_BODY},
        }
    )

    assert "metadata" not in frame
    assert frame["thread_id"] == "run-1"


# ---------------------------------------------------------------------------
# Nested list items are rebuilt, never forwarded whole
# ---------------------------------------------------------------------------


def test_tool_call_locations_are_rebuilt_field_by_field() -> None:
    """A location item carries path and line only; a smuggled body does not ride."""
    frame = enforce_progress_allowlist(
        {
            "type": "tool_call_start",
            "thread_id": "run-1",
            "tool_call_id": "call-1",
            "locations": [
                {"path": "report.md", "line": 12, "new_text": _DIFF_BODY},
            ],
        }
    )

    locations = frame["locations"]
    assert isinstance(locations, list)
    assert locations[0] == {"path": "report.md", "line": 12}


def test_permission_options_are_rebuilt_field_by_field() -> None:
    """An option item carries its identity and kind, never a smuggled payload."""
    frame = enforce_progress_allowlist(
        {
            "type": "permission_request",
            "thread_id": "run-1",
            "request_id": "req-1",
            "description": "Allow edit?",
            "options": [
                {
                    "option_id": "allow",
                    "name": "Allow",
                    "kind": "allow_once",
                    "raw_provider_payload": _PROVIDER_PAYLOAD,
                }
            ],
        }
    )

    options = frame["options"]
    assert isinstance(options, list)
    assert options[0] == {"option_id": "allow", "name": "Allow", "kind": "allow_once"}


def test_plan_entries_keep_classification_and_drop_the_plan_prose() -> None:
    """A plan entry's ``content`` is model-authored body text and never crosses."""
    frame = enforce_progress_allowlist(
        {
            "type": "plan_update",
            "thread_id": "run-1",
            "entries": [
                {"content": _PLAN_BODY, "status": "in_progress", "priority": "high"}
            ],
        }
    )

    entries = frame["entries"]
    assert isinstance(entries, list)
    assert entries[0] == {"status": "in_progress", "priority": "high"}


def test_nested_list_items_are_bounded_by_count_and_by_text() -> None:
    """Both the item count and each item's text are capped, silently."""
    frame = enforce_progress_allowlist(
        {
            "type": "tool_call_start",
            "thread_id": "run-1",
            "locations": [{"path": "p" * 800, "line": n} for n in range(50)],
        }
    )

    locations = frame["locations"]
    assert isinstance(locations, list)
    assert len(locations) == 32
    # Expected values derive from the declared caps (32 items, path 512), not
    # from an observed run.
    assert locations[0] == {"path": "p" * 512, "line": 0}
    assert locations[-1] == {"path": "p" * 512, "line": 31}


def test_a_text_list_is_bounded_by_count_and_by_item_length() -> None:
    """``active_thread_ids`` is a bounded list of bounded strings."""
    frame = enforce_progress_allowlist(
        {
            "type": "team_status",
            "thread_id": "run-1",
            "active_thread_ids": ["t" * 300] * 100,
        }
    )

    ids = frame["active_thread_ids"]
    assert isinstance(ids, list)
    assert len(ids) == 64
    first = ids[0]
    assert isinstance(first, str)
    assert len(first) == 128


# ---------------------------------------------------------------------------
# Truncation, not refusal
# ---------------------------------------------------------------------------


def test_over_cap_text_is_truncated_rather_than_dropping_the_field() -> None:
    """A field over its cap keeps its bounded prefix; the frame is not refused."""
    frame = enforce_progress_allowlist(
        {
            "type": "error",
            "thread_id": "run-1",
            "code": "c" * 400,
            "message": "m" * 4000,
        }
    )

    message = frame["message"]
    code = frame["code"]
    assert isinstance(message, str)
    assert isinstance(code, str)
    assert len(message) == 512
    assert len(code) == 64
    assert message.startswith("mmm")


def test_a_wrongly_shaped_value_is_omitted_and_the_frame_survives() -> None:
    """A bool field given a dict loses that field only, never the whole frame."""
    frame = enforce_progress_allowlist(
        {
            "type": "artifact_update",
            "thread_id": "run-1",
            "artifact_id": "art-1",
            "last_chunk": {"smuggled": _PROVIDER_PAYLOAD},
        }
    )

    assert "last_chunk" not in frame
    assert frame["artifact_id"] == "art-1"


def test_an_unrecognised_enum_member_still_crosses() -> None:
    """Enums are bounded as text, so a producer ahead of the catalog is not silenced."""
    frame = enforce_progress_allowlist(
        {"type": "agent_status", "thread_id": "run-1", "state": "some_new_state"}
    )

    assert frame["state"] == "some_new_state"


# ---------------------------------------------------------------------------
# The two layers share one authority, and the encoded bytes agree
# ---------------------------------------------------------------------------


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


def test_the_producer_projection_closes_the_default_too() -> None:
    """The relay seam degrades an uncatalogued type exactly as the boundary does."""
    payload = {
        "type": "some_future_event",
        "thread_id": "run-1",
        "raw_provider_payload": _PROVIDER_PAYLOAD,
    }

    assert project_run_progress(payload) == {
        "type": "some_future_event",
        "thread_id": "run-1",
    }


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


def test_encoded_uncatalogued_bytes_exclude_everything_but_identity() -> None:
    """The closed default holds all the way to the wire bytes."""
    encoded = encode_sse_frame(
        {
            "type": "some_future_event",
            "thread_id": "run-1",
            "metadata": {"leaked": _METADATA_BODY},
            "prompt": _PROVIDER_PAYLOAD,
        },
        event="some_future_event",
        thread_id="run-1",
    ).decode("utf-8")

    assert _METADATA_BODY not in encoded
    assert _PROVIDER_PAYLOAD not in encoded
    assert "some_future_event" in encoded
    assert '"thread_id":"run-1"' in encoded
