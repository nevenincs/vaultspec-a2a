"""REST request/response models for the HTTP API.

These models complement the WebSocket protocol by providing idempotent,
retryable endpoints for operations that require guaranteed delivery
(e.g., permission responses) and state queries (thread listing, snapshots).
"""

from datetime import datetime

from pydantic import BaseModel

from lib.utils.enums import Model, Provider

from .enums import AgentLifecycleState, PermissionOptionKind


__all__ = [
    "CreateThreadRequest",
    "CreateThreadResponse",
    "PermissionResponseRequest",
    "PermissionResponseResult",
    "SendMessageRequest",
    "TeamStatusResponse",
    "ThreadListResponse",
    "ThreadSummary",
]


class CreateThreadRequest(BaseModel):
    """Create a new orchestration thread."""

    title: str | None = None
    initial_message: str
    provider: Provider | None = None
    model: Model | None = None


class CreateThreadResponse(BaseModel):
    """Response after successfully creating a thread."""

    thread_id: str
    status: str


class SendMessageRequest(BaseModel):
    """Send a user message into an existing thread via REST."""

    content: str
    agent_id: str | None = None


class ThreadSummary(BaseModel):
    """Lightweight thread descriptor for list endpoints."""

    thread_id: str
    title: str | None = None
    status: str
    agent_state: AgentLifecycleState | None = None
    created_at: datetime
    updated_at: datetime


class ThreadListResponse(BaseModel):
    """Paginated thread listing."""

    threads: list[ThreadSummary]
    total: int


class _AgentStatusEntry(BaseModel):
    """Agent status within a team status response."""

    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider
    model: Model


class _PendingPermission(BaseModel):
    """Outstanding permission request summary."""

    request_id: str
    thread_id: str
    description: str


class TeamStatusResponse(BaseModel):
    """Current team status snapshot via REST."""

    agents: list[_AgentStatusEntry]
    active_threads: list[str]
    pending_permissions: list[_PendingPermission]


class PermissionResponseRequest(BaseModel):
    """Submit a permission response via REST (guaranteed delivery)."""

    option_id: str
    kind: PermissionOptionKind | None = None


class PermissionResponseResult(BaseModel):
    """Result of submitting a permission response."""

    request_id: str
    accepted: bool
    thread_id: str
