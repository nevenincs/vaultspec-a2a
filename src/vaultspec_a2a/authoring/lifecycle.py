"""Typed decoding of the engine authoring lifecycle SSE stream (ADR R3, P03.S07).

The engine's ``GET /authoring/v1/events`` endpoint replays the durable
transactional outbox as Server-Sent Events. Three frame types appear on the
wire, distinguished by the SSE ``event:`` field:

- ``lifecycle`` - one ``LifecycleEventFeedRecord`` (the authoritative event),
  carrying ``seq``, ``aggregate_kind``/``aggregate_id``, an ``event_kind`` from
  the engine's snake_case vocabulary (e.g. ``approval.resolved``,
  ``proposal.rejected``), and a schema-wrapped ``payload`` whose inner ``data``
  holds the decision-specific fields.
- ``gap`` - an explicit replay-window break (``invalid_last_seq``,
  ``cursor_ahead_of_high_water``, ``replay_window_exceeded``) carrying the
  recovery high-water mark; the consumer falls back to the recovery snapshot.
- ``error`` - a typed store error (e.g. ``authoring_store_unavailable``).

This module is transport-agnostic: it decodes already-split SSE fields into
frames and extracts the reviewer verdict. The pinned verdict vocabulary is
``approved`` / ``rejected`` / ``request_changes`` (the engine's decision strings
``approve`` / ``reject`` / ``request_changes`` mapped onto it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

__all__ = [
    "VERDICT_APPROVED",
    "VERDICT_REJECTED",
    "VERDICT_REQUEST_CHANGES",
    "GapSignal",
    "LifecycleEvent",
    "SseFrame",
    "StreamError",
    "changeset_status_verdict",
    "parse_sse_frame",
    "verdict_from_event",
]

VERDICT_APPROVED = "approved"
VERDICT_REJECTED = "rejected"
VERDICT_REQUEST_CHANGES = "request_changes"

# Engine review-decision strings (`ApprovalDecision`, snake_case) mapped onto the
# pinned a2a verdict vocabulary shared across executors.
_DECISION_TO_VERDICT: dict[str, str] = {
    "approve": VERDICT_APPROVED,
    "reject": VERDICT_REJECTED,
    "request_changes": VERDICT_REQUEST_CHANGES,
}

# Terminal changeset statuses (snake_case `ChangesetStatus`) that map to a
# reviewer verdict for the recovery-snapshot catch-up path. `request_changes`
# has no distinct changeset status (it returns the proposal to draft), so it is
# not recoverable from a status snapshot - only from the live decision event.
_STATUS_TO_VERDICT: dict[str, str] = {
    "approved": VERDICT_APPROVED,
    # An AUTO gate resolves approved AND materializes in one synchronous step, so
    # a still-parked run's proposal is observed terminal as `applied`, never as
    # the transient `approved`. `applied` implies the gate was approved (a
    # changeset cannot apply unresolved), so recovery correlates it to an approved
    # verdict - resuming ONLY still-parked runs, so it is idempotent for a run that
    # already advanced past its gate.
    "applied": VERDICT_APPROVED,
    "rejected": VERDICT_REJECTED,
}

# Lifecycle event_kinds that resolve a review without an explicit `decision`
# field in their payload data.
_RESOLVED_EVENT_KINDS = frozenset({"approval.resolved"})
_REJECTION_EVENT_KINDS = frozenset({"proposal.rejected"})

# Correlation id fields the inner payload data may carry for a review event.
_CORRELATION_KEYS = ("proposal_id", "changeset_id", "approval_id")


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """A decoded authoritative lifecycle event from the outbox feed.

    ``data`` is the inner ``payload.data`` object - the decision-specific fields
    (e.g. ``decision``, ``comment``, ``proposal_id``), not the schema wrapper.
    """

    seq: int
    event_kind: str
    aggregate_kind: str
    aggregate_id: str
    data: dict[str, Any]

    def correlation_ids(self) -> set[str]:
        """Return every engine id this event could be correlated to a run by.

        The aggregate id addresses the event's own aggregate (changeset, proposal
        or approval); the payload data may additionally name the proposal and
        changeset ids. A parked run is matched when any of these intersect its
        recorded ``authoring_proposal_ids`` / ``authoring_changeset_ids``.
        """
        ids: set[str] = set()
        if self.aggregate_id:
            ids.add(self.aggregate_id)
        for key in _CORRELATION_KEYS:
            value = self.data.get(key)
            if isinstance(value, str) and value:
                ids.add(value)
        return ids


@dataclass(frozen=True, slots=True)
class GapSignal:
    """An explicit replay-window break; the consumer must fall back to recovery."""

    reason: str
    latest_outbox_seq: int | None
    next_recovery_seq: int | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StreamError:
    """A typed store-side stream error frame."""

    error_kind: str
    error: str


SseFrame = LifecycleEvent | GapSignal | StreamError


def _as_int(value: Any) -> int | None:
    """Coerce a JSON number to int, rejecting bools and non-numerics."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def parse_sse_frame(event_type: str, data: str) -> SseFrame | None:
    """Decode one SSE frame into a typed :data:`SseFrame`, or ``None`` if unusable.

    ``event_type`` is the SSE ``event:`` field (defaulting to ``message`` when the
    server omits it); ``data`` is the concatenated ``data:`` payload. A frame
    whose JSON is malformed or whose type is unrecognised returns ``None`` so the
    consumer can skip it without crashing.
    """
    try:
        payload = json.loads(data)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    if event_type == "lifecycle":
        return _lifecycle_from_record(payload)
    if event_type == "gap":
        return GapSignal(
            reason=str(payload.get("reason", "unknown")),
            latest_outbox_seq=_as_int(payload.get("latest_outbox_seq")),
            next_recovery_seq=(
                _as_int(payload.get("next_recovery_seq"))
                or _as_int(payload.get("next_seq"))
            ),
            raw=payload,
        )
    if event_type == "error":
        return StreamError(
            error_kind=str(payload.get("error_kind", "unknown")),
            error=str(payload.get("error", "")),
        )
    return None


def _lifecycle_from_record(record: dict[str, Any]) -> LifecycleEvent | None:
    """Build a :class:`LifecycleEvent` from a lifecycle feed record dict."""
    seq = _as_int(record.get("seq"))
    if seq is None:
        return None
    inner: dict[str, Any] = {}
    payload = record.get("payload")
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            inner = data
    return LifecycleEvent(
        seq=seq,
        event_kind=str(record.get("event_kind", "")),
        aggregate_kind=str(record.get("aggregate_kind", "")),
        aggregate_id=str(record.get("aggregate_id", "")),
        data=inner,
    )


def _notes(event: LifecycleEvent) -> str | None:
    """Extract the reviewer comment to thread through as resume ``notes``."""
    comment = event.data.get("comment")
    return comment if isinstance(comment, str) and comment else None


def verdict_from_event(event: LifecycleEvent) -> tuple[str, str | None] | None:
    """Return ``(verdict, notes)`` for a resolving event, or ``None`` otherwise.

    An explicit ``decision`` field in the payload data wins (it distinguishes
    ``request_changes`` from a plain approval). Absent that, ``approval.resolved``
    reads as approved and ``proposal.rejected`` as rejected. Non-resolving events
    (``approval.requested``, validation updates, etc.) return ``None`` - they
    park the run rather than resume it.
    """
    decision = event.data.get("decision")
    if isinstance(decision, str):
        verdict = _DECISION_TO_VERDICT.get(decision)
        if verdict is not None:
            return verdict, _notes(event)
    if event.event_kind in _REJECTION_EVENT_KINDS:
        return VERDICT_REJECTED, _notes(event)
    if event.event_kind in _RESOLVED_EVENT_KINDS:
        return VERDICT_APPROVED, _notes(event)
    return None


def changeset_status_verdict(status: str) -> str | None:
    """Map a terminal changeset status to a verdict for recovery catch-up.

    ``approved`` and ``applied`` both map to an approved verdict (an ``applied``
    changeset was necessarily approved - the AUTO gate resolves-and-applies in one
    step, so a still-parked run is observed terminal as ``applied``); ``rejected``
    maps to a rejected verdict. Returns ``None`` for non-terminal or non-verdict
    statuses (draft, generating, needs_review, ...), which carry no reviewer
    decision to resume on.
    """
    return _STATUS_TO_VERDICT.get(status)
