"""Versioning and bounding of SSE progress frames."""

from __future__ import annotations

import json

import pytest

from ...graph.enums import RESEARCH_ADR_NODE_PHASE
from ..sse_frames import (
    MAX_PROGRESS_CONTENT_CHARS,
    MAX_SSE_FRAME_BYTES,
    SSE_FRAME_VERSION,
    catalog_worst_case_frame_bytes,
    encode_sse_frame,
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


def _agents_of(payload: dict[str, object]) -> list[dict[str, object]]:
    """Narrow the ``agents`` list of a decoded ``team_status`` payload."""
    agents = payload["agents"]
    assert isinstance(agents, list)
    entries: list[dict[str, object]] = []
    for item in agents:
        assert isinstance(item, dict)
        entries.append({str(key): value for key, value in item.items()})
    return entries


def test_frame_is_stamped_with_the_contract_version() -> None:
    frame = encode_sse_frame(
        {"type": "stream_rejected", "reason": "stream_limit_exceeded"},
        event="stream_rejected",
    )
    payload = _data_payload(frame)
    assert payload["api_version"] == SSE_FRAME_VERSION
    assert payload["type"] == "stream_rejected"
    assert frame.startswith(b"event: stream_rejected\n")


def test_version_stamp_is_idempotent() -> None:
    already = {
        "api_version": SSE_FRAME_VERSION,
        "type": "stream_rejected",
        "reason": "stream_limit_exceeded",
    }
    payload = _data_payload(encode_sse_frame(already))
    # No nested/duplicated version wrapper is introduced.
    assert payload == already


def test_oversized_frame_degrades_to_a_versioned_drop_sentinel() -> None:
    """The byte cap is the backstop for what the per-field caps cannot bound.

    Every catalogued text field is now truncated to its own cap, so the way over
    the byte cap is an identity key - here ``message_id`` - which the catalog
    passes verbatim by design. The frame still degrades rather than blocking the
    stream.
    """
    huge = {
        "type": "message_chunk",
        "message_id": "x" * (MAX_SSE_FRAME_BYTES + 1024),
        "content": "hello",
    }
    frame = encode_sse_frame(huge, event="message_chunk", thread_id="run-1")
    assert len(frame) <= MAX_SSE_FRAME_BYTES
    payload = _data_payload(frame)
    assert payload["api_version"] == SSE_FRAME_VERSION
    assert payload["type"] == "progress_dropped"
    assert payload["dropped_type"] == "message_chunk"
    assert payload["thread_id"] == "run-1"
    assert frame.startswith(b"event: progress_dropped\n")


def test_catalogued_caps_cannot_breach_the_frame_byte_cap() -> None:
    """The character caps and the byte cap must be sized against each other.

    The per-field caps count characters and the frame cap counts bytes, so they
    agree only if the byte cap covers the catalog's worst-case UTF-8 and JSON
    expansion. Were it smaller, a frame every one of whose fields respected its
    cap could still be dropped - and only ever for non-ASCII text.
    """
    assert catalog_worst_case_frame_bytes() <= MAX_SSE_FRAME_BYTES


@pytest.mark.parametrize(
    ("label", "filler"),
    [
        ("cjk", "中"),
        ("astral", "\U0001f600"),
        ("combining", "é"),
    ],
)
def test_team_status_within_character_caps_survives_non_ascii(
    label: str, filler: str
) -> None:
    """Non-ASCII text inside every declared cap must stream, not degrade.

    ``team_status`` drives the agent panel, and its declared caps are the largest
    in the catalog. Filling them with multibyte text keeps every field inside its
    character cap while multiplying the encoded byte count several-fold; the
    frame must still arrive, or a CJK or emoji team would silently lose the one
    frame an English team receives.
    """
    text = (filler * 512)[:256]
    frame = encode_sse_frame(
        {
            "type": "team_status",
            "active_thread_ids": [text[:128]] * 64,
            "agents": [
                {
                    "agent_id": text[:63],
                    "state": text[:64],
                    "node_name": text[:128],
                    "provider": text[:64],
                    "model": text[:128],
                    "role": text[:64],
                    "display_name": text[:128],
                    "description": text[:256],
                }
            ]
            * 64,
        },
        event="team_status",
        thread_id="run-1",
    )
    payload = _data_payload(frame)
    assert payload["type"] == "team_status", (
        f"{label} team_status degraded to {payload['type']!r} despite every "
        f"field sitting inside its character cap"
    )
    # Round-trips as characters, not mojibake or escapes.
    assert _agents_of(payload)[0]["description"] == text[:256]


@pytest.mark.parametrize(
    ("name", "separator"),
    [
        # Built by code point rather than written literally: these three are
        # invisible in source and indistinguishable from a space to a reader.
        ("line separator", chr(0x2028)),
        ("paragraph separator", chr(0x2029)),
        ("next line", chr(0x0085)),
    ],
)
def test_unicode_line_separators_never_split_a_data_line(
    name: str, separator: str
) -> None:
    """A separator inside content must not break the frame into two data lines.

    JSON leaves these three unescaped, yet ``str.splitlines`` counts all three as
    line breaks. If one reached the wire raw it would split the ``data:`` line,
    and a consumer rejoining the parts under the SSE grammar would read a newline
    where the producer wrote a separator - corrupting content while every length
    bound still looked satisfied.
    """
    content = f"before{separator}after"
    frame = encode_sse_frame(
        {"type": "message_chunk", "content": content},
        event="message_chunk",
        thread_id="run-1",
    )
    body = frame.split(b"\n\n", 1)[0]
    data_lines = [
        line for line in body.decode("utf-8").splitlines() if line.startswith("data: ")
    ]
    assert len(data_lines) == 1, f"{name} split the frame into {len(data_lines)} lines"
    assert _data_payload(frame)["content"] == content


def test_over_cap_catalogued_text_truncates_instead_of_dropping_the_frame() -> None:
    """A field over its own cap truncates, so the frame survives the byte cap."""
    frame = encode_sse_frame(
        {
            "type": "message_chunk",
            "thread_id": "run-1",
            "content": "x" * (MAX_SSE_FRAME_BYTES + 1024),
        },
        event="message_chunk",
        thread_id="run-1",
    )
    payload = _data_payload(frame)
    assert payload["type"] == "message_chunk"
    content = payload["content"]
    assert isinstance(content, str)
    assert len(content) == MAX_PROGRESS_CONTENT_CHARS


def test_an_uncatalogued_frame_keeps_only_its_identity_keys() -> None:
    """The catalog default is closed: an unenumerated field does not pass through.

    This deliberately inverts the pre-catalog contract, under which an unmapped
    type was relayed verbatim. The type name itself is preserved, so a consumer
    that classifies frames by name is not silently rerouted.
    """
    frame = encode_sse_frame({"type": "progress", "n": 2}, event="progress")
    payload = _data_payload(frame)
    assert payload["type"] == "progress"
    assert "n" not in payload


# ---------------------------------------------------------------------------
# clarification_pending
# ---------------------------------------------------------------------------


def test_clarification_pending_carries_only_the_request_id() -> None:
    """The nudge frame is minimal: request_id only, never the questions."""
    frame = encode_sse_frame(
        {
            "type": "clarification_pending",
            "thread_id": "run-1",
            "request_id": "abc123",
            "questions": [{"id": "provider", "prompt": "Which provider?"}],
        },
        event="clarification_pending",
        thread_id="run-1",
    )
    payload = _data_payload(frame)
    assert payload["type"] == "clarification_pending"
    assert payload["request_id"] == "abc123"
    # The questions themselves never cross the relay - a nudge to re-read
    # run-status, never the source of the questions (D5(b)).
    assert "questions" not in payload


def test_clarification_pending_request_id_truncates_over_cap() -> None:
    """Truncated to the catalog's own declared bound for this field."""
    frame = encode_sse_frame(
        {
            "type": "clarification_pending",
            "thread_id": "run-1",
            "request_id": "x" * 200,
        },
        event="clarification_pending",
        thread_id="run-1",
    )
    payload = _data_payload(frame)
    request_id = payload["request_id"]
    # Narrowed rather than cast: the frame carries JSON, so the decoded value is
    # object until something proves otherwise. Asserting the type here also pins
    # that the cap produces a STRING - a truncation that yielded bytes or a list
    # of 128 things would satisfy a bare length check.
    assert isinstance(request_id, str)
    assert len(request_id) == 128


# ---------------------------------------------------------------------------
# Semantic phase stamping
# ---------------------------------------------------------------------------


def test_stamped_frames_agree_with_the_shared_phase_map_for_every_node() -> None:
    """Every node the graph declares stamps that node's phase onto the frame.

    Asserted against the owning map rather than a copied node list, so a phase
    added to the vocabulary is covered here the day it is added. Driven through
    ``encode_sse_frame`` rather than the mapping function, because the stamping is
    what this layer owes; a stamper that dropped the phase entirely would satisfy
    a test that only called the function.
    """
    assert RESEARCH_ADR_NODE_PHASE, "the shared phase map must not be empty"
    for node, expected in RESEARCH_ADR_NODE_PHASE.items():
        frame = encode_sse_frame({"type": "agent_status", "node_name": node})
        assert _data_payload(frame)["semantic_phase"] == expected, node
        mounted = encode_sse_frame(
            {"type": "agent_status", "node_name": f"mount_{node}"}
        )
        assert _data_payload(mounted)["semantic_phase"] == expected, node


def test_fan_out_nodes_stamp_the_researching_phase() -> None:
    """The dispatch and researcher fan-out resolve by prefix, not by map entry."""
    for node in ("research_dispatch", "research_dispatch_researcher_00"):
        frame = encode_sse_frame({"type": "agent_status", "node_name": node})
        assert _data_payload(frame)["semantic_phase"] == "researching", node


@pytest.mark.parametrize("node", ["supervisor", "__end__", ""])
def test_nodes_outside_the_topology_stamp_no_phase(node: str) -> None:
    """A node the vocabulary does not cover never has a phase fabricated for it."""
    frame = encode_sse_frame({"type": "agent_status", "node_name": node})
    assert "semantic_phase" not in _data_payload(frame)


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


def test_streaming_does_not_republish_the_phase_vocabulary() -> None:
    """The stamper consumes graph.enums; it does not offer a second way in.

    The mapping was once re-exported from this module under a shorter name, so a
    reader searching for the owner's spelling found no consumer here and a reader
    searching for the short one found no owner. The surface that must REMAIN is
    asserted alongside the absence, since an emptied module would satisfy the
    absence on its own.
    """
    from .. import sse_frames

    assert "semantic_phase_for_node" not in sse_frames.__all__
    assert not hasattr(sse_frames, "semantic_phase_for_node")
    assert "encode_sse_frame" in sse_frames.__all__
    assert "enforce_progress_allowlist" in sse_frames.__all__
