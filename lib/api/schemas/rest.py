"""REST request/response models for the HTTP API.

These models complement the WebSocket protocol by providing idempotent,
retryable endpoints for operations that require guaranteed delivery
(e.g., permission responses) and state queries (thread listing, snapshots).
"""

from datetime import datetime

from pydantic import BaseModel, Field

from ...core.metadata import ThreadMetadata
from ...utils.enums import Model, Provider
from .enums import AgentLifecycleState, PermissionOptionKind


__all__ = [
    "AgentStatusEntry",
    "CreateThreadRequest",
    "CreateThreadResponse",
    "PendingPermission",
    "PermissionResponseRequest",
    "PermissionResponseResult",
    "SendMessageRequest",
    "SendMessageResponse",
    "TeamPresetSummary",
    "TeamPresetsResponse",
    "TeamStatusResponse",
    "ThreadListResponse",
    "ThreadSummary",
]


class CreateThreadRequest(BaseModel):
    """Create a new orchestration thread.

    **Model Selection Policy**: When ``team_preset`` is specified, the ``provider``
    and ``model`` fields are ignored. Models are defined statically in the team
    TOML configuration (per ADR-013 §2.3). Per-request model overrides are not
    supported for team presets. To customize models for a team, create a custom
    team preset in the workspace or modify bundled presets.
    """

    title: str | None = Field(default=None, max_length=200)
    # 64 KB limit prevents excessive LLM token consumption and memory pressure
    initial_message: str = Field(max_length=65536)
    # NEW: select a team preset by ID (ADR-013 §6)
    team_preset: str | None = Field(default=None, max_length=64)
    # NEW: thread metadata for provenance and context (ADR-014)
    metadata: ThreadMetadata | None = None
    # NEW — skip interrupts for headless runs
    autonomous: bool = False
    # DEPRECATED: kept for backward compat, ignored if team_preset is set
    provider: Provider | None = None
    model: Model | None = None


class CreateThreadResponse(BaseModel):
    """Response after successfully creating a thread."""

    thread_id: str
    status: str
    nickname: str | None = None


class SendMessageRequest(BaseModel):
    """Send a user message into an existing thread via REST."""

    # 64 KB limit prevents excessive LLM token consumption and memory pressure
    content: str = Field(max_length=65536)
    agent_id: str | None = Field(default=None, max_length=64)


class SendMessageResponse(BaseModel):
    """Response after accepting a user message (202 Accepted)."""

    status: str
    thread_id: str


class ThreadSummary(BaseModel):
    """Lightweight thread descriptor for list endpoints."""

    thread_id: str
    title: str | None = None
    status: str
    agent_state: AgentLifecycleState | None = None
    created_at: datetime
    updated_at: datetime
    # ADR-014: metadata summary fields for UI thread list
    nickname: str | None = None
    feature_tag: str | None = None
    source_branch: str | None = None
    callee: str | None = None


class ThreadListResponse(BaseModel):
    """Paginated thread listing."""

    threads: list[ThreadSummary]
    total: int


class AgentStatusEntry(BaseModel):
    """Agent status within a team status response."""

    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider | None = None
    model: Model | None = None
    role: str = ""
    display_name: str = ""
    description: str = ""


class PendingPermission(BaseModel):
    """Outstanding permission request summary."""

    request_id: str
    thread_id: str
    description: str


class TeamStatusResponse(BaseModel):
    """Current team status snapshot via REST."""

    agents: list[AgentStatusEntry]
    active_threads: list[str]
    pending_permissions: list[PendingPermission]


class PermissionResponseRequest(BaseModel):
    """Submit a permission response via REST (guaranteed delivery)."""

    option_id: str
    # Forward-compatibility: ``kind`` is accepted but not yet acted upon by the
    # endpoint handler.  It is preserved here so that future routing logic (e.g.
    # dispatching ``ALLOW_ALWAYS`` vs ``ALLOW_ONCE`` to different persistence
    # paths) can read it without a breaking schema change.
    kind: PermissionOptionKind | None = None


class PermissionResponseResult(BaseModel):
    """Result of submitting a permission response."""

    request_id: str
    accepted: bool
    thread_id: str


class TeamPresetSummary(BaseModel):
    """Lightweight team preset descriptor for the team picker UI (ADR-013 §6)."""

    id: str
    display_name: str
    description: str
    topology: str
    worker_count: int


class TeamPresetsResponse(BaseModel):
    """Response for GET /teams: list of available team presets (ADR-013 §6)."""

    presets: list[TeamPresetSummary]
