"""Versioned gateway wire models.

The engine pass-through forwards versioned, bounded, self-describing run and
service operations across the edge. Every response carries an explicit
``api_version`` so the engine can wrap it verbatim inside its own tiers envelope
and fence event-shape drift; every field is bounded so a response is always safe
to wrap under the engine's 8 MiB / 120 s caps.

The gateway contract reshapes the existing service surface rather than
reinventing it:
``run-start`` delegates to the same thread-create/dispatch flow, ``run-status``
composes the recovery snapshot, active-run discovery projects bounded durable
identities, and the operator verbs roll up cancel, preset listing, and health.

The run-start models expose ``start``, ``prepare``, ``commit``, and ``release``
for :mod:`vaultspec_a2a.api.routes.gateway`. Commit binds the exact role set to
the exact replay request. ``lease_id`` is non-secret coordination metadata, not
a bearer credential; release applies only to an uncommitted reservation.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...context.metadata import ThreadMetadata
from ...control.worker_status import WorkerConnectionStatus
from ...graph.enums import SemanticPhase
from ...providers.conditions import ProviderCondition
from ...team.preset_origin import PresetOrigin
from ...team.team_config import TopologyType
from ...thread.actor_tokens import MAX_ROLES_PER_RUN, ActorTokenBundle
from ...thread.clarification import (
    MAX_QUESTIONS_PER_REQUEST,
    MAX_RUN_MESSAGE_CHARS,
    AnswerText,
    ClarificationRequest,
    ContinuationPrompt,
    QuestionId,
)
from ...thread.constants import MAX_FEATURE_TAG_LENGTH
from ...thread.enums import (
    ApprovalStatus,
    CleanupKind,
    RepairStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from .snapshots import ThreadStateSnapshot

# ``MAX_RUN_MESSAGE_CHARS`` is imported to BOUND a field, not to be republished:
# the bound belongs to ``thread.clarification`` beside the continuation prompt it
# also bounds, and being carried on the wire does not make this a second home.
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
    "ProviderCatalogSelection",
    "ProviderEligibility",
    "ReservationId",
    "RoleAssignmentSummary",
    "RoleState",
    "RunAdmission",
    "RunCancelResponse",
    "RunClarificationRespondRequest",
    "RunClarificationRespondResponse",
    "RunCommitResponse",
    "RunPrepareResponse",
    "RunReleaseResponse",
    "RunStage",
    "RunStartRequest",
    "RunStartResponse",
    "RunStatusResponse",
    "RunSummariesResponse",
    "RunSummaryRecord",
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


class ProviderCatalogSelection(BaseModel):
    """One explicit schema-v1 reference to a served provider catalog entry."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    provider_id: str = Field(min_length=1, max_length=512)
    execution_mode: str = Field(min_length=1, max_length=512)
    catalog_revision: str = Field(min_length=1, max_length=512)
    entry_id: str = Field(min_length=1, max_length=512)
    controls: dict[
        Annotated[str, Field(min_length=1, max_length=128)],
        Annotated[str, Field(min_length=1, max_length=512)],
    ] = Field(default_factory=dict, max_length=32)


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
    """Whether at least one subprocess provider can actually run on this host.

    Computed through the credential-aware readiness probe: the configured
    credential is checked first, then command resolvability. The probe is still
    no-instantiation - no provider is constructed and no subprocess is spawned
    to determine it - but a resolvable launch command is not on its own
    sufficient, because a provider whose binary is installed with its
    credential absent cannot run. Codex is the deliberate exception: its auth
    is a file-based persisted session rather than a configured secret, so it
    gates on command resolvability alone.
    """

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


class RunAdmission(StrEnum):
    """Whether the gateway would admit a run right now - the execution-ready fact.

    ``ready`` means execution-ready: a reachable worker and a provider that is
    both installed and credentialed, so this staged gate and the
    credential-aware gate launch applies agree, rather than admitting a run and
    reserving capacity for it that the latter then refuses.
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
    # The opening prompt, bounded at 65536 CHARACTERS - not bytes. The bound is
    # a proxy for LLM token consumption, and tokens track characters, so counting
    # bytes instead would hand a CJK or emoji author a quarter of the prompt an
    # ASCII author gets for the same model cost. A consumer that bounds this
    # field in bytes must therefore budget 65536 * 4 = 262144, the most UTF-8 can
    # spend on the permitted character count; that figure is well inside the
    # engine's pass-through cap, so no truncation is owed anywhere on the path.
    # Empty is permitted only on a ``prepare``, which carries no opening message;
    # ``start``/``commit`` require a non-empty prompt (enforced stage-aware
    # below).
    message: str = Field(default="", max_length=MAX_RUN_MESSAGE_CHARS)
    actor_tokens: ActorTokenBundle | None = None
    metadata: ThreadMetadata | None = None
    autonomous: bool | None = None
    title: str | None = Field(default=None, max_length=200)
    # Target feature tag for document-authoring runs. Bounded; the eligibility
    # policy requires it for document-authoring presets. Falls back to
    # metadata.feature_tag when the field is omitted.
    feature_tag: str | None = Field(default=None, max_length=MAX_FEATURE_TAG_LENGTH)
    # Client-supplied stable run/idempotency id. Explicit provider selection is
    # replay-safe only when every start owns a durable caller identity.
    run_id: PathSafeRunId
    # Explicit whole-team catalog choice. New runs have no implicit profile or
    # provider default; every selected value must revalidate against the current
    # workspace catalog before admission.
    selection: ProviderCatalogSelection
    overrides: dict[
        Annotated[str, Field(min_length=1, max_length=63)], ProviderCatalogSelection
    ] = Field(default_factory=dict, max_length=64)
    fallbacks: list[ProviderCatalogSelection] = Field(
        default_factory=list, max_length=8
    )
    # feedback-loop: an OPAQUE engine feedback-batch id for a revision run. a2a
    # never parses or owns batch content; it transports only the id
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
        if self.stage == RunStage.COMMIT and self.reservation_id is None:
            raise ValueError("commit requires a reservation id")
        if self.stage == RunStage.RELEASE:
            if self.reservation_id is None:
                raise ValueError("release requires a reservation id")
            if self.actor_tokens is not None:
                raise ValueError("release must not carry actor tokens")
        return self


class FrozenNativeControlSummary(BaseModel):
    """One exact provider-native value frozen for historical disclosure."""

    control_id: str = Field(min_length=1, max_length=1024)
    option_id: str = Field(min_length=1, max_length=1024)
    provider_value: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, max_length=256)
    option_display_name: str | None = Field(default=None, max_length=256)


class FrozenExecutionSnapshotSummary(BaseModel):
    """Catalog provenance and exact provider inputs for one execution lane."""

    provider_id: str = Field(min_length=1, max_length=1024)
    provider_display_name: str | None = Field(default=None, max_length=256)
    execution_mode: str = Field(min_length=1, max_length=1024)
    catalog_revision: str = Field(min_length=1, max_length=1024)
    entry_id: str = Field(min_length=1, max_length=1024)
    model_name: str = Field(min_length=1, max_length=1024)
    model_display_name: str | None = Field(default=None, max_length=256)
    controls: list[FrozenNativeControlSummary] = Field(
        default_factory=list, max_length=32
    )


class FrozenSelectionProvenanceSummary(BaseModel):
    """Bounded admission layer that supplied one role's primary lane."""

    selection_source: Literal["team_selection", "role_override"]


class FrozenRoleAssignmentSummary(FrozenExecutionSnapshotSummary):
    """One role's exact primary and ordered fallback execution snapshots."""

    role_id: str = Field(min_length=1, max_length=1024)
    agent_id: str | None = Field(default=None, max_length=1024)
    fallbacks: list[FrozenExecutionSnapshotSummary] = Field(
        default_factory=list, max_length=8
    )
    provenance: FrozenSelectionProvenanceSummary


class FrozenTeamAssignmentSummary(BaseModel):
    """Complete immutable schema-v1 execution authority for a modern run."""

    schema_version: Literal[1] = 1
    digest: str = Field(
        min_length=64,
        max_length=71,
        pattern=r"^(?:sha256:)?[a-f0-9]{64}$",
    )
    assignments: list[FrozenRoleAssignmentSummary] = Field(
        min_length=1, max_length=MAX_ROLES_PER_RUN
    )


class RunStartResponse(BaseModel):
    """Acknowledge a started run, with its initial semantic status."""

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    status: str
    nickname: str | None = None
    # Initial product-safe semantic status; the full phase projection is served
    # by run-status. Typed by the SAME vocabulary that field answers from, since
    # this is that question asked one moment earlier, not a second one.
    semantic_status: SemanticPhase = SemanticPhase.STARTING
    # Whether the run was accepted as eligible to dispatch (always True on a 201;
    # ineligible requests are refused with a 4xx before reaching this response).
    eligible: bool = True
    # The complete execution authority the run was frozen with - the single
    # disclosure of what will produce this run's work. The retired profile pair
    # (`profile_id`, `assignments`) is deliberately absent here: a request that
    # could start a profile-driven run no longer parses, so on this response
    # those fields could only ever disclose a confident emptiness. Runs frozen
    # under the legacy profiles remain readable through run-status, which keeps
    # both shapes.
    frozen_assignment: FrozenTeamAssignmentSummary | None = None


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
    reservation_id: ReservationId
    lease_id: LeaseId
    # The roles commit's actor-token bundle must cover, one per required role.
    required_roles: list[str] = Field(
        default_factory=list, max_length=MAX_ROLES_PER_RUN
    )
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
    run_id: PathSafeRunId
    status: str
    lease_id: LeaseId
    semantic_status: SemanticPhase = SemanticPhase.STARTING
    nickname: str | None = None
    # As on RunStartResponse: the freeze is the one start-surface disclosure;
    # the legacy profile pair is unreachable through the commit schema.
    frozen_assignment: FrozenTeamAssignmentSummary | None = None


class RunReleaseResponse(BaseModel):
    """Acknowledge explicit release of an uncommitted reservation."""

    api_version: Literal["v1"] = _API_VERSION
    stage: Literal["released"] = "released"
    reservation_id: ReservationId
    released: bool


class ActiveRunRecord(BaseModel):
    """Minimal durable run identity used to recover a viewing binding."""

    run_id: PathSafeRunId
    status: ThreadStatus
    feature_tag: str | None = Field(default=None, max_length=MAX_FEATURE_TAG_LENGTH)


class ActiveRunsResponse(BaseModel):
    """Bounded, non-authoritative run listing.

    ``state`` distinguishes the two readings deliberately. The default is the
    capped discovery projection of non-terminal runs - what the engine contract
    certified, unchanged. ``all`` is the history read over the paginated store,
    which is the only mode that can report a ``total``: discovery caps its answer
    by design and has no honest total to give.
    """

    api_version: Literal["v1"] = _API_VERSION
    state: Literal["active", "all"] = "active"
    runs: list[ActiveRunRecord] = Field(default_factory=list, max_length=100)
    truncated: bool = False
    #: Total matching runs. Present only for the history reading; ``None`` in
    #: discovery, where a capped projection cannot honestly report one.
    total: int | None = None


class RunSummaryRecord(BaseModel):
    """One run as the history reading reports it: identity plus its projection.

    Deliberately wider than :class:`ActiveRunRecord`, and deliberately a
    SEPARATE model rather than fields added to it. Discovery answers the narrow
    question "which runs are live, and where do I bind a viewer" and its shape is
    certified byte-for-byte; a reader of history is asking what happened, and
    needs the facts that distinguish a healthy run from a degraded one.

    Every field here is one the list service already resolves - the degradation
    projections in particular are its reading of checkpoint authority and stale
    approval pointers, not a restatement of stored columns - so nothing is
    invented that the projection cannot fill.
    """

    run_id: PathSafeRunId
    status: ThreadStatus
    feature_tag: str | None = Field(default=None, max_length=MAX_FEATURE_TAG_LENGTH)
    title: str | None = Field(default=None, max_length=200)
    nickname: str | None = Field(default=None, max_length=128)
    team_preset: str | None = Field(default=None, max_length=64)
    # The projection's verdict on this run's recoverability. A caller scanning
    # history for work that needs attention reads these, and they are the whole
    # reason this record exists rather than the discovery one.
    # All three answer from a closed set the service fixes, so they are served
    # as the enumerations that already own them rather than as bounded strings.
    # ``repair_status`` and ``execution_readiness`` share one vocabulary
    # deliberately: they ask different questions from the same set of answers.
    repair_status: RepairStatus | None = None
    execution_readiness: RepairStatus | None = None
    approval_status: ApprovalStatus | None = None
    approval_request_id: str | None = Field(default=None, max_length=256)
    created_at: datetime
    updated_at: datetime
    source_branch: str | None = Field(default=None, max_length=256)
    callee: str | None = Field(default=None, max_length=128)


class RunSummariesResponse(BaseModel):
    """The history reading of the run listing.

    Answers ``state=all`` only. The default reading keeps
    :class:`ActiveRunsResponse` and its narrower record, so widening what history
    reports cannot disturb the certified discovery shape.

    ``total`` is not optional here: this reading walks the paginated store and
    always knows how many runs matched, which is what makes paging honest.
    """

    api_version: Literal["v1"] = _API_VERSION
    state: Literal["all"] = "all"
    runs: list[RunSummaryRecord] = Field(default_factory=list, max_length=100)
    truncated: bool = False
    total: int


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
    run_id: PathSafeRunId
    status: ThreadStatus
    # Product-safe semantic authoring phase projected from topology position and
    # gate state, so the Rust backend never interprets LangGraph node names.
    semantic_phase: SemanticPhase
    # The run's target feature tag and the Rust-backend authoring session id it
    # produced, read from the checkpoint (None until produced / for non-authoring).
    feature_tag: str | None = None
    authoring_session_id: str | None = None
    topology: TopologyPosition
    roles: list[RoleState] = Field(default_factory=list)
    proposal_ids: list[str] = Field(default_factory=list)
    changeset_ids: list[str] = Field(default_factory=list)
    approval_status: ApprovalStatus | None = None
    approval_request_id: str | None = None
    checkpoint_id: str | None = None
    last_sequence: int = 0
    repair_status: RepairStatus | None = None
    execution_readiness: RepairStatus | None = None
    # Left as bare strings pending the narrowing, NOT because this list lacks an
    # owning vocabulary - ``thread.enums.DegradedReason`` declares it - but
    # because the projection that appends to it is under concurrent revision and
    # a member added there while this field is narrowed would fail the response
    # rather than the write. Narrowed once that projection derives from the type.
    degraded_reasons: list[str] = Field(default_factory=list)
    # The capped, single-line reason this run last transitioned to FAILED,
    # sourced from the durable threads.failure_reason column (never a live SSE
    # frame), so a reloaded panel recovers the SAME reason a connected client
    # already saw over the relay rather than a bare "failed". Additive; None for
    # a run that never failed, or one whose failure predates this field.
    failure_reason: str | None = None
    # The machine-readable counterpart to the reason above: which member of the
    # closed provider-condition vocabulary the failure resolved to. The reason
    # says what happened, this says what the reader should do about it - wait,
    # re-authenticate, top up, raise a ceiling, or change the request - and a
    # client that had to derive that from the reason text would be matching
    # vendor prose, which breaks the moment a vendor rewords a message. Served
    # as the owning enumeration, which is what makes that promise checkable.
    #
    # Authoritative here rather than on the relay, following the same discipline
    # the pending clarification below follows: the error frame carrying this
    # value is droppable, so a reloading client with no live stream recovers it
    # only from this response. Additive; None for a run that never failed, or
    # one whose failure predates the durable column. The value is a wire
    # contract shared with the consuming repository and is additive-only.
    provider_condition: ProviderCondition | None = None
    # Why an OPERATION did not take on a run that is STILL ALIVE - a follow-up
    # or a resume the worker never received - as opposed to why a run FAILED.
    # The distinction is not cosmetic and a client must not collapse it: a run
    # reported here is still parked on its question and may yet complete, so
    # rendering this as a failure tells a user their run died when it did not.
    # The two never both describe the same event; a failed run carries
    # failure_reason and a live one carries this.
    #
    # Projected because the paths that write it - an undelivered follow-up, an
    # undelivered clarification resume - deliberately decline to stamp
    # failure_reason precisely BECAUSE the run survives. Without this field that
    # account reached no client at all: durable, and readable by nobody.
    repair_reason: str | None = Field(default=None, max_length=500)
    # model-profiles: the frozen profile the run launched with and its
    # effective per-role assignment, reproduced verbatim from run metadata across
    # restarts (additive v1; absent for runs started before profiles landed).
    profile_id: str | None = None
    assignments: list[RoleAssignmentSummary] = Field(default_factory=list)
    frozen_assignment: FrozenTeamAssignmentSummary | None = None
    # Non-secret staged-admission lease identity. It lets the dashboard repair
    # a locally reserved hash bundle after a process crash that followed remote
    # commit but preceded the local binding write.
    lease_id: LeaseId | None = None
    # The persisted prepare reservation paired with ``lease_id``. This lets a
    # dashboard reconcile only the exact local reservation after a lost reply.
    reservation_id: ReservationId | None = None
    # The bounded questionnaire this run is currently parked on, read from the
    # run's own checkpoint. This is the AUTHORITATIVE disclosure of a pending
    # question: a client that reloaded, or that never saw the progress frame
    # announcing it, re-renders the questionnaire from here. ``None`` whenever the
    # run is not waiting on one, which is the overwhelmingly common case.
    pending_clarification: ClarificationRequest | None = None


class RunCancelResponse(BaseModel):
    """Acknowledge an (idempotent) run-cancel request."""

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    status: str
    cancelled: bool
    accepted: bool = False
    applied: bool = False
    action_status: str = "rejected_invalid_state"
    idempotency_key: str | None = None


class RunPermissionDecision(BaseModel):
    """One permission decision this run settled, as the audit log recorded it.

    Answers which tool call was approved or refused, with which option, and when.
    Carries no tool INPUT and no prompt text, so a caller reviewing what a run was
    permitted to do never has to read what it was asked to do.

    ``agent_id`` is nullable because it is genuinely not knowable at the decision
    seam rather than merely unset: the interrupt payload carries the tool, its
    input, and the options, but no agent. An unattributed decision is still a real
    record, and the alternative is fabricating attribution.
    """

    tool_name: str
    action: str
    option_id: str | None = None
    agent_id: str | None = None
    responded_at: datetime


class RunHistoryResponse(BaseModel):
    """The full read of one run, including terminal and archived ones.

    Deliberately distinct from run-status, which is the BOUNDED recovery
    snapshot an engine reconciles from. This is the wide read - transcript,
    agents, plan, pending answers, and the run's metadata - for a consumer that
    wants the whole record rather than the authority fields.

    The state snapshot is embedded by reference rather than restated field by
    field, so the two cannot drift apart as the snapshot evolves.

    The transcript is the one part of the record this verb cannot always
    deliver, because it lives only in the checkpoint. ``transcript_available``
    and ``transcript_status`` say so outright, so ``state.messages`` is never
    read as "this run had no conversation" when the truth is that its
    conversation could not be read. They are the transcript's counterpart to the
    snapshot's own ``snapshot_complete`` / ``degraded_reasons`` pairing.

    ``permission_decisions`` is the settled counterpart to the snapshot's PENDING
    permissions. A gate leaves the pending list the moment it is answered or the
    run ends, so without this the record of a decision a human actually made was
    durable in the audit log and readable nowhere - a run could be reviewed whole
    with no trace that anyone had approved anything.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    state: ThreadStateSnapshot
    metadata: ThreadMetadata | None = None
    transcript_available: bool
    transcript_status: TranscriptAvailability
    permission_decisions: list[RunPermissionDecision] = Field(default_factory=list)


class RunArchiveResponse(BaseModel):
    """Acknowledge a run moved to the archived state."""

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    status: ThreadStatus = ThreadStatus.ARCHIVED


class RunAgentSummary(BaseModel):
    """One agent's disclosed operational state in the team projection."""

    agent_id: str
    display_name: str | None = None
    state: str


class RunPendingPermission(BaseModel):
    """A permission awaiting an answer, addressed by the run that raised it."""

    request_id: str
    run_id: PathSafeRunId
    description: str | None = None
    request_status: str


class TeamStatusV1Response(BaseModel):
    """The team's live operational projection.

    Safe operational metadata only - which agents exist, what state they are in,
    which runs are active, and what is awaiting an answer. Never a credential,
    a prompt, or a document body.
    """

    api_version: Literal["v1"] = _API_VERSION
    agents: list[RunAgentSummary] = Field(default_factory=list)
    active_runs: list[str] = Field(default_factory=list)
    pending_permissions: list[RunPendingPermission] = Field(default_factory=list)


class RunDeleteResponse(BaseModel):
    """Report a deletion that finalized over state no pass could remove.

    Carried only on that one outcome. A clean deletion answers with no body at
    all, so the presence of this body IS the signal that external state was
    stranded. Names the KINDS of item left behind and nothing more: a concrete
    checkpoint id or artifact path is control-plane state and never the
    caller's to receive.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    deleted: Literal[True] = True
    cleanup_abandoned: Literal[True] = True
    abandoned_kinds: list[CleanupKind] = Field(min_length=1)


class RunMessageRequest(BaseModel):
    """Send a follow-up turn into a run that already exists.

    Run-start cannot express this: a repeat run identifier is a REPLAY, answered
    with the original run, so there is no way to say "same run, new input"
    through it. This is that verb.
    """

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=65536)
    agent_id: str | None = Field(default=None, max_length=128)


class RunMessageResponse(BaseModel):
    """Acknowledge a follow-up turn as accepted for dispatch.

    Acceptance is not completion: the turn is handed to the worker and the run
    continues asynchronously, so a caller reconciles progress from the stream or
    run-status rather than from this body.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    accepted: bool = True
    applied: bool = False
    action_status: str
    action_id: str | None = None
    idempotency_key: str | None = None


class RunPermissionRespondRequest(BaseModel):
    """Answer one permission request raised by a run.

    Carries the chosen option and, optionally, a reviewer comment. The options
    themselves were advertised on the versioned progress stream in the
    ``permission_request`` frame that raised the question, so the answer names
    one rather than restating it. ``notes`` survives into the verdict resume
    payload for a locally-respondable verdict-style pause (D6); it is ignored
    for a plain tool-permission response, which resumes on the bare option id.
    """

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2048)


class RunPermissionRespondResponse(BaseModel):
    """Report what an answer did, including when it did nothing.

    ``accepted`` says the answer was taken; ``applied`` reports whether the
    worker had durably confirmed applying this request's resolution when this
    response was assembled - never whether THIS call resumed the run. A first
    accepted answer therefore returns ``applied`` false with ``action_status``
    ``accepted_not_applied``: the resume is dispatched and application is
    confirmed asynchronously. A duplicate replays the stored outcome rather
    than acting twice - byte-identical to the first response until that
    confirmation lands, ``applied`` true after it - so a caller retrying after
    a lost response learns the current outcome instead of re-answering. An
    answer arriving after the request was already applied reports ``accepted``
    with ``applied`` true and ``action_status`` ``duplicate``.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    request_id: str
    accepted: bool
    applied: bool
    action_status: str
    approval_status: str | None = None
    idempotency_key: str | None = None


class RunClarificationRespondRequest(BaseModel):
    """Resolve a parked questionnaire with answers, a new prompt, or a decline.

    Carries exactly one outcome: legacy answers keyed by question id, a new
    prompt that continues the same run, or a payload-free decline that lets the
    run proceed with no answer given. The questions themselves were disclosed
    authoritatively by ``run-status``; the run id and request id address the
    questionnaire from the path, so no outcome restates what was asked.

    All bounds are imported from the domain contract rather than restated. The
    checks that need the parked questions in hand (an id nobody asked about, a
    required question left blank, a choice outside its declared options) are
    applied only to the answer outcome by the route against the checkpoint; a
    decline deliberately bypasses them because refusal is not an answer.

    ``decline`` admits only the literal ``true``: ``false`` would be a client
    saying "not declining" while supplying no other outcome, which is a
    contradiction better refused at the schema than interpreted.
    """

    model_config = ConfigDict(extra="forbid")

    answers: dict[QuestionId, AnswerText] | None = Field(
        default=None, max_length=MAX_QUESTIONS_PER_REQUEST
    )
    prompt: ContinuationPrompt | None = None
    decline: Literal[True] | None = None

    @model_validator(mode="after")
    def _require_one_resolution(self) -> RunClarificationRespondRequest:
        """Require exactly one unambiguous clarification outcome."""
        supplied = [
            outcome
            for outcome in (self.answers, self.prompt, self.decline)
            if outcome is not None
        ]
        if len(supplied) != 1:
            msg = "exactly one of answers, prompt, or decline is required"
            raise ValueError(msg)
        if self.prompt is not None and not self.prompt.strip():
            msg = "prompt must not be blank"
            raise ValueError(msg)
        return self


class RunClarificationRespondResponse(BaseModel):
    """Report the durable outcome of a questionnaire resolution.

    Identical retries replay the journal outcome without dispatch while a lease
    is fresh. ``applied`` becomes true only after the request-scoped checkpoint
    receipt matches the accepted resolution fingerprint, including when a retry
    follows a lost response after the graph already advanced.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    request_id: str
    accepted: bool
    applied: bool = False
    action_status: str
    idempotency_key: str | None = None


class RoleAssignmentSummary(BaseModel):
    """Effective per-role model assignment under a profile.

    Only safe operational metadata: role id, agent id, provider id, capability,
    the stable concrete model name, ordered fallbacks, current provider readiness,
    and which precedence layer the assignment came from. Never a credential, env
    value, token, or private path.

    ``provider_id`` is EMPTY when no preset layer declares a provider for the
    role, which is the ordinary state now that product presets carry no
    provider policy: a run chooses its lane at run start from the served catalog.
    Empty rather than absent so the field keeps one type, and never a substituted
    provider name - naming a lane no preset asked for would be indistinguishable
    from a real declaration. ``resolution_error`` carries the reason and ``source``
    reads ``undeclared``; the role is reported ineligible.

    ``provider_id`` is deliberately NOT typed by the ``Provider`` enumeration
    served beside it on the agent snapshot, even though the two carry the same
    concept. This surface replays FROZEN historical assignments, and two of its
    values are provably outside that enumeration: the empty string documented
    above, and a provider a past run froze that this build no longer knows -
    a case the disclosure path already handles explicitly by reporting it not
    ready rather than raising. Narrowing here would turn both into a validation
    failure on a read path. The reconciliation is therefore that these are two
    concepts: ``Provider`` is the closed set of lanes this build can RUN, and
    this is an identifier a past run RECORDED.
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
    # The topology enumeration the preset loader already validates against, not
    # a restatement of it: an unloadable preset has no topology and reads None.
    topology: TopologyType | None = None
    worker_count: int | None = None
    required_roles: list[str] = Field(default_factory=list)
    authoring_capability: str | None = None
    # True for bundled mock/test presets so the product layer can exclude them.
    is_mock: bool = False
    # model-profiles additions (additive v1 fields, absent-safe): the preset's
    # origin, the document outputs the topology delivers, the selectable
    # profiles with effective assignments and eligibility, and the default
    # profile id. The origin's legal values were previously stated only in this
    # comment, which is a declaration no client can read and no compiler can
    # check; they are now the enumeration the field is typed by.
    origin: PresetOrigin | None = None
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
    # Identity of THIS gateway process, distinct from its pid and its port. A
    # gateway that restarts on the same port is a different incarnation, and a
    # consumer comparing only host and port cannot tell the two apart - which is
    # how dispatch reached a worker still paired to a gateway that had exited.
    gateway_lifetime_id: str | None = None
    # The watchdog's raw observation, served as the vocabulary that watchdog
    # writes. Distinct from ``readiness.worker_state`` below, which is the
    # readiness ladder this is projected onto - see ``control.worker_status``.
    worker_status: WorkerConnectionStatus | None = None
    worker_connected: bool | None = None
    # What the worker reports about the pairing, echoed rather than asserted:
    # which gateway incarnation spawned it, and which spawn attempt it was.
    # A mismatch against gateway_lifetime_id means the worker belongs to another
    # gateway; both absent means the worker was not gateway-spawned at all.
    worker_paired_gateway_lifetime: str | None = None
    worker_generation: str | None = None
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
    # Free-form BY DESIGN, and not the same field as the run snapshot's list of
    # the same name. These are operator-readable sentences ("worker is down"),
    # one of them interpolated from the worker's own status, meant to be read
    # rather than matched. A client branching on service health reads the typed
    # facts under ``readiness``; nothing is expected to compare these to a
    # constant, so under this contract they are prose and not a vocabulary.
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
    run_id: PathSafeRunId
    lease_id: LeaseId
    terminal_status: ThreadStatus


# ``ServiceStateResponse.readiness`` forward-references ``DesktopReadiness``,
# defined below it; rebuild the model now that the target is in scope.
ServiceStateResponse.model_rebuild()
