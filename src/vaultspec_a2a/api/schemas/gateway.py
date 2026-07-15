"""Versioned five-verb gateway wire models (ADR R6).

The engine pass-through forwards exactly five verbs across the frozen edge:
``run-start``, ``run-status``, ``run-cancel``, ``presets-list``, and
``service-state``. These models are the versioned, bounded, self-describing
shapes those verbs speak. Every response carries an explicit ``api_version`` so
the engine can wrap it verbatim inside its own tiers envelope and fence event
shape drift; every field is bounded so a response is always safe to wrap under
the engine's 8 MiB / 120 s caps.

The verbs reshape the existing service surface rather than reinventing it:
``run-start`` delegates to the same thread-create/dispatch flow the internal
``/api`` surface uses, ``run-status`` composes the recovery snapshot, and the
remaining three roll up cancel, preset listing, and health.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...context.metadata import ThreadMetadata
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.enums import ThreadStatus

__all__ = [
    "PresetSummary",
    "PresetsListResponse",
    "RoleState",
    "RunCancelResponse",
    "RunStartRequest",
    "RunStartResponse",
    "RunStatusResponse",
    "ServiceStateResponse",
    "TopologyPosition",
]

_API_VERSION = "v1"


class RunStartRequest(BaseModel):
    """Start a run: the engine-facing shape of thread-create + first message.

    Carries the engine-provisioned per-role actor token bundle (ADR R7) alongside
    the run's preset and opening message. The gateway threads this onto the same
    dispatch path the internal thread-create flow uses — no second code path.
    """

    team_preset: str = Field(max_length=64)
    # 64 KB cap bounds LLM token consumption and keeps the run-start payload safe
    # to wrap under the engine pass-through caps.
    message: str = Field(max_length=65536)
    actor_tokens: ActorTokenBundle | None = None
    metadata: ThreadMetadata | None = None
    autonomous: bool | None = None
    title: str | None = Field(default=None, max_length=200)


class RunStartResponse(BaseModel):
    """Acknowledge a started run."""

    api_version: Literal["v1"] = _API_VERSION
    run_id: str
    status: str
    nickname: str | None = None


class TopologyPosition(BaseModel):
    """Where a run sits in its team topology (recovery snapshot, ADR R6).

    Product-facing status speaks role vocabulary only (PW4): ``active_agent`` is
    the role currently working, never an internal LangGraph node name. The raw
    next-node projection lives in the internal recovery snapshot
    (``thread/snapshots.py``), not this contract — see the S15 record for why
    ``next_nodes`` was dropped from the v1 surface.
    """

    team_preset: str | None = None
    active_agent: str | None = None
    pause_cause: str | None = None


class RoleState(BaseModel):
    """Per-role lifecycle state within a run (recovery snapshot, ADR R6)."""

    agent_id: str
    role: str = ""
    state: str
    display_name: str = ""


class RunStatusResponse(BaseModel):
    """The authoritative recovery snapshot for a run (ADR R6).

    Designed as the read a restarted A2A resumes or reports a run from: topology
    position, per-role state, and the engine proposal/changeset ids the run has
    produced, plus the checkpoint cursor and repair posture. Non-authoritative
    SSE progress frames may be lost freely; this snapshot is the source of truth.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: str
    status: ThreadStatus
    topology: TopologyPosition
    roles: list[RoleState] = Field(default_factory=list)
    proposal_ids: list[str] = Field(default_factory=list)
    changeset_ids: list[str] = Field(default_factory=list)
    approval_status: str | None = None
    approval_request_id: str | None = None
    checkpoint_id: str | None = None
    last_sequence: int = 0
    repair_status: str | None = None
    execution_readiness: str | None = None
    degraded_reasons: list[str] = Field(default_factory=list)


class RunCancelResponse(BaseModel):
    """Acknowledge an (idempotent) run-cancel request."""

    api_version: Literal["v1"] = _API_VERSION
    run_id: str
    status: str
    cancelled: bool
    accepted: bool = False
    applied: bool = False
    action_status: str = "rejected_invalid_state"
    idempotency_key: str | None = None


class PresetSummary(BaseModel):
    """One available team preset."""

    id: str
    display_name: str
    description: str
    topology: str
    worker_count: int


class PresetsListResponse(BaseModel):
    """List of available team presets."""

    api_version: Literal["v1"] = _API_VERSION
    presets: list[PresetSummary] = Field(default_factory=list)


class ServiceStateResponse(BaseModel):
    """Health/doctor rollup for the resident gateway (service-state verb)."""

    api_version: Literal["v1"] = _API_VERSION
    status: str
    ready: bool
    worker_status: str | None = None
    worker_connected: bool | None = None
    circuit_breaker: str | None = None
    database_backend: str | None = None
    checkpoint_backend: str | None = None
