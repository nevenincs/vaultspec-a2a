"""Shared IPC message types between gateway and worker (ADR-019, D-01).

These types define the gateway-worker contract.  Neither ``api/`` nor
``worker/`` owns them; both are equal consumers.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from ..thread.constants import DEFAULT_SUPERVISOR_ID

__all__ = [
    "DispatchRequest",
    "DispatchResponse",
    "ExecutionStateProjectionPayload",
    "ExecutionTaskProjectionPayload",
]


class DispatchRequest(BaseModel):
    """Work dispatch command from gateway to worker."""

    dispatch_id: str = Field(default_factory=lambda: uuid4().hex)
    action: Literal["ingest", "resume", "cancel"] = Field(
        description="'ingest' | 'resume' | 'cancel'"
    )
    thread_id: str
    agent_id: str = DEFAULT_SUPERVISOR_ID
    # For ingest: user message content
    content: str | None = None
    # For resume: permission response option
    # (str for tool perms, dict for plan approval)
    option_id: str | dict | None = None
    # For initial thread creation
    team_preset: str | None = None
    workspace_root: str | None = None
    autonomous: bool = False
    metadata_json: str | None = None
    context_preamble: str | None = None
    recursion_limit: int
    # ADR-019: SDD blackboard fields
    active_feature: str | None = None
    pipeline_phase: str | None = None
    vault_index: dict[str, list[str]] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)


class DispatchResponse(BaseModel):
    """Acknowledgement from worker to gateway."""

    status: str = "dispatched"
    thread_id: str


class ExecutionTaskProjectionPayload(BaseModel):
    """Normalized task summary emitted internally by the worker."""

    task_id: str
    name: str
    path: list[str] = Field(default_factory=list)
    has_error: bool = False
    error_type: str | None = None
    interrupt_ids: list[str] = Field(default_factory=list)
    interrupt_types: list[str] = Field(default_factory=list)
    has_nested_state: bool = False
    has_result: bool = False


class ExecutionStateProjectionPayload(BaseModel):
    """Normalized execution-state snapshot emitted by the worker."""

    type: str = "execution_state_projection"
    checkpoint_id: str | None = None
    parent_checkpoint_id: str | None = None
    snapshot_created_at: str | None = None
    next_nodes: list[str] = Field(default_factory=list)
    interrupt_types: list[str] = Field(default_factory=list)
    interrupt_count: int = 0
    task_count: int = 0
    tasks: list[ExecutionTaskProjectionPayload] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
