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


def _event_type(event: object) -> str | None:
    """Return the stable wire event type for a domain event.

    Every event a worker broadcasts MUST have a case here. An event that falls
    through relays with no ``type`` at all, and the gateway's closed catalog then
    projects an untyped frame onto the always-safe identity keys - so the frame
    reaches subscribers stripped of everything that made it meaningful, while the
    worker-side emission looks perfectly healthy. Nothing raises, and an
    in-process test of the emitter passes, because the loss happens on the far
    side of the IPC boundary. Adding an event kind without adding it here is
    therefore silent, and is exactly how the clarification nudge shipped
    undeliverable.
    """
    match event:
        case AgentStatus():
            return ServerEventType.AGENT_STATUS
        case ArtifactUpdate():
            return ServerEventType.ARTIFACT_UPDATE
        case ClarificationPending():
            return ServerEventType.CLARIFICATION_PENDING
        case ErrorOccurred():
            return ServerEventType.ERROR
        case MessageChunk():
            return ServerEventType.MESSAGE_CHUNK
        case PermissionRequest():
            return ServerEventType.PERMISSION_REQUEST
        case PlanUpdate():
            return ServerEventType.PLAN_UPDATE
        case TeamStatus():
            return ServerEventType.TEAM_STATUS
        case ThoughtChunk():
            return ServerEventType.THOUGHT_CHUNK
        case ToolCallStart():
            return ServerEventType.TOOL_CALL_START
        case ToolCallUpdate():
            return ServerEventType.TOOL_CALL_UPDATE
        case _:
            return None


def sequenced_to_dict(sequenced: SequencedEvent) -> dict:
    """Serialise a ``SequencedEvent`` to a plain dict (for bridge relay)."""
    d = asdict(sequenced.event)
    if event_type := _event_type(sequenced.event):
        d["type"] = event_type
        d = normalize_wire_event_type(d)
    d["sequence"] = sequenced.sequence
    return d
