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

__all__ = ["MAX_SSE_FRAME_BYTES", "SSE_FRAME_VERSION", "encode_sse_frame"]

SSE_FRAME_VERSION = "v1"

# Hard per-frame byte cap for the encoded SSE frame. Sized to carry ordinary
# progress payloads with headroom while staying far under the engine's 8 MiB
# pass-through cap; an oversized frame degrades to a sentinel (frames are
# droppable, so this loses progress detail, never run authority).
MAX_SSE_FRAME_BYTES = 256 * 1024


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
