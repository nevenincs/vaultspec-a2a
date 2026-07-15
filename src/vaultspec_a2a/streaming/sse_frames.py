"""Versioned, bounded Server-Sent Event frame encoding (ADR R6).

SSE progress frames are non-authoritative and droppable by contract: a client or
the engine reconciles run state from the ``run-status`` verb, never from a relay
frame. Two properties follow, and this module owns both so every emitter shares
them:

- **Versioned.** Each frame carries ``api_version`` so a consumer can fence
  event-shape drift the same way the engine fences its own event schemas. The
  stamp is idempotent — a payload that already declares the version passes
  through unchanged.
- **Bounded.** Each encoded frame is held under a hard byte cap. Because frames
  are droppable, a payload over the cap is replaced by a tiny versioned
  ``progress_dropped`` sentinel rather than emitted or truncated — the stream
  stays within the engine's pass-through limits and never blocks on an oversized
  event, and the consumer learns to catch up from ``run-status``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MAX_SSE_FRAME_BYTES",
    "SSE_FRAME_VERSION",
    "encode_sse_frame",
    "semantic_phase_for_node",
]

SSE_FRAME_VERSION = "v1"

# research_adr structural node -> product-safe semantic authoring phase for
# progress frames. Mirrors the run-status projection vocabulary
# (control.thread_state_service.project_semantic_phase), duplicated here so the
# streaming layer stamps a phase without importing the control layer; run-status
# remains the authoritative phase, these frames are non-authoritative progress.
_RESEARCH_ADR_NODE_PHASE: dict[str, str] = {
    "synthesis": "synthesizing_research",
    "research_review": "reviewing_research",
    "research_gate": "awaiting_research_decision",
    "adr_author": "writing_adr",
    "adr_review": "reviewing_adr",
    "adr_gate": "awaiting_adr_decision",
}


def semantic_phase_for_node(node_name: str) -> str | None:
    """Map a research_adr node name to its semantic authoring phase, or None.

    Returns None for a node that is not part of the research_adr topology (a
    coder node, the supervisor, an empty or end marker), so progress frames only
    carry a phase when one is genuinely known - never a fabricated one.
    """
    node = node_name.removeprefix("mount_")
    if not node or node == "__end__":
        return None
    if node.startswith("research_dispatch"):
        return "researching"
    return _RESEARCH_ADR_NODE_PHASE.get(node)


# Hard per-frame byte cap for the encoded SSE frame. Sized to carry ordinary
# progress payloads with headroom while staying far under the engine's 8 MiB
# pass-through cap; an oversized frame degrades to a sentinel (frames are
# droppable, so this loses progress detail, never run authority).
MAX_SSE_FRAME_BYTES = 256 * 1024


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
