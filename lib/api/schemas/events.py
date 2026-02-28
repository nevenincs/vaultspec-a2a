"""Server-to-client WebSocket event models.

Each model uses a ``Literal`` type discriminator so the top-level
``ServerEvent`` union supports O(1) ``switch`` dispatch on both Python
and TypeScript sides.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ...utils.enums import Model, Provider
from .base import EventEnvelope
from .enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    PlanEntryPriority,
    PlanEntryStatus,
    ServerEventType,
    ToolCallStatus,
    ToolKind,
)


__all__ = [
    # Event models
    "AgentStatusEvent",
    # Component models
    "AgentSummary",
    "ArtifactUpdateEvent",
    "ConnectedEvent",
    "ErrorEvent",
    "HeartbeatEvent",
    "MessageChunkEvent",
    "PermissionOption",
    "PermissionRequestEvent",
    "PlanEntry",
    "PlanUpdateEvent",
    # Union
    "ServerEvent",
    "TeamStatusEvent",
    "ThoughtChunkEvent",
    "ToolCallContent",
    "ToolCallContentDiff",
    "ToolCallContentTerminal",
    "ToolCallContentText",
    "ToolCallLocation",
    "ToolCallStartEvent",
    "ToolCallUpdateEvent",
]


# ---------------------------------------------------------------------------
# Component models (non-event)
# ---------------------------------------------------------------------------


class ToolCallLocation(BaseModel):
    """File location associated with a tool call."""

    path: str
    line: int | None = None


class ToolCallContentText(BaseModel):
    """Plain text content block within a tool call."""

    content_type: Literal["text"] = "text"
    text: str


class ToolCallContentDiff(BaseModel):
    """Diff content block within a tool call."""

    content_type: Literal["diff"] = "diff"
    path: str
    old_text: str | None = None
    new_text: str


class ToolCallContentTerminal(BaseModel):
    """Terminal output content block within a tool call."""

    content_type: Literal["terminal"] = "terminal"
    terminal_id: str


ToolCallContent = Annotated[
    ToolCallContentText | ToolCallContentDiff | ToolCallContentTerminal,
    Field(discriminator="content_type"),
]


class PlanEntry(BaseModel):
    """A single entry in the agent's execution plan."""

    content: str
    status: PlanEntryStatus = PlanEntryStatus.PENDING
    priority: PlanEntryPriority = PlanEntryPriority.MEDIUM


class PermissionOption(BaseModel):
    """A selectable option in a permission request."""

    option_id: str
    name: str
    kind: PermissionOptionKind


class AgentSummary(BaseModel):
    """Lightweight agent descriptor for team status broadcasts."""

    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider
    model: Model
    # ADR-012 §6: metadata extracted from compiled_graph.nodes[node_name].metadata
    role: str = ""
    display_name: str = ""
    description: str = ""


# ---------------------------------------------------------------------------
# Thread-scoped event models (extend EventEnvelope)
# ---------------------------------------------------------------------------


class AgentStatusEvent(EventEnvelope):
    """Agent lifecycle state transition."""

    type: Literal[ServerEventType.AGENT_STATUS] = ServerEventType.AGENT_STATUS
    state: AgentLifecycleState
    node_name: str
    detail: str | None = None


class MessageChunkEvent(EventEnvelope):
    """Streaming agent message token."""

    type: Literal[ServerEventType.MESSAGE_CHUNK] = ServerEventType.MESSAGE_CHUNK
    content: str
    message_id: str
    finish_reason: str | None = None


class ThoughtChunkEvent(EventEnvelope):
    """Streaming agent thought/reasoning token."""

    type: Literal[ServerEventType.THOUGHT_CHUNK] = ServerEventType.THOUGHT_CHUNK
    content: str
    message_id: str


class ToolCallStartEvent(EventEnvelope):
    """A new tool invocation has begun."""

    type: Literal[ServerEventType.TOOL_CALL_START] = ServerEventType.TOOL_CALL_START
    tool_call_id: str
    title: str
    kind: ToolKind
    status: ToolCallStatus = ToolCallStatus.PENDING
    locations: list[ToolCallLocation] = Field(default_factory=list)
    content: list[ToolCallContent] = Field(default_factory=list)


class ToolCallUpdateEvent(EventEnvelope):
    """Incremental update to an in-progress tool call (merge semantics)."""

    type: Literal[ServerEventType.TOOL_CALL_UPDATE] = ServerEventType.TOOL_CALL_UPDATE
    tool_call_id: str
    title: str | None = None
    kind: ToolKind | None = None
    status: ToolCallStatus | None = None
    locations: list[ToolCallLocation] | None = None
    content: list[ToolCallContent] | None = None


class PermissionRequestEvent(EventEnvelope):
    """Agent is requesting user permission to proceed."""

    type: Literal[ServerEventType.PERMISSION_REQUEST] = (
        ServerEventType.PERMISSION_REQUEST
    )
    request_id: str
    description: str
    options: list[PermissionOption]
    tool_call: str | None = None


class ArtifactUpdateEvent(EventEnvelope):
    """Streaming file artifact content."""

    type: Literal[ServerEventType.ARTIFACT_UPDATE] = ServerEventType.ARTIFACT_UPDATE
    artifact_id: str
    filename: str
    content: str
    append: bool = False
    last_chunk: bool = False


class PlanUpdateEvent(EventEnvelope):
    """Full plan state replacement."""

    type: Literal[ServerEventType.PLAN_UPDATE] = ServerEventType.PLAN_UPDATE
    entries: list[PlanEntry]


class TeamStatusEvent(EventEnvelope):
    """Team-wide agent status broadcast."""

    type: Literal[ServerEventType.TEAM_STATUS] = ServerEventType.TEAM_STATUS
    agents: list[AgentSummary]
    active_thread_ids: list[str] = Field(default_factory=list)


class ErrorEvent(EventEnvelope):
    """Server-side error notification."""

    type: Literal[ServerEventType.ERROR] = ServerEventType.ERROR
    code: str
    message: str
    recoverable: bool = True


# ---------------------------------------------------------------------------
# Connection-scoped event models (do NOT extend EventEnvelope)
# ---------------------------------------------------------------------------


class ConnectedEvent(BaseModel):
    """Sent once on WebSocket open; connection-scoped, not thread-scoped."""

    type: Literal[ServerEventType.CONNECTED] = ServerEventType.CONNECTED
    client_id: str
    server_version: str
    active_threads: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class HeartbeatEvent(BaseModel):
    """Periodic keepalive; connection-scoped, not thread-scoped."""

    type: Literal[ServerEventType.HEARTBEAT] = ServerEventType.HEARTBEAT
    timestamp: datetime
    server_uptime_seconds: float
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Discriminated union of all server events
# ---------------------------------------------------------------------------

ServerEvent = Annotated[
    AgentStatusEvent
    | MessageChunkEvent
    | ThoughtChunkEvent
    | ToolCallStartEvent
    | ToolCallUpdateEvent
    | PermissionRequestEvent
    | ArtifactUpdateEvent
    | PlanUpdateEvent
    | TeamStatusEvent
    | ErrorEvent
    | ConnectedEvent
    | HeartbeatEvent,
    Field(discriminator="type"),
]
