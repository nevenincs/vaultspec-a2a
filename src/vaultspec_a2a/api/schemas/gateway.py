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

The run-start models expose ``start``, ``prepare``, ``commit``, and ``release``
for :mod:`vaultspec_a2a.api.routes.gateway`. Commit binds the exact role set to
the exact replay request. ``lease_id`` is non-secret coordination metadata, not
a bearer credential; release applies only to an uncommitted reservation.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...context.metadata import ThreadMetadata
from ...thread.actor_tokens import ActorTokenBundle
from ...thread.enums import ThreadStatus

__all__ = [
    "ActiveRunRecord",
    "ActiveRunsResponse",
    "DesktopReadiness",
    "GatewayReadiness",
    "LeaseId",
    "LivenessResponse",
    "LivenessState",
    "PathSafeRunId",
    "PresetSummary",
    "PresetsListResponse",
    "ProfileSummary",
    "ProviderEligibility",
    "ReservationId",
    "RoleAssignmentSummary",
    "RoleState",
    "RunAdmission",
    "RunCancelResponse",
    "RunCommitResponse",
    "RunPrepareResponse",
    "RunReleaseResponse",
    "RunStage",
    "RunStartRequest",
    "RunStartResponse",
    "RunStatusResponse",
    "ServiceStateResponse",
    "TerminalSettlement",
    "TopologyPosition",
    "WorkerLifecycleState",
]

_API_VERSION = "v1"
_PATH_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$")
PathSafeRunId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=_PATH_SAFE_RUN_ID.pattern),
]
# A reservation identity is a server-minted opaque handle for a prepared
# admission slot; a lease identity is the non-secret, run-scoped handle the
# dashboard revokes at terminal settlement. Both share the run-id path-safe
# shape so they are addressable and log-safe, and neither is ever a bearer.
ReservationId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=_PATH_SAFE_RUN_ID.pattern),
]
LeaseId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=_PATH_SAFE_RUN_ID.pattern),
]


class LivenessState(StrEnum):
    """Minimal process-liveness fact: the gateway answered, or it did not.

    This is the only fact an unauthenticated caller ever observes. It proves
    neither ownership nor readiness and discloses no product state.
    """

    ALIVE = "alive"
    NOT_ALIVE = "not_alive"


class GatewayReadiness(StrEnum):
    """Whether a live gateway with a valid database is ready to be attached.

    Independent of worker state: a live gateway with a valid database and a cold,
    startable worker is ``ready``. A gateway-owned dependency failure - an invalid
    or unreachable database - is ``not_ready``.
    """

    READY = "ready"
    NOT_READY = "not_ready"


class WorkerLifecycleState(StrEnum):
    """The gateway-owned worker's rung on the cold-to-execution ladder.

    ``cold`` is the pre-demand resting state: no worker exists yet and one is
    startable on first execution demand. It is informational, never degradation.
    ``starting`` is the single-flight startup window, ``ready`` is an up and
    reachable worker, and ``unavailable`` is a worker that started but is down or
    restarting after demand.
    """

    COLD = "cold"
    STARTING = "starting"
    READY = "ready"
    UNAVAILABLE = "unavailable"


class ProviderEligibility(StrEnum):
    """Whether at least one subprocess provider command resolves on this host.

    Computed through the no-instantiation classify seam: no provider is
    constructed and no subprocess is spawned to determine it.
    """

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class RunAdmission(StrEnum):
    """Whether the gateway would admit a run right now - the execution-ready fact.

    ``ready`` means execution-ready: a reachable worker and an eligible provider.
    ``deferred`` means gateway-ready but not yet execution-ready - the worker is
    cold or starting and will start on demand. It remains informational on the
    readiness surface, while staged ``prepare`` admission refuses it fail-closed.
    ``blocked`` means a hard gateway dependency (the database) is unavailable.
    """

    READY = "ready"
    DEFERRED = "deferred"
    BLOCKED = "blocked"


class RunStage(StrEnum):
    """Which stage of the run-start verb a request drives.

    The single ``POST /v1/runs`` verb supports ``prepare`` for readiness-gated,
    expiring capacity; ``commit`` for exact request and actor-role binding;
    ``release`` for an uncommitted reservation; and the pre-existing one-shot
    ``start`` compatibility path.
    """

    START = "start"
    PREPARE = "prepare"
    COMMIT = "commit"
    RELEASE = "release"


class RunStartRequest(BaseModel):
    """Start a run: the engine-facing shape of thread-create + first message.

    Carries the engine-provisioned per-role actor token bundle alongside
    the run's preset and opening message. The gateway threads this onto the same
    dispatch path the internal thread-create flow uses — no second code path.
    """

    model_config = ConfigDict(extra="forbid")

    # The stage this request drives. Absent means ``start`` - the direct one-shot
    # path - so every pre-existing caller keeps its contract unchanged.
    stage: RunStage = RunStage.START
    # The prepared reservation a ``commit`` binds to. Required on ``commit``,
    # forbidden on ``prepare`` and ``start`` (there is nothing to bind yet).
    reservation_id: ReservationId | None = None
    # A non-empty preset is mandatory on the v1 verb: the engine-facing contract
    # never creates the internal surface's non-dispatched draft.
    team_preset: str = Field(min_length=1, max_length=64)
    # 64 KB cap bounds LLM token consumption and keeps the run-start payload safe
    # to wrap under the engine pass-through caps. Empty is permitted only on a
    # ``prepare``, which carries no opening message; ``start``/``commit`` require
    # a non-empty prompt (enforced stage-aware below).
    message: str = Field(default="", max_length=65536)
    actor_tokens: ActorTokenBundle | None = None
    metadata: ThreadMetadata | None = None
    autonomous: bool | None = None
    title: str | None = Field(default=None, max_length=200)
    # Target feature tag for document-authoring runs. Bounded; the eligibility
    # policy requires it for document-authoring presets. Falls back to
    # metadata.feature_tag when the field is omitted.
    feature_tag: str | None = Field(default=None, max_length=128)
    # Client-supplied stable run/idempotency id. Staged prepare, commit, and
    # release require it so a lost acknowledgement can be replayed; direct start
    # keeps the compatibility shape and may mint a server-side id when absent.
    run_id: PathSafeRunId | None = None
    # model-profiles: the selected model profile id. Defaults to the implicit
    # team-defaults profile (the team's normal resolution). An unknown or
    # ineligible profile is refused before dispatch - never silently replaced.
    profile_id: str = Field(default="team-defaults", min_length=1, max_length=64)
    # feedback-loop: an OPAQUE engine feedback-batch id for a revision run. a2a
    # never parses or owns batch content (edge ADR D5); it transports only the id
    # and the worker retrieves the authoritative feedback context from the engine
    # batch read route. Bounded; content-addressed ("feedback-batch:<digest>").
    feedback_batch_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def _enforce_stage_invariants(self) -> RunStartRequest:
        """Enforce the per-stage shape of the split run-start verb.

        ``start`` and ``commit`` carry the run's opening prompt, so an empty or
        whitespace-only message is refused as it always was. ``prepare`` accepts
        no tokens and reserves nothing to bind, so a token bundle or a
        reservation id on a prepare is a malformed request; ``commit`` must name
        the reservation it binds.
        """
        if self.stage in (RunStage.START, RunStage.COMMIT) and not self.message.strip():
            raise ValueError("message must not be empty")
        if self.stage == RunStage.PREPARE:
            if self.actor_tokens is not None:
                raise ValueError("prepare must not carry actor tokens")
            if self.reservation_id is not None:
                raise ValueError("prepare must not carry a reservation id")
            if self.run_id is None:
                raise ValueError("prepare requires a stable run id")
        if self.stage == RunStage.COMMIT:
            if self.reservation_id is None:
                raise ValueError("commit requires a reservation id")
            if self.run_id is None:
                raise ValueError("commit requires a stable run id")
        if self.stage == RunStage.RELEASE:
            if self.reservation_id is None:
                raise ValueError("release requires a reservation id")
            if self.run_id is None:
                raise ValueError("release requires a stable run id")
            if self.actor_tokens is not None:
                raise ValueError("release must not carry actor tokens")
        return self

    @field_validator("run_id")
    @classmethod
    def _run_id_must_be_path_safe(cls, value: str | None) -> str | None:
        """Keep client identities addressable by every per-run gateway route."""
        if value is not None and _PATH_SAFE_RUN_ID.fullmatch(value) is None:
            raise ValueError("run_id must be a path-safe token")
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


class RunPrepareResponse(BaseModel):
    """Acknowledge a prepared admission reservation.

    Returned by the ``prepare`` stage of run-start. It carries the server-minted
    reservation identity a later ``commit`` binds to, its non-secret run-scoped
    lease identity, the bounded validated set of roles that commit's actor-token
    bundle must cover, and the reservation's hard expiry. The three readiness
    facts report why admission is or is not
    execution-ready right now. No durable run exists yet and no token was
    accepted; a reservation that is never committed simply expires.
    """

    api_version: Literal["v1"] = _API_VERSION
    stage: Literal["prepared"] = "prepared"
    reservation_id: str
    lease_id: LeaseId
    # The roles commit's actor-token bundle must cover, one per required role.
    required_roles: list[str] = Field(default_factory=list, max_length=64)
    # ISO-8601 hard expiry; the slot is released automatically at this instant.
    expires_at: str
    worker_state: WorkerLifecycleState
    provider_eligibility: ProviderEligibility
    run_admission: RunAdmission
    # Bounded, path-free reasons explaining a deferred or blocked admission.
    reasons: list[str] = Field(default_factory=list, max_length=16)


class RunCommitResponse(BaseModel):
    """Acknowledge a run committed against a prepared reservation.

    Returned by the ``commit`` stage. The reservation is consumed and a stable
    run is created and dispatched with the bound actor tokens. ``lease_id`` is the
    non-secret, run-scoped lease identity the dashboard revokes at terminal
    settlement; it is an identifier, never a bearer.
    """

    api_version: Literal["v1"] = _API_VERSION
    stage: Literal["committed"] = "committed"
    run_id: str
    status: str
    lease_id: str
    semantic_status: str = "starting"
    nickname: str | None = None
    profile_id: str | None = None
    assignments: list[RoleAssignmentSummary] = Field(default_factory=list)


class RunReleaseResponse(BaseModel):
    """Acknowledge explicit release of an uncommitted reservation."""

    api_version: Literal["v1"] = _API_VERSION
    stage: Literal["released"] = "released"
    reservation_id: ReservationId
    released: bool


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
    # Non-secret staged-admission lease identity. It lets the dashboard repair
    # a locally reserved hash bundle after a process crash that followed remote
    # commit but preceded the local binding write.
    lease_id: LeaseId | None = None
    # The persisted prepare reservation paired with ``lease_id``. This lets a
    # dashboard reconcile only the exact local reservation after a lost reply.
    reservation_id: ReservationId | None = None


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
    # The separated desktop readiness projection: process and product identity
    # plus the five bounded facts. Built by the single readiness authority
    # (``assemble_desktop_readiness``) so service-state and the authenticated
    # liveness surface never compute readiness twice. Additive v1; absent on any
    # response constructed before the readiness authority ran.
    readiness: "DesktopReadiness | None" = None


class LivenessResponse(BaseModel):
    """The unauthenticated liveness body.

    Deliberately minimal: it carries only the liveness fact and discloses no
    process identity, product identity, or product state. An unauthenticated
    caller of the desktop gateway observes this and nothing more.
    """

    liveness: LivenessState = LivenessState.ALIVE


class DesktopReadiness(BaseModel):
    """The authenticated desktop readiness projection.

    Carries process and product identity alongside the five separate bounded
    readiness facts. The facts are never collapsed into a single boolean: a cold,
    startable worker leaves ``gateway_readiness`` ``ready`` while ``run_admission``
    stays ``deferred``, so gateway-readiness and execution-readiness remain
    distinct. Served only to an attach-authenticated caller.
    """

    api_version: Literal["v1"] = _API_VERSION
    # Process identity.
    gateway_pid: int
    # Product identity: the running product generation and its profile.
    generation: str
    profile: str
    # The five separate bounded facts.
    liveness: LivenessState = LivenessState.ALIVE
    gateway_readiness: GatewayReadiness
    worker_state: WorkerLifecycleState
    provider_eligibility: ProviderEligibility
    eligible_providers: list[str] = Field(default_factory=list, max_length=16)
    run_admission: RunAdmission
    # Bounded, path-free reasons explaining a not-ready, cold, or deferred fact.
    reasons: list[str] = Field(default_factory=list, max_length=16)


class TerminalSettlement(BaseModel):
    """The bounded terminal-settlement callback body.

    Emitted by the gateway to the dashboard after a run reaches a durable
    terminal state, authenticated with the dashboard-created attach-control
    credential. It carries only non-secret identities - the run and its lease -
    plus the terminal status, so the dashboard can revoke exactly that run's
    lease. It never carries an actor token, the worker interprocess-communication
    secret, or any other bearer.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: str = Field(min_length=1, max_length=128)
    lease_id: str = Field(min_length=1, max_length=128)
    terminal_status: ThreadStatus


# ``ServiceStateResponse.readiness`` forward-references ``DesktopReadiness``,
# defined below it; rebuild the model now that the target is in scope.
ServiceStateResponse.model_rebuild()
