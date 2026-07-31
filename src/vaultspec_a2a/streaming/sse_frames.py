"""Versioned, bounded Server-Sent Event frame encoding.

SSE progress frames are non-authoritative and droppable by contract: a client or
the engine reconciles run state from the ``run-status`` verb, never from a relay
frame. Three properties follow, and this module owns all three so every emitter
shares them:

- **Versioned.** Each frame carries ``api_version`` so a consumer can fence
  event-shape drift the same way the engine fences its own event schemas. The
  stamp is idempotent — a payload that already declares the version passes
  through unchanged.
- **Allowlisted.** The progress channel is a CLOSED per-event catalog. Every
  frame type the product emits is enumerated here with an explicit per-field
  allowlist and explicit bounds on its text fields, and a frame type absent from
  the catalog is projected onto the always-safe identity keys rather than passed
  through. A prompt, document or artifact body, edit diff, or raw provider
  payload therefore cannot cross to a consumer even when a producer relays one,
  and neither can a field of a type nobody enumerated. Projection is by omission
  and truncation, never refusal: frames are droppable, so degrading an
  unrecognised frame to its identity keys keeps the most useful signal, whereas
  refusing it would turn additive producer evolution into silent loss.
- **Bounded.** Each encoded frame is held under a hard byte cap. Because frames
  are droppable, a payload over the cap is replaced by a tiny versioned
  ``progress_dropped`` sentinel rather than emitted or truncated — the stream
  stays within the engine's pass-through limits and never blocks on an oversized
  event, and the consumer learns to catch up from ``run-status``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeGuard

# Progress frames stamp the semantic phase from the single shared research_adr
# vocabulary (graph.enums), which run-status also reads - one source of truth,
# not a per-layer copy. Re-exported under the module's public name so callers
# and tests keep importing it from here.
from ..graph.enums import research_adr_semantic_phase as semantic_phase_for_node

# The wire event-type key pair is owned by ``thread.snapshots`` - the one layer
# every producer and consumer of a relayed payload can import. Reading the frame
# type through it keeps this catalog and the relay predicates on one rule.
from ..thread.snapshots import wire_event_type

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


# Sentinel returned by a field spec when the supplied value cannot be projected
# (wrong shape for the declared field). Projection is by omission: the key is
# left out of the rebuilt frame rather than the frame being refused.
_OMIT: Final = object()


@dataclass(frozen=True, slots=True)
class _Text:
    """A bounded text field. Over-cap text is truncated, never refused."""

    max_chars: int

    def project(self, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return _OMIT
        return value[: self.max_chars]


@dataclass(frozen=True, slots=True)
class _Flag:
    """A boolean field."""

    def project(self, value: object) -> object:
        if value is None:
            return None
        return value if isinstance(value, bool) else _OMIT


@dataclass(frozen=True, slots=True)
class _Number:
    """A numeric field (integral or fractional)."""

    def project(self, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return _OMIT
        return value


@dataclass(frozen=True, slots=True)
class _Integer:
    """An integral field."""

    def project(self, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            return _OMIT
        return value


@dataclass(frozen=True, slots=True)
class _TextList:
    """A bounded list of bounded strings."""

    max_items: int
    max_chars: int

    def project(self, value: object) -> object:
        if value is None:
            return None
        if not _is_item_sequence(value):
            return _OMIT
        return [
            item[: self.max_chars]
            for item in value[: self.max_items]
            if isinstance(item, str)
        ]


@dataclass(frozen=True, slots=True)
class _ObjectList:
    """A bounded list of objects, each rebuilt field-by-field from *fields*.

    Rebuilding is what makes the catalog hold inside a list: an item is never
    forwarded whole, so a key nobody enumerated cannot ride a nested object
    across the boundary.
    """

    max_items: int
    fields: Mapping[str, _FieldSpec]

    def project(self, value: object) -> object:
        if value is None:
            return None
        if not _is_item_sequence(value):
            return _OMIT
        rebuilt: list[object] = []
        for item in value[: self.max_items]:
            entry = _string_keyed(item)
            if entry is not None:
                rebuilt.append(_project_fields(entry, self.fields))
        return rebuilt


type _FieldSpec = _Text | _Flag | _Number | _Integer | _TextList | _ObjectList


def _is_item_sequence(value: object) -> TypeGuard[Sequence[object]]:
    """Whether *value* is a sequence of items rather than a text scalar."""
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _string_keyed(source: object) -> dict[str, object] | None:
    """Narrow a nested relay item to its string-keyed entries, or ``None``.

    A relayed payload's key type is not known statically, so the narrowing
    belongs here rather than at the call site. The catalog only ever probes its
    own string keys, so discarding a non-string key loses nothing a later lookup
    could have matched, and a non-mapping item has no fields to rebuild at all.
    """
    if not isinstance(source, Mapping):
        return None
    return {key: value for key, value in source.items() if isinstance(key, str)}


def _project_fields(
    source: Mapping[str, object], fields: Mapping[str, _FieldSpec]
) -> dict[str, object]:
    """Rebuild *source* from *fields* alone, dropping everything unenumerated.

    The iteration is over the catalog rather than the payload, so an
    unrecognised key has no path into the result.
    """
    projected: dict[str, object] = {}
    for key, spec in fields.items():
        if key not in source:
            continue
        value = spec.project(source[key])
        if value is not _OMIT:
            projected[key] = value
    return projected


# Enum-valued fields are bounded as text rather than checked against their
# member set: an unrecognised member is a producer that moved ahead of this
# catalog, and dropping it would be the refusal semantics the channel rejects.
_ENUM = _Text(64)

# Fields shared verbatim by the two tool-call frame types, declared once.
_TOOL_CALL_FIELDS: dict[str, _FieldSpec] = {
    "tool_call_id": _Text(128),
    "title": _Text(256),
    "kind": _ENUM,
    "status": _ENUM,
    # ``content`` is deliberately absent: it is the tool-call content block
    # carrying edit diffs and raw provider output, which the progress channel
    # never relays.
    "locations": _ObjectList(32, {"path": _Text(512), "line": _Integer()}),
}


# The closed per-event catalog: every frame type that carries content to a
# subscriber, with the fields that survive projection and their bounds. A field
# absent from an entry (an artifact body, a tool-call content block, the
# free-form ``metadata`` dict every envelope carries) is dropped by omission,
# and a frame type absent from the catalog keeps only the always-safe identity
# keys.
#
# Two emitted types are deliberately absent, and their absence is the design
# rather than an oversight - the entry below is the record of that, since a
# reader finding an emitted type missing would otherwise reasonably read it as a
# gap:
#
# ``execution_state_projection`` is consumed at the relay seam and never reaches
# a subscriber queue, so enumerating it would grant its fields transit they
# should not have; if one ever leaks, the closed default degrading it to
# identity keys is the correct outcome.
#
# ``graph_registered`` does travel the relay, and does degrade to identity keys.
# Its payload is consumed server-side by the aggregator BEFORE projection and
# resurfaces through catalogued team-status fields, and no consumer reads the
# frame itself, so the loss is equivalent rather than a regression. It is left
# uncatalogued rather than enumerated because nothing on the subscriber side
# needs it; that judgement should be revisited if a consumer ever does.
_PROGRESS_CATALOG: dict[str, dict[str, _FieldSpec]] = {
    "message_chunk": {
        "content": _Text(MAX_PROGRESS_CONTENT_CHARS),
        "finish_reason": _Text(64),
    },
    "thought_chunk": {"content": _Text(MAX_PROGRESS_CONTENT_CHARS)},
    "tool_call_start": _TOOL_CALL_FIELDS,
    "tool_call_update": _TOOL_CALL_FIELDS,
    "artifact_update": {
        "artifact_id": _Text(256),
        "filename": _Text(256),
        "append": _Flag(),
        "last_chunk": _Flag(),
    },
    "agent_status": {
        "state": _ENUM,
        "node_name": _Text(128),
        "detail": _Text(256),
    },
    "team_status": {
        "active_thread_ids": _TextList(64, 128),
        "agents": _ObjectList(
            64,
            {
                "agent_id": _Text(63),
                "state": _ENUM,
                "node_name": _Text(128),
                "provider": _Text(64),
                "model": _Text(128),
                "role": _Text(64),
                "display_name": _Text(128),
                "description": _Text(256),
            },
        ),
    },
    "error": {
        "code": _Text(64),
        "message": _Text(512),
        "recoverable": _Flag(),
    },
    "thread_terminal": {
        "status": _ENUM,
        "replay": _Flag(),
        "error_detail": _Text(512),
    },
    "heartbeat": {"server_uptime_seconds": _Number()},
    "connected": {
        "client_id": _Text(128),
        "server_version": _Text(64),
        "active_threads": _TextList(64, 128),
    },
    "stream_rejected": {"reason": _Text(64)},
    "progress_dropped": {"reason": _Text(64), "dropped_type": _Text(64)},
    "permission_request": {
        "request_id": _Text(128),
        "tool_call": _Text(128),
        "tool_kind": _ENUM,
        "description": _Text(512),
        "options": _ObjectList(
            16, {"option_id": _Text(64), "name": _Text(128), "kind": _ENUM}
        ),
    },
    # A plan entry's ``content`` is model-authored plan text - document-body
    # adjacent, and nothing consumes it - so only its classification survives.
    "plan_update": {"entries": _ObjectList(64, {"status": _ENUM, "priority": _ENUM})},
}


def enforce_progress_allowlist(
    payload: Mapping[str, object],
) -> Mapping[str, object]:
    """Project a progress frame onto the closed per-event catalog.

    The frame is rebuilt from the always-safe identity keys plus the fields its
    ``type`` enumerates in :data:`_PROGRESS_CATALOG`, with each text field
    truncated to its declared cap and each list bounded and rebuilt item by
    item. A frame whose type is absent from the catalog - or that names no type
    at all - keeps only the identity keys. Nothing is refused: prompts, document
    and artifact bodies, edit diffs, raw provider payloads, the free-form
    ``metadata`` dict, and any unrecognised key leave by omission instead.

    This is the authoritative wire catalog for the public progress edge. The
    encode boundary applies it to every outgoing frame, and the upstream relay
    projection calls this same function, so the two layers cannot disagree.
    """
    frame_type = wire_event_type(payload)
    projected: dict[str, object] = {
        key: value for key, value in payload.items() if key in _ALWAYS_SAFE_KEYS
    }
    fields = _PROGRESS_CATALOG.get(frame_type)
    if fields is not None:
        projected.update(_project_fields(payload, fields))
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
    # Final, authoritative gate: project every outgoing frame onto the catalog
    # regardless of how it was produced (in-process wire dump or relayed worker
    # payload), so a forbidden body cannot cross the encoded boundary even if an
    # upstream projection call site is bypassed. The catalog itself is one
    # deliberately shared authority rather than a per-layer copy, so this layer
    # backstops a missing call, not a gap in the catalog.
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
