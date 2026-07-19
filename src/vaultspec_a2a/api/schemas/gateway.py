"""Versioned gateway wire models.

The engine pass-through forwards versioned, bounded, self-describing run and
service operations across the edge. Every response carries an explicit
``api_version`` so the engine can wrap it verbatim inside its own tiers envelope
and fence event-shape drift; every field is bounded so a response is always safe
to wrap under the engine's 8 MiB / 120 s caps.

The gateway contract reshapes the existing service surface rather than
reinventing it:
``run-start`` delegates to the same thread-create/dispatch flow the internal
``/api`` surface uses, ``run-status`` composes the recovery snapshot, active-run
discovery projects bounded durable identities, and the operator verbs roll up
cancel, preset listing, and health.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ...context.metadata import ThreadMetadata
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.enums import ThreadStatus

__all__ = [
    "ActiveRunRecord",
    "ActiveRunsResponse",
    "PresetSummary",
    "PresetsListResponse",
    "ProfileSummary",
    "RoleAssignmentSummary",
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

    Carries the engine-provisioned per-role actor token bundle alongside
    the run's preset and opening message. The gateway threads this onto the same
    dispatch path the internal thread-create flow uses — no second code path.
    """

    # A non-empty preset is mandatory on the v1 verb: the engine-facing contract
    # never creates the internal surface's non-dispatched draft.
    team_preset: str = Field(min_length=1, max_length=64)
    # 64 KB cap bounds LLM token consumption and keeps the run-start payload safe
    # to wrap under the engine pass-through caps.
    message: str = Field(max_length=65536)
    actor_tokens: ActorTokenBundle | None = None
    metadata: ThreadMetadata | None = None
    autonomous: bool | None = None
    title: str | None = Field(default=None, max_length=200)
    # Target feature tag for document-authoring runs. Bounded; the eligibility
    # policy requires it for document-authoring presets. Falls back to
    # metadata.feature_tag when the field is omitted.
    feature_tag: str | None = Field(default=None, max_length=128)
    # Client-supplied stable run/idempotency id. When present the verb is
    # dispatch-exactly-once: a retry with the same id returns the existing run
    # instead of starting a second. Absent, the gateway mints a server-side id.
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    # model-profiles: the selected model profile id. Defaults to the implicit
    # team-defaults profile (the team's normal resolution). An unknown or
    # ineligible profile is refused before dispatch - never silently replaced.
    profile_id: str = Field(default="team-defaults", min_length=1, max_length=64)
    # feedback-loop: an OPAQUE engine feedback-batch id for a revision run. a2a
    # never parses or owns batch content (edge ADR D5); it transports only the id
    # and the worker retrieves the authoritative feedback context from the engine
    # batch read route. Bounded; content-addressed ("feedback-batch:<digest>").
    feedback_batch_id: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("message")
    @classmethod
    def _message_must_be_non_empty(cls, value: str) -> str:
        """Reject an empty or whitespace-only prompt before dispatch."""
        if not value.strip():
            raise ValueError("message must not be empty")
        return value


class RunStartResponse(BaseModel):
    """Acknowledge a started run, with its initial semantic status."""

    api_version: Literal["v1"] = _API_VERSION
    run_id: str
    status: str
    nickname: str | None = None
    # Initial product-safe semantic status; the full phase projection is served
    # by run-status. "starting" for a freshly dispatched run.
    semantic_status: str = "starting"
    # Whether the run was accepted as eligible to dispatch (always True on a 201;
    # ineligible requests are refused with a 4xx before reaching this response).
    eligible: bool = True
    # model-profiles: the profile the run was frozen with and its effective
    # per-role assignment (additive v1). Absent on the idempotent-replay short
    # path where the response is reconstructed from the existing run row.
    profile_id: str | None = None
    assignments: list[RoleAssignmentSummary] = Field(default_factory=list)


class ActiveRunRecord(BaseModel):
    """Minimal durable run identity used to recover a viewing binding."""

    run_id: str = Field(min_length=1, max_length=128)
    status: ThreadStatus
    feature_tag: str | None = Field(default=None, max_length=128)


class ActiveRunsResponse(BaseModel):
    """Bounded, non-authoritative discovery result for active runs."""

    api_version: Literal["v1"] = _API_VERSION
    state: Literal["active"] = "active"
    runs: list[ActiveRunRecord] = Field(default_factory=list, max_length=100)
    truncated: bool = False


class TopologyPosition(BaseModel):
    """Where a run sits in its team topology (recovery snapshot).

    Product-facing status speaks role vocabulary only: ``active_agent`` is
    the role currently working, never an internal LangGraph node name. The raw
    next-node projection lives in the internal recovery snapshot
    (``thread/snapshots.py``), not this contract; ``next_nodes`` was dropped
    from the v1 surface.
    """

    team_preset: str | None = None
    active_agent: str | None = None
    pause_cause: str | None = None


class RoleState(BaseModel):
    """Per-role lifecycle state within a run (recovery snapshot)."""

    agent_id: str
    role: str = ""
    state: str
    display_name: str = ""


class RunStatusResponse(BaseModel):
    """The authoritative recovery snapshot for a run.

    Designed as the read a restarted A2A resumes or reports a run from: topology
    position, per-role state, and the engine proposal/changeset ids the run has
    produced, plus the checkpoint cursor and repair posture. Non-authoritative
    SSE progress frames may be lost freely; this snapshot is the source of truth.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: str
    status: ThreadStatus
    # Product-safe semantic authoring phase projected from topology position and
    # gate state, so the Rust backend never interprets LangGraph node names.
    semantic_phase: str
    # The run's target feature tag and the Rust-backend authoring session id it
    # produced, read from the checkpoint (None until produced / for non-authoring).
    feature_tag: str | None = None
    authoring_session_id: str | None = None
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
    # model-profiles: the frozen profile the run launched with and its
    # effective per-role assignment, reproduced verbatim from run metadata across
    # restarts (additive v1; absent for runs started before profiles landed).
    profile_id: str | None = None
    assignments: list[RoleAssignmentSummary] = Field(default_factory=list)


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


class RoleAssignmentSummary(BaseModel):
    """Effective per-role model assignment under a profile.

    Only safe operational metadata: role id, agent id, provider id, capability,
    the stable concrete model name, ordered fallbacks, current provider readiness,
    and which precedence layer the assignment came from. Never a credential, env
    value, token, or private path.
    """

    role_id: str
    agent_id: str
    provider_id: str
    capability: str | None = None
    model_name: str | None = None
    fallback_providers: list[str] = Field(default_factory=list)
    provider_ready: bool = False
    source: str = "team_default"
    resolution_error: str | None = None


class ProfileSummary(BaseModel):
    """One selectable model profile for a preset.

    Carries the profile's identity, whether it is the default, its per-role
    effective assignments (resolved by the same shared resolver launch uses, so
    picker truth cannot drift from execution truth), and backend-computed
    eligibility with safe reasons.
    """

    id: str
    display_name: str = ""
    description: str = ""
    is_default: bool = False
    eligible: bool = False
    unavailable_reasons: list[str] = Field(default_factory=list)
    assignments: list[RoleAssignmentSummary] = Field(default_factory=list)


class PresetSummary(BaseModel):
    """One discovered team preset and whether it is actually runnable.

    A preset whose TOML is missing or invalid is still listed with
    ``loadable=False`` and an ``unavailable_reason`` so the Rust backend sees the
    truthful set rather than a listing that omits or crashes on it. Descriptive
    fields are populated only when the preset loaded.
    """

    id: str
    loadable: bool
    unavailable_reason: str | None = None
    display_name: str | None = None
    description: str | None = None
    topology: str | None = None
    worker_count: int | None = None
    required_roles: list[str] = Field(default_factory=list)
    authoring_capability: str | None = None
    # True for bundled mock/test presets so the product layer can exclude them.
    is_mock: bool = False
    # model-profiles additions (additive v1 fields, absent-safe):
    # preset origin (bundled | workspace | test_mock), the document outputs the
    # topology delivers, the selectable profiles with effective assignments and
    # eligibility, and the default profile id.
    origin: str | None = None
    supported_capabilities: list[str] = Field(default_factory=list)
    profiles: list[ProfileSummary] = Field(default_factory=list)
    default_profile_id: str | None = None


class PresetsListResponse(BaseModel):
    """List of available team presets."""

    api_version: Literal["v1"] = _API_VERSION
    presets: list[PresetSummary] = Field(default_factory=list)


class ServiceStateResponse(BaseModel):
    """Backend-served readiness for the A2A service (service-state verb).

    Distinguishes three truths the Rust backend must not conflate: the process is
    ``alive`` (it answered), the service ``can_accept_run`` (dependencies are
    ready), and - separately, via presets-list eligibility - whether a chosen
    authoring preset is runnable. A live HTTP process is not evidence that a run
    can start, so ``status`` is derived from real dependency probes rather than
    hardcoded.
    """

    api_version: Literal["v1"] = _API_VERSION
    service_version: str
    # "ready" (can accept a run), "degraded" (alive but a dependency is unready),
    # or "unavailable" (a hard dependency such as the database is down).
    status: str
    alive: bool = True
    ready: bool
    can_accept_run: bool
    gateway_pid: int
    worker_status: str | None = None
    worker_connected: bool | None = None
    circuit_breaker: str | None = None
    database_backend: str | None = None
    checkpoint_backend: str | None = None
    database_ready: bool | None = None
    checkpoint_ready: bool | None = None
    worker_ready: bool | None = None
    # Engine authoring-backend discovery freshness (non-blocking, file+heartbeat):
    # True when a fresh valid discovery record exists, False when present but
    # stale/malformed, None when no engine is configured for this process.
    authoring_backend_reachable: bool | None = None
    # Configured maximum concurrent runs this gateway admits.
    active_run_capacity: int | None = None
    degraded_reasons: list[str] = Field(default_factory=list)
    # Sorted "METHOD path" signature of the live route table (see
    # ``route_signature`` in ``api.routes.gateway``). The doctor CLI diffs this
    # against the installed source's expected signature to catch a resident
    # process started before a route landed - there is no hot-reload, so a
    # stale resident silently 404s otherwise.
    routes: list[str] = Field(default_factory=list)
