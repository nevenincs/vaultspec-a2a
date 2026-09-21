"""IPC serialization helpers shared between gateway and worker."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from ..graph.enums import ServerEventType
from ..graph.events import (
    AgentStatus,
    ArtifactUpdate,
    ClarificationPending,
    ErrorOccurred,
    MessageChunk,
    PermissionRequest,
    PlanUpdate,
    TeamStatus,
    ThoughtChunk,
    ToolCallStart,
    ToolCallUpdate,
)
from ..thread.snapshots import normalize_wire_event_type

if TYPE_CHECKING:
    from ..streaming.types import SequencedEvent

__all__ = ["sequenced_to_dict"]

_EVENT_TYPES: tuple[tuple[type[object], ServerEventType], ...] = (
    (AgentStatus, ServerEventType.AGENT_STATUS),
    (ArtifactUpdate, ServerEventType.ARTIFACT_UPDATE),
    (ClarificationPending, ServerEventType.CLARIFICATION_PENDING),
    (ErrorOccurred, ServerEventType.ERROR),
    (MessageChunk, ServerEventType.MESSAGE_CHUNK),
    (PermissionRequest, ServerEventType.PERMISSION_REQUEST),
    (PlanUpdate, ServerEventType.PLAN_UPDATE),
    (TeamStatus, ServerEventType.TEAM_STATUS),
    (ThoughtChunk, ServerEventType.THOUGHT_CHUNK),
    (ToolCallStart, ServerEventType.TOOL_CALL_START),
    (ToolCallUpdate, ServerEventType.TOOL_CALL_UPDATE),
)


def _event_type(event: object) -> str | None:
    """Return the stable wire event type for a domain event.

    Every event a worker broadcasts MUST have an entry in ``_EVENT_TYPES``.
    An event that falls through relays with no ``type`` reaches the gateway's
    closed catalog, which projects only the always-safe identity keys - so the frame
    reaches subscribers stripped of everything that made it meaningful, while the
    worker-side emission looks perfectly healthy. Nothing raises, and an
    in-process test of the emitter passes, because the loss happens on the far
    side of the IPC boundary. Adding an event kind without adding it here is
    therefore silent, and is exactly how the clarification nudge shipped
    undeliverable.
    """
    for event_class, wire_type in _EVENT_TYPES:
        if isinstance(event, event_class):
            return wire_type
    return None


def sequenced_to_dict(sequenced: SequencedEvent) -> dict[str, object]:
    """Serialise a ``SequencedEvent`` to a plain dict (for bridge relay)."""
    d = asdict(sequenced.event)
    if event_type := _event_type(sequenced.event):
        d["type"] = event_type
        d = normalize_wire_event_type(d)
    d["sequence"] = sequenced.sequence
    return d
