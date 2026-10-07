"""State replay snapshot models for WebSocket reconnection.

When a client reconnects, it fetches the latest ``ThreadStateSnapshot``
via REST. The ``last_sequence`` field enables gap detection: the client
discards any subsequent WebSocket events with ``sequence <= last_sequence``.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from ...graph.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    Provider,
    ToolCallStatus,
    ToolKind,
)
from ...thread.enums import DegradedReason, ThreadStatus
from ...thread.models import PlanEntry
from .events import ToolCallContent, ToolCallLocation

__all__ = [
    "AgentSnapshot",
    "ArtifactSnapshot",
    "ClarificationRequestSnapshot",
    "ExecutionTaskSnapshot",
    "MessageSnapshot",
    "PermissionSnapshot",
    "ThreadStateSnapshot",
    "ToolCallSnapshot",
]


class MessageSnapshot(BaseModel):
    """Fully materialized message in a thread replay."""

    message_id: str
    role: str
    content: str
    agent_id: str | None = None
    # Null for a message recorded before messages carried their production
    # time; never the time the snapshot was read.
    timestamp: datetime | None


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


class PermissionSnapshot(BaseModel):
    """Outstanding permission request in a state snapshot."""

    request_id: str
    description: str
    options: list["PermissionOptionSnapshot"]
    tool_call: str | None = None
    tool_kind: ToolKind | None = None


class ClarificationQuestionSnapshot(BaseModel):
    """Layer 1 equivalent of ``thread.snapshots.ClarificationQuestionData``."""

    id: str
    prompt: str
    kind: str
    required: bool = False
    options: list[str] = Field(default_factory=list)


class ClarificationRequestSnapshot(BaseModel):
    """Layer 1 equivalent of ``thread.snapshots.ClarificationRequestData``.

    A pending mid-run clarification, disclosed on ``run-status`` so a reload
    re-renders the questionnaire from authoritative state alone, never from a
    relay frame.
    """

    request_id: str
    questions: list[ClarificationQuestionSnapshot] = Field(default_factory=list)


class PermissionOptionSnapshot(BaseModel):
    """Permission option within a snapshot."""

    option_id: str
    name: str
    kind: PermissionOptionKind


class AgentSnapshot(BaseModel):
    """Wire projection of the canonical agent descriptor within a snapshot.

    Mirrors ``thread.snapshots.AgentData``.
    """

    thread_id: str
    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider | None = None
    model_name: str | None = None
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
    status: ThreadStatus
    messages: list[MessageSnapshot] = Field(default_factory=list)
    tool_calls: list[ToolCallSnapshot] = Field(default_factory=list)
    pending_permissions: list[PermissionSnapshot] = Field(default_factory=list)
    pending_clarification: ClarificationRequestSnapshot | None = None
    artifacts: list[ArtifactSnapshot] = Field(default_factory=list)
    plan: list[PlanEntry] = Field(default_factory=list)
    agents: list[AgentSnapshot] = Field(default_factory=list)
    model_assignment_digest: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    last_sequence: int
    checkpoint_id: str | None = None
    checkpoint_created_at: datetime | None = None
    checkpoint_parent_id: str | None = Field(
        default=None,
        description=(
            "The parent the current checkpoint records. It may name a "
            "checkpoint that no longer exists: once a run settles, its "
            "superseded history is pruned and only this reference to it "
            "remains. Do not read it as a checkpoint that can be fetched."
        ),
    )
    checkpoint_source: str | None = None
    checkpoint_step: int | None = None
    checkpoint_updated_channels: list[str] = Field(default_factory=list)
    pending_write_channels: list[str] = Field(default_factory=list)
    pending_write_count: int = 0
    history_depth: int | None = Field(
        default=None,
        description=(
            "How deep the current checkpoint's recorded ancestry goes: 2 when "
            "it names a parent, 1 when it is the first of its thread, null "
            "when no checkpoint was read. Recorded ancestry, not stored rows - "
            "a settled run's history is pruned and its depth does not fall."
        ),
    )
    next_nodes: list[str] = Field(default_factory=list)
    task_count: int = 0
    pending_interrupt_count: int = 0
    execution_tasks: list[ExecutionTaskSnapshot] = Field(default_factory=list)
    snapshot_complete: bool = True
    degraded_reasons: list[DegradedReason] = Field(default_factory=list)
    replay_status: str = "unknown"
    repair_status: str | None = None
    execution_readiness: str | None = None
    pause_cause: str | None = None
    approval_status: str | None = None
    approval_request_id: str | None = None
    # The capped, single-line reason this run last failed, sourced from the
    # durable column rather than a live frame so a reloaded panel recovers the
    # same reason a connected client already saw. Declared here because the
    # projection seam is a ``model_validate`` over the domain dataclass, which
    # DROPS a field this model does not name - silently, and without failing.
    # Persisting the reason and never carrying it to the wire left no client
    # able to say why a run failed.
    failure_reason: str | None = None
    # The machine-readable counterpart to the reason above, and declared here
    # for exactly the same reason: this seam is a ``model_validate`` over the
    # domain dataclass, so a field this model does not name is dropped silently
    # and without failing. That is how the reason itself was lost once already.
    # Naming the condition on BOTH sides is what stops the condition following
    # it - a value persisted, carried to the seam, and then quietly discarded is
    # indistinguishable from one that was never recorded.
    provider_condition: str | None = None
    # Why an operation did not take on a run that is STILL ALIVE, as opposed to
    # why a run failed. Named here for the same silent-drop reason as the two
    # above; the paths that write it decline to write a failure reason precisely
    # because the run survives, so this is the only channel their account has.
    repair_reason: str | None = None
    # How many follow-up turns this run holds behind the one it is running.
    # Named here for the same silent-drop reason: the seam validates over the
    # domain dataclass, and a count this model does not declare would read as
    # a run holding nothing, which is the one thing a reloading client cannot
    # check any other way.
    queued_messages: int = 0
