"""Internal IPC message types between gateway and worker (ADR-019)."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


__all__ = [
    "DispatchRequest",
    "DispatchResponse",
    "HeartbeatMessage",
    "WorkerEventEnvelope",
]


class DispatchRequest(BaseModel):
    """Work dispatch command from gateway to worker."""

    dispatch_id: str = Field(default_factory=lambda: uuid4().hex)
    action: Literal["ingest", "resume", "cancel"] = Field(
        description="'ingest' | 'resume' | 'cancel'"
    )
    thread_id: str
    agent_id: str = "vaultspec-supervisor"
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
    recursion_limit: int = 100
    # ADR-019: SDD blackboard fields
    active_feature: str | None = None
    pipeline_phase: str | None = None
    vault_index: dict[str, list[str]] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)


class DispatchResponse(BaseModel):
    """Acknowledgement from worker to gateway."""

    status: str = "dispatched"
    thread_id: str


class HeartbeatMessage(BaseModel):
    """Worker heartbeat sent via internal WebSocket."""

    type: str = "heartbeat"
    worker_id: str
    active_threads: list[str] = Field(default_factory=list)
    timestamp: str


class WorkerEventEnvelope(BaseModel):
    """Wrapper for events sent from worker to gateway via internal WS."""

    type: str = "event"
    thread_id: str
    payload: dict
