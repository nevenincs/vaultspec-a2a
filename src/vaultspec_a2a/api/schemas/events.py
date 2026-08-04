"""Server-to-client WebSocket event models.

Each model uses a ``Literal`` type discriminator so the top-level
``ServerEvent`` union supports O(1) ``switch`` dispatch on both Python
and TypeScript sides.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

from ...graph.enums import (
    AgentLifecycleState,
    Model,
    PermissionOptionKind,
    Provider,
    ServerEventType,
    ToolCallStatus,
    ToolKind,
)
from ...thread.models import PlanEntry
from .base import EventEnvelope

__all__ = [
    "MAX_PERMISSION_DESCRIPTION_CHARS",
    "MAX_TOOL_CALL_CHARS",
    # Event models
    "AgentStatusEvent",
    # Component models
    "AgentSummary",
    "ArtifactUpdateEvent",
    "ClarificationPendingEvent",
    "ErrorEvent",
    "HeartbeatEvent",
    "MessageChunkEvent",
    "PermissionOption",
    "PermissionRequestEvent",
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
# Bounded caller-controlled text
# ---------------------------------------------------------------------------

#: Cap on a streamed permission description, matched deliberately to the 4096
#: the durable control writer already truncates to before persisting the same
#: text. Matching is the point rather than a coincidence: the streamed frame and
#: the row a reload replays from must not disagree about how much of a
#: description exists, or a panel would show text live that vanishes on refresh.
MAX_PERMISSION_DESCRIPTION_CHARS = 4096

#: Cap on the tool identifier a permission request names. Tool names are
#: identifiers, sized alongside the other bounded identifiers on this wire.
MAX_TOOL_CALL_CHARS = 256


def _bounded(limit: int) -> BeforeValidator:
    """Build a validator that TRUNCATES over-long text instead of refusing it.

    These fields carry content an LLM can be induced to produce, so they need a
    bound. The bound has to shorten rather than reject, which is the opposite of
    the request schemas in ``gateway.py``: those face inbound callers, where
    refusing a malformed request is the correct and safe answer. These models
    are the outbound projection, built in ``api/event_adapter.py`` from an
    already-accepted domain event with no error handling around the
    construction. A ``max_length`` there would turn an over-long description
    into a raised ``ValidationError``, and the permission frame it killed is the
    only thing telling the operator that a run is waiting on them — so the run
    would hang, unattended, on a cap meant to protect it. Truncating keeps the
    frame deliverable and the bound enforced.
    """

    def _truncate(value: object) -> object:
        if isinstance(value, str) and len(value) > limit:
            return value[:limit]
        return value

    return BeforeValidator(_truncate)


BoundedDescription = Annotated[
    str,
    _bounded(MAX_PERMISSION_DESCRIPTION_CHARS),
    Field(max_length=MAX_PERMISSION_DESCRIPTION_CHARS),
]
BoundedToolCall = Annotated[
    str, _bounded(MAX_TOOL_CALL_CHARS), Field(max_length=MAX_TOOL_CALL_CHARS)
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


class PermissionOption(BaseModel):
    """A selectable option in a permission request."""

    option_id: str
    name: str
    kind: PermissionOptionKind


class AgentSummary(BaseModel):
    """Wire projection of the canonical agent descriptor for team broadcasts.

    Mirrors ``thread.snapshots.AgentData``, which is the one place the field set
    is decided; provider/model stay optional because an agent can be observed
    before its model assignment resolves.

    ``model`` additionally stays ``None`` for the whole life of a FROZEN run:
    that path resolves a concrete catalog entry instead of a capability tier, so
    there is no tier to report. ``model_name`` carries what such a run actually
    executed and is the field to read when asking which model ran.
    """

    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider | None = None
    model: Model | None = None
    model_name: str | None = None
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
    description: BoundedDescription
    options: list[PermissionOption]
    tool_call: BoundedToolCall | None = None
    tool_kind: ToolKind | None = None


class ClarificationPendingEvent(EventEnvelope):
    """A run is parked on a questionnaire; re-read run-status to render it.

    The narrowest event on this channel by design. It carries the request id and
    the envelope's own thread id, and nothing a client could mistake for the
    questions themselves - no prompts, no options, no kinds. A client that could
    render the questionnaire from this frame would be rendering from a channel
    that is permitted to drop frames, which is precisely the recovery bug the
    authoritative status disclosure exists to prevent.
    """

    type: Literal[ServerEventType.CLARIFICATION_PENDING] = (
        ServerEventType.CLARIFICATION_PENDING
    )
    request_id: str


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
    | ClarificationPendingEvent
    | ArtifactUpdateEvent
    | PlanUpdateEvent
    | TeamStatusEvent
    | ErrorEvent
    | HeartbeatEvent,
    Field(discriminator="type"),
]
