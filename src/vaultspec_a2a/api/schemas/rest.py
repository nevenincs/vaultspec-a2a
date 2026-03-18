"""REST request/response models for the HTTP API.

These models complement the WebSocket protocol by providing idempotent,
retryable endpoints for operations that require guaranteed delivery
(e.g., permission responses) and state queries (thread listing, snapshots).
"""

import re

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from ...core.metadata import ThreadMetadata
from ...utils.enums import Model, Provider
from .enums import AgentLifecycleState, PermissionOptionKind


__all__ = [
    "AgentStatusEntry",
    "CancelThreadResponse",
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
    """Create a new orchestration thread."""

    title: str | None = Field(default=None, max_length=200)
    # 64 KB limit prevents excessive LLM token consumption and memory pressure
    initial_message: str = Field(max_length=65536)
    # NEW: select a team preset by ID (ADR-013 §6)
    team_preset: str | None = Field(default=None, max_length=64)
    # NEW: thread metadata for provenance and context (ADR-014)
    metadata: ThreadMetadata | None = None
    # Optional nickname for the thread (ADR-034). Overrides metadata.nickname
    # when both are set. Allows CLI users to name threads without full metadata.
    nickname: str | None = Field(default=None, max_length=64)
    # None = use team preset default (auto_approve); False = always supervised
    autonomous: bool | None = None

    @field_validator("nickname")
    @classmethod
    def _validate_nickname_slug(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^[a-z0-9][a-z0-9\-]{1,62}[a-z0-9]$", v):
            msg = (
                "nickname must be a lowercase slug "
                "(3-64 chars, [a-z0-9-], "
                "no leading/trailing hyphens)"
            )
            raise ValueError(msg)
        return v


class CreateThreadResponse(BaseModel):
    """Response after successfully creating a thread."""

    thread_id: str
    status: str
    nickname: str | None = None


class CancelThreadResponse(BaseModel):
    """Response after requesting thread cancellation."""

    thread_id: str
    status: str
    cancelled: bool
    accepted: bool = False
    applied: bool = False
    action_status: str = "rejected_invalid_state"
    action_id: str | None = None
    idempotency_key: str | None = None


class SendMessageRequest(BaseModel):
    """Send a user message into an existing thread via REST."""

    # 64 KB limit prevents excessive LLM token consumption and memory pressure
    content: str = Field(max_length=65536)
    agent_id: str | None = Field(default=None, max_length=64)


class SendMessageResponse(BaseModel):
    """Response after accepting a user message (202 Accepted)."""

    status: str
    thread_id: str
    accepted: bool = True
    applied: bool = False
    action_status: str = "accepted_not_applied"
    action_id: str | None = None
    idempotency_key: str | None = None


class ThreadSummary(BaseModel):
    """Lightweight thread descriptor for list endpoints."""

    thread_id: str
    title: str | None = None
    status: str
    repair_status: str | None = None
    execution_readiness: str | None = None
    approval_status: str | None = None
    approval_request_id: str | None = None
    agent_state: AgentLifecycleState | None = None
    team_preset: str | None = None
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
    request_status: str = "pending"


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
    applied: bool = False
    action_status: str = "rejected_invalid_state"
    thread_id: str
    action_id: str | None = None
    idempotency_key: str | None = None
    approval_status: str | None = None


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
