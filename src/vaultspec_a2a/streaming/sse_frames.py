"""Versioned, bounded Server-Sent Event frame encoding.

SSE progress frames are non-authoritative and droppable by contract: a client or
the engine reconciles run state from the ``run-status`` verb, never from a relay
frame. Three properties follow, and this module owns all three so every emitter
shares them:

- **Versioned.** Each frame carries ``api_version`` so a consumer can fence
  event-shape drift the same way the engine fences its own event schemas. The
  stamp is idempotent — a payload that already declares the version passes
  through unchanged.
- **Allowlisted.** The progress channel is a deliberate positive allowlist. A
  content-bearing frame (message/thought token chunk, tool call, artifact
  update) is projected onto its allowlisted fields at the encode boundary, so a
  prompt, document or artifact body, edit diff, or raw provider payload cannot
  cross to a consumer even when a producer relays one; the one permitted
  token-stream field is length-bounded.
- **Bounded.** Each encoded frame is held under a hard byte cap. Because frames
  are droppable, a payload over the cap is replaced by a tiny versioned
  ``progress_dropped`` sentinel rather than emitted or truncated — the stream
  stays within the engine's pass-through limits and never blocks on an oversized
  event, and the consumer learns to catch up from ``run-status``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

# Progress frames stamp the semantic phase from the single shared research_adr
# vocabulary (graph.enums), which run-status also reads - one source of truth,
# not a per-layer copy. Re-exported under the module's public name so callers
# and tests keep importing it from here.
from ..graph.enums import research_adr_semantic_phase as semantic_phase_for_node

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MAX_PROGRESS_CONTENT_CHARS",
    "MAX_SSE_FRAME_BYTES",
    "SSE_FRAME_VERSION",
    "encode_sse_frame",
    "enforce_progress_allowlist",
    "semantic_phase_for_node",
]

SSE_FRAME_VERSION = "v1"


# Hard per-frame byte cap for the encoded SSE frame. Sized to carry ordinary
# progress payloads with headroom while staying far under the engine's 8 MiB
# pass-through cap; an oversized frame degrades to a sentinel (frames are
# droppable, so this loses progress detail, never run authority).
MAX_SSE_FRAME_BYTES = 256 * 1024


# Per-frame character cap for the permitted message/thought token stream. The
# progress channel relays bounded token deltas: a single content-bearing frame's
# text is truncated to this cap so a buggy or hostile producer cannot stream an
# unbounded body through the one permitted content field. Sized to carry ordinary
# token chunks with generous headroom while keeping a single frame small.
MAX_PROGRESS_CONTENT_CHARS = 16 * 1024


# Identity and lifecycle keys that are safe on every progress frame. These carry
# no prompt, document, artifact, diff, or provider payload - only who/when/which.
_ALWAYS_SAFE_KEYS: frozenset[str] = frozenset(
    {
        "api_version",
        "type",
        "event_type",
        "thread_id",
        "agent_id",
        "sequence",
        "timestamp",
        "message_id",
        "semantic_phase",
    }
)


# The positive allowlist for the content-bearing event families - the only frame
# types that can carry a prompt, document/artifact body, edit diff, or raw
# provider payload. For each family only these fields survive (on top of the
# always-safe identity keys); artifact bodies, tool-call content blocks (edit
# diffs and raw provider output), and any unrecognised key are dropped by
# omission, so a forbidden field cannot cross the boundary even if a producer
# adds one. Every other frame type is already body-free by construction and
# passes through untouched.
_POSITIVE_FIELD_ALLOWLIST: dict[str, frozenset[str]] = {
    "message_chunk": frozenset({"content", "finish_reason"}),
    "thought_chunk": frozenset({"content"}),
    "tool_call_start": frozenset(
        {"tool_call_id", "title", "kind", "status", "locations"}
    ),
    "tool_call_update": frozenset(
        {"tool_call_id", "title", "kind", "status", "locations"}
    ),
    "artifact_update": frozenset({"artifact_id", "filename", "append", "last_chunk"}),
}


# The families whose one permitted content field is a token-stream chunk and is
# therefore length-bounded per frame.
_BOUNDED_CONTENT_TYPES: frozenset[str] = frozenset({"message_chunk", "thought_chunk"})


def enforce_progress_allowlist(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Project a content-bearing progress frame onto its positive allowlist.

    A frame whose ``type`` names a content-bearing family (message/thought token
    chunks, tool calls, artifact updates) is rebuilt from only its allowlisted
    fields: artifact bodies, tool-call content blocks (edit diffs and raw
    provider output), and any unrecognised key are dropped by omission, and the
    one permitted token-stream field is truncated to
    :data:`MAX_PROGRESS_CONTENT_CHARS`. Every other frame type is already free of
    prompts, document/artifact bodies, edit diffs, and raw provider payloads by
    construction and is returned unchanged.

    This is the authoritative wire allowlist for the public progress edge; the
    encode boundary applies it to every frame, and upstream projections reuse it
    so the exclusion is enforced independently at more than one layer.
    """
    frame_type = payload.get("type") or payload.get("event_type")
    if not isinstance(frame_type, str):
        return payload
    allowed = _POSITIVE_FIELD_ALLOWLIST.get(frame_type)
    if allowed is None:
        return payload
    permitted = _ALWAYS_SAFE_KEYS | allowed
    projected: dict[str, object] = {
        key: value for key, value in payload.items() if key in permitted
    }
    if frame_type in _BOUNDED_CONTENT_TYPES:
        content = projected.get("content")
        if isinstance(content, str) and len(content) > MAX_PROGRESS_CONTENT_CHARS:
            projected["content"] = content[:MAX_PROGRESS_CONTENT_CHARS]
    return projected


def _stamp_semantic_phase(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Stamp ``semantic_phase`` on a progress frame that names a research_adr node.

    Idempotent: a frame that already declares a phase passes through. Frames
    without a resolvable research_adr node (heartbeats, terminals, coder-run
    frames) are unchanged, so a phase is present only when genuinely known.
    """
    if payload.get("semantic_phase"):
        return payload
    node_name = payload.get("node_name") or payload.get("agent_id")
    if not isinstance(node_name, str) or not node_name:
        return payload
    phase = semantic_phase_for_node(node_name)
    if phase is None:
        return payload
    return {**payload, "semantic_phase": phase}


def _encode(payload: Mapping[str, object], event: str | None) -> bytes:
    """Serialize one payload as a wire SSE frame."""
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    data = json.dumps(payload, separators=(",", ":"))
    lines.extend(f"data: {line}" for line in data.splitlines() or [data])
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def encode_sse_frame(
    payload: Mapping[str, object],
    *,
    event: str | None = None,
    thread_id: str | None = None,
) -> bytes:
    """Encode *payload* as a versioned, bounded SSE frame.

    Stamps ``api_version`` (idempotently) and enforces
    :data:`MAX_SSE_FRAME_BYTES`. A frame over the cap is replaced by a small
    ``progress_dropped`` sentinel naming the dropped event type so the consumer
    knows to reconcile from ``run-status`` rather than silently missing an event.
    """
    versioned = (
        payload
        if payload.get("api_version") == SSE_FRAME_VERSION
        else {"api_version": SSE_FRAME_VERSION, **payload}
    )
    versioned = _stamp_semantic_phase(versioned)
    # Final, authoritative gate: strip forbidden content from every outgoing
    # frame regardless of how it was produced (in-process wire dump or relayed
    # worker payload), so a forbidden body cannot cross the encoded boundary even
    # if an upstream projection is bypassed or buggy.
    versioned = enforce_progress_allowlist(versioned)
    encoded = _encode(versioned, event)
    if len(encoded) <= MAX_SSE_FRAME_BYTES:
        return encoded

    sentinel: dict[str, object] = {
        "api_version": SSE_FRAME_VERSION,
        "type": "progress_dropped",
        "event_type": "progress_dropped",
        "reason": "frame_exceeds_cap",
        "dropped_type": versioned.get("type"),
    }
    if thread_id is not None:
        sentinel["thread_id"] = thread_id
    return _encode(sentinel, "progress_dropped")
