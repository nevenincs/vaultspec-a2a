"""State replay snapshot models for WebSocket reconnection.

When a client reconnects, it fetches the latest ``ThreadStateSnapshot``
via REST. The ``last_sequence`` field enables gap detection: the client
discards any subsequent WebSocket events with ``sequence <= last_sequence``.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from ...utils.enums import Model, Provider
from .enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    ToolCallStatus,
    ToolKind,
)
from .events import PlanEntry, ToolCallContent, ToolCallLocation


__all__ = [
    "ArtifactSnapshot",
    "ExecutionTaskSnapshot",
    "MessageSnapshot",
    "ThreadStateSnapshot",
    "ToolCallSnapshot",
]


class MessageSnapshot(BaseModel):
    """Fully materialized message in a thread replay."""

    message_id: str
    role: str
    content: str
    agent_id: str | None = None
    timestamp: datetime


class ToolCallSnapshot(BaseModel):
    """Fully materialized tool call (all incremental updates merged)."""

    tool_call_id: str
    title: str
    kind: ToolKind
    status: ToolCallStatus
    locations: list[ToolCallLocation] = Field(default_factory=list)
    content: list[ToolCallContent] = Field(default_factory=list)


class ArtifactSnapshot(BaseModel):
    """Fully materialized file artifact."""

    artifact_id: str
    filename: str
    content: str
    complete: bool


class _PermissionSnapshot(BaseModel):
    """Outstanding permission request in a state snapshot."""

    request_id: str
    description: str
    options: list["_PermissionOptionSnapshot"]
    tool_call: str | None = None


class _PermissionOptionSnapshot(BaseModel):
    """Permission option within a snapshot."""

    option_id: str
    name: str
    kind: PermissionOptionKind


class _AgentSnapshot(BaseModel):
    """Agent state within a thread snapshot."""

    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider | None = None
    model: Model | None = None
    role: str = ""
    display_name: str = ""
    description: str = ""


class ExecutionTaskSnapshot(BaseModel):
    """Normalized execution task used in reconnect snapshots."""

    task_id: str
    name: str
    path: list[str] = Field(default_factory=list)
    has_error: bool = False
    error_type: str | None = None
    interrupt_ids: list[str] = Field(default_factory=list)
    interrupt_types: list[str] = Field(default_factory=list)
    has_nested_state: bool = False
    has_result: bool = False


class ThreadStateSnapshot(BaseModel):
    """Complete thread state for reconnection replay.

    The client fetches this via REST, notes ``last_sequence``, then
    discards any WebSocket events with ``sequence <= last_sequence``.
    """

    thread_id: str
    status: str
    messages: list[MessageSnapshot] = Field(default_factory=list)
    tool_calls: list[ToolCallSnapshot] = Field(default_factory=list)
    pending_permissions: list[_PermissionSnapshot] = Field(default_factory=list)
    artifacts: list[ArtifactSnapshot] = Field(default_factory=list)
    plan: list[PlanEntry] = Field(default_factory=list)
    agents: list[_AgentSnapshot] = Field(default_factory=list)
    last_sequence: int
    checkpoint_id: str | None = None
    checkpoint_created_at: datetime | None = None
    checkpoint_parent_id: str | None = None
    checkpoint_source: str | None = None
    checkpoint_step: int | None = None
    checkpoint_updated_channels: list[str] = Field(default_factory=list)
    pending_write_channels: list[str] = Field(default_factory=list)
    pending_write_count: int = 0
    history_depth: int | None = None
    next_nodes: list[str] = Field(default_factory=list)
    task_count: int = 0
    pending_interrupt_count: int = 0
    execution_tasks: list[ExecutionTaskSnapshot] = Field(default_factory=list)
    snapshot_complete: bool = True
    degraded_reasons: list[str] = Field(default_factory=list)
    replay_status: str = "unknown"
    repair_status: str | None = None
    execution_readiness: str | None = None
    pause_cause: str | None = None
    approval_status: str | None = None
    approval_request_id: str | None = None
