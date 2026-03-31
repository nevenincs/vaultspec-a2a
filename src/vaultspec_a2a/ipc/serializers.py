"""IPC serialization helpers shared between gateway and worker (D-01)."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from ..graph.events import (
    AgentStatus,
    ArtifactUpdate,
    ErrorOccurred,
    MessageChunk,
    PermissionRequest,
    PlanUpdate,
    TeamStatus,
    ThoughtChunk,
    ToolCallStart,
    ToolCallUpdate,
)

if TYPE_CHECKING:
    from ..streaming.aggregator import SequencedEvent

__all__ = ["sequenced_to_dict"]


def _event_type(event: object) -> str | None:
    """Return the stable wire event type for a domain event."""
    match event:
        case AgentStatus():
            return "agent_status"
        case ArtifactUpdate():
            return "artifact_update"
        case ErrorOccurred():
            return "error"
        case MessageChunk():
            return "message_chunk"
        case PermissionRequest():
            return "permission_request"
        case PlanUpdate():
            return "plan_update"
        case TeamStatus():
            return "team_status"
        case ThoughtChunk():
            return "thought_chunk"
        case ToolCallStart():
            return "tool_call_start"
        case ToolCallUpdate():
            return "tool_call_update"
        case _:
            return None


def sequenced_to_dict(sequenced: SequencedEvent) -> dict:
    """Serialise a ``SequencedEvent`` to a plain dict (for bridge relay)."""
    d = asdict(sequenced.event)
    if event_type := _event_type(sequenced.event):
        d["type"] = event_type
        d["event_type"] = event_type
    d["sequence"] = sequenced.sequence
    return d
