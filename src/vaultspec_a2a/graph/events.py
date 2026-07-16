"""Domain event dataclasses for the graph orchestration layer.

These are plain ``@dataclass`` types (NOT Pydantic) that represent the
aggregator's output in domain terms.  A separate adapter in ``api/`` translates
them into wire-protocol schemas for WebSocket delivery.

Core never imports from ``api.schemas`` — the dependency arrow points outward.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import (
    AgentLifecycleState,
    PermissionType,
    ToolCallStatus,
    ToolKind,
)

__all__ = [
    "AgentStatus",
    "ArtifactUpdate",
    "DomainEvent",
    "ErrorOccurred",
    "MessageChunk",
    "PermissionRequest",
    "PlanUpdate",
    "TeamStatus",
    "ThoughtChunk",
    "ToolCallStart",
    "ToolCallUpdate",
]


@dataclass
class DomainEvent:
    """Base class for all domain events emitted by the aggregator."""

    thread_id: str
    agent_id: str
    timestamp: float


@dataclass
class MessageChunk(DomainEvent):
    """Streaming agent message token."""

    content: str
    message_id: str
    finish_reason: str | None = None


@dataclass
class ThoughtChunk(DomainEvent):
    """Streaming agent thought/reasoning token."""

    content: str
    message_id: str


@dataclass
class ToolCallStart(DomainEvent):
    """A new tool invocation has begun."""

    tool_call_id: str
    title: str
    kind: ToolKind
    status: ToolCallStatus = ToolCallStatus.PENDING
    locations: list[dict[str, str | int | None]] = field(default_factory=list)
    content: list[dict[str, str | None]] = field(default_factory=list)


@dataclass
class ToolCallUpdate(DomainEvent):
    """Incremental update to an in-progress tool call (merge semantics)."""

    tool_call_id: str
    title: str | None = None
    kind: ToolKind | None = None
    status: ToolCallStatus | None = None
    locations: list[dict[str, str | int | None]] | None = None
    content: list[dict[str, str | None]] | None = None


@dataclass
class PermissionRequest(DomainEvent):
    """Agent is requesting user permission to proceed."""

    request_id: str
    description: str
    permission_type: PermissionType = PermissionType.TOOL_PERMISSION
    options: list[dict[str, str]] = field(default_factory=list)
    tool_call: str | None = None
    tool_kind: ToolKind | None = None


@dataclass
class PlanUpdate(DomainEvent):
    """Full plan state replacement."""

    entries: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ArtifactUpdate(DomainEvent):
    """Streaming file artifact content."""

    artifact_id: str
    filename: str
    content: str
    append: bool = False
    last_chunk: bool = False


@dataclass
class AgentStatus(DomainEvent):
    """Agent lifecycle state transition."""

    state: AgentLifecycleState
    node_name: str
    detail: str | None = None


@dataclass
class TeamStatus(DomainEvent):
    """Team-wide agent status broadcast."""

    agents: list[dict[str, str]] = field(default_factory=list)
    active_thread_ids: list[str] = field(default_factory=list)


@dataclass
class ErrorOccurred(DomainEvent):
    """Server-side error notification."""

    code: str
    message: str
    recoverable: bool = True
