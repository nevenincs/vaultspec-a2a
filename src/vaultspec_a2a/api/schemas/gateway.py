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
for the run-start verb mounted by :mod:`vaultspec_a2a.api.routes`. Commit binds
the exact role set to the exact replay request. ``lease_id`` is non-secret
coordination metadata, not a bearer credential; release applies only to an
uncommitted reservation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...context.metadata import ThreadMetadata
from ...control.readiness import (
    API_VERSION as _API_VERSION,
)
from ...control.readiness import (
    DesktopReadiness,
    ProviderEligibility,
    RunAdmission,
    WorkerLifecycleState,
)
from ...control.worker_status import WorkerConnectionStatus
from ...graph.enums import ProviderCondition, SemanticPhase
from ...providers.provider_catalog import (
    MAX_CONTROL_ID_LENGTH,
    MAX_CONTROLS,
    MAX_DISPLAY_LENGTH,
    MAX_FALLBACKS,
    MAX_PUBLIC_ID_LENGTH,
    MAX_TEXT_LENGTH,
)
from ...team.preset_origin import PresetOrigin
from ...team.team_config import AuthoringCapability, DocumentCapability, TopologyType
from ...thread.actor_tokens import MAX_ROLES_PER_RUN, ActorTokenBundle
from ...thread.clarification import (
    MAX_QUESTIONS_PER_REQUEST,
    AnswerText,
    ClarificationRequest,
    ContinuationPrompt,
    QuestionId,
)
from ...thread.constants import (
    MAX_AGENT_ID_CHARS,
    MAX_APPROVAL_REQUEST_ID_CHARS,
    MAX_DISCOVERY_RESULTS,
    MAX_FEATURE_TAG_LENGTH,
    MAX_FEEDBACK_BATCH_ID_CHARS,
    MAX_PERMISSION_OPTION_ID_CHARS,
    MAX_ROLE_ID_CHARS,
    MAX_RUN_ID_CHARS,
    MAX_RUN_MESSAGE_CHARS,
    MAX_RUN_TITLE_CHARS,
    MAX_TEAM_PRESET_CHARS,
    RUN_ID_PATTERN,
)
from ...thread.dispatch_policy import FailureType
from ...thread.enums import (
    ApprovalStatus,
    CleanupKind,
    DegradedReason,
    RepairStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ...thread.snapshots import QueuedMessageCount, RepairReason, ThreadStateSnapshot

__all__ = [
    "ActiveRunRecord",
    "ActiveRunsResponse",
    "FrozenTeamAssignmentSummary",
    "GatewayHealthResponse",
    "PathSafeRunId",
    "PresetSummary",
    "PresetsListResponse",
    "ProviderCatalogSelection",
    "RoleState",
    "RunAgentSummary",
    "RunArchiveResponse",
    "RunCancelResponse",
    "RunClarificationRespondRequest",
    "RunClarificationRespondResponse",
    "RunCommitResponse",
    "RunDeleteResponse",
    "RunHistoryResponse",
    "RunMessageRefusalCode",
    "RunMessageRefusalDetail",
    "RunMessageRefusalResponse",
    "RunMessageRequest",
    "RunMessageResponse",
    "RunPendingPermission",
    "RunPermissionDecision",
    "RunPermissionRefusalResponse",
    "RunPermissionRespondRequest",
    "RunPermissionRespondResponse",
    "RunPrepareResponse",
    "RunReleaseResponse",
    "RunStage",
    "RunStartRequest",
    "RunStartResponse",
    "RunStatusResponse",
    "RunSummariesResponse",
    "RunSummaryRecord",
    "ServiceStateResponse",
    "TeamStatusV1Response",
    "TerminalSettlement",
    "TopologyPosition",
]

# The run identity type, shared by the reservation identity (the server-minted
# opaque handle for a prepared admission slot) and the lease identity (the
# non-secret, run-scoped handle the dashboard revokes at terminal settlement).
# Both are minted in the run-id path-safe shape so they are addressable and
# log-safe, and neither is ever a bearer.
PathSafeRunId = Annotated[
    str,
    Field(min_length=1, max_length=MAX_RUN_ID_CHARS, pattern=RUN_ID_PATTERN),
]


class ProviderCatalogSelection(BaseModel):
    """One explicit schema-v1 reference to a served provider catalog entry."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    provider_id: str = Field(min_length=1, max_length=MAX_PUBLIC_ID_LENGTH)
    execution_mode: str = Field(min_length=1, max_length=MAX_PUBLIC_ID_LENGTH)
    catalog_revision: str = Field(min_length=1, max_length=MAX_PUBLIC_ID_LENGTH)
    entry_id: str = Field(min_length=1, max_length=MAX_PUBLIC_ID_LENGTH)
    controls: dict[
        Annotated[str, Field(min_length=1, max_length=MAX_CONTROL_ID_LENGTH)],
        Annotated[str, Field(min_length=1, max_length=MAX_PUBLIC_ID_LENGTH)],
    ] = Field(default_factory=dict, max_length=MAX_CONTROLS)


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
    reservation_id: PathSafeRunId | None = None
    # A non-empty preset is mandatory on the v1 verb: the engine-facing contract
    # never creates the internal surface's non-dispatched draft.
    team_preset: str = Field(min_length=1, max_length=MAX_TEAM_PRESET_CHARS)
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
    title: str | None = Field(default=None, max_length=MAX_RUN_TITLE_CHARS)
    # Target feature tag for document-authoring runs. Bounded; the eligibility
    # policy requires it for document-authoring presets. Falls back to
    # metadata.feature_tag when the field is omitted.
    feature_tag: str | None = Field(default=None, max_length=MAX_FEATURE_TAG_LENGTH)
    # Client-supplied stable run/idempotency id. Explicit provider selection is
    # replay-safe only when every start owns a durable caller identity.
    run_id: PathSafeRunId
    continues_run_id: PathSafeRunId | None = None
    # Explicit whole-team catalog choice. New runs have no implicit profile or
    # provider default; every selected value must revalidate against the current
    # workspace catalog before admission.
    selection: ProviderCatalogSelection
    overrides: dict[
        Annotated[str, Field(min_length=1, max_length=MAX_ROLE_ID_CHARS)],
        ProviderCatalogSelection,
    ] = Field(default_factory=dict, max_length=MAX_ROLES_PER_RUN)
    fallbacks: list[ProviderCatalogSelection] = Field(
        default_factory=list, max_length=MAX_FALLBACKS
    )
    # feedback-loop: an OPAQUE engine feedback-batch id for a revision run. a2a
    # never parses or owns batch content; it transports only the id
    # and the worker retrieves the authoritative feedback context from the engine
    # batch read route. Bounded; content-addressed ("feedback-batch:<digest>").
    feedback_batch_id: str | None = Field(
        default=None, min_length=1, max_length=MAX_FEEDBACK_BATCH_ID_CHARS
    )

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
            self._validate_prepare()
        if self.stage == RunStage.COMMIT and self.reservation_id is None:
            raise ValueError("commit requires a reservation id")
        if self.stage == RunStage.RELEASE:
            self._validate_release()
        return self

    def _validate_prepare(self) -> None:
        if self.actor_tokens is not None:
            raise ValueError("prepare must not carry actor tokens")
        if self.reservation_id is not None:
            raise ValueError("prepare must not carry a reservation id")

    def _validate_release(self) -> None:
        if self.reservation_id is None:
            raise ValueError("release requires a reservation id")
        if self.actor_tokens is not None:
            raise ValueError("release must not carry actor tokens")


class FrozenNativeControlSummary(BaseModel):
    """One exact provider-native value frozen for historical disclosure."""

    control_id: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    option_id: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    provider_value: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    display_name: str | None = Field(default=None, max_length=MAX_DISPLAY_LENGTH)
    option_display_name: str | None = Field(default=None, max_length=MAX_DISPLAY_LENGTH)


class FrozenExecutionSnapshotSummary(BaseModel):
    """Catalog provenance and exact provider inputs for one execution lane."""

    provider_id: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    provider_display_name: str | None = Field(
        default=None, max_length=MAX_DISPLAY_LENGTH
    )
    execution_mode: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    catalog_revision: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    entry_id: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    model_name: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    model_display_name: str | None = Field(default=None, max_length=MAX_DISPLAY_LENGTH)
    controls: list[FrozenNativeControlSummary] = Field(
        default_factory=list, max_length=MAX_CONTROLS
    )


class FrozenSelectionProvenanceSummary(BaseModel):
    """Bounded admission layer that supplied one role's primary lane."""

    selection_source: Literal["team_selection", "role_override"]


class FrozenRoleAssignmentSummary(FrozenExecutionSnapshotSummary):
    """One role's exact primary and ordered fallback execution snapshots."""

    role_id: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    agent_id: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    fallbacks: list[FrozenExecutionSnapshotSummary] = Field(
        default_factory=list, max_length=MAX_FALLBACKS
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
    # The complete execution authority the run was frozen with: the exact served
    # catalog selection that will produce this run's work.
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
    reservation_id: PathSafeRunId
    lease_id: PathSafeRunId
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
    lease_id: PathSafeRunId
    semantic_status: SemanticPhase = SemanticPhase.STARTING
    nickname: str | None = None
    # As on RunStartResponse, this is the exact execution authority disclosure.
    frozen_assignment: FrozenTeamAssignmentSummary | None = None


class RunReleaseResponse(BaseModel):
    """Acknowledge explicit release of an uncommitted reservation."""

    api_version: Literal["v1"] = _API_VERSION
    stage: Literal["released"] = "released"
    reservation_id: PathSafeRunId
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
    runs: list[ActiveRunRecord] = Field(
        default_factory=list, max_length=MAX_DISCOVERY_RESULTS
    )
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
    title: str | None = Field(default=None, max_length=MAX_RUN_TITLE_CHARS)
    nickname: str | None = Field(default=None, max_length=128)
    team_preset: str | None = Field(default=None, max_length=MAX_TEAM_PRESET_CHARS)
    # The projection's verdict on this run's recoverability. A caller scanning
    # history for work that needs attention reads these, and they are the whole
    # reason this record exists rather than the discovery one.
    # All three answer from a closed set the service fixes, so they are served
    # as the enumerations that already own them rather than as bounded strings.
    # ``execution_readiness`` is derived from ``repair_status``: it is the same
    # posture read as whether the run is fit to resume, so the two share one
    # vocabulary and always agree.
    repair_status: RepairStatus | None = None
    execution_readiness: RepairStatus | None = None
    approval_status: ApprovalStatus | None = None
    approval_request_id: str | None = Field(
        default=None, max_length=MAX_APPROVAL_REQUEST_ID_CHARS
    )
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
    runs: list[RunSummaryRecord] = Field(
        default_factory=list, max_length=MAX_DISCOVERY_RESULTS
    )
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


# Two kinds of field below, and the split is the point. The ones carrying a
# comment are run-status's OWN: the api envelope, the product projections of a
# position, and the staged-admission identities. Every other field belongs to the
# Layer-1 run read model (``thread/snapshots.ThreadStateSnapshot``) and is carried
# here under that type with no second bound, default or vocabulary - a second
# declaration drifts, and these did: the provider condition reached one surface as
# its enum and the other as a bare string, and the frame cursor was required on
# one and defaulted on the other. Why each read-model field exists is documented
# once, on the read model, and `test_run_status_derives_from_read_model.py` holds
# the two surfaces to one published shape per shared field.
class RunStatusResponse(BaseModel):
    """The authoritative recovery snapshot for a run.

    Designed as the read a restarted A2A resumes or reports a run from: topology
    position, per-role state, and the engine proposal/changeset ids the run has
    produced, plus the checkpoint cursor and repair posture. Non-authoritative
    SSE progress frames may be lost freely; this snapshot is the source of truth.

    Every relay frame is droppable, so this response is where a reloading client
    with no live stream recovers the run's failure condition, its queue depth and
    the question it is parked on.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    continues_run_id: PathSafeRunId | None = None
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
    last_sequence: int
    # Whether this run's progress stream can be RESUMED from the id its frames
    # carry, as opposed to merely re-attached. The two postures are otherwise
    # indistinguishable without probing: a stream that serves no replay emits
    # no id at all, so a client would have to attach, wait for a frame, and
    # find no id on it to learn what this field says outright. False whenever
    # retention is switched off for the service or nothing is retained for
    # this run - a settled run whose window has expired, or one that has yet
    # to emit a frame. Additive, and never a statement about run state: a
    # resumable stream and an authoritative one are different things, and this
    # response remains the authority either way.
    stream_resumable: bool = False
    queued_messages: QueuedMessageCount = 0
    repair_status: RepairStatus | None = None
    execution_readiness: RepairStatus | None = None
    degraded_reasons: list[DegradedReason] = Field(default_factory=list)
    failure_reason: str | None = None
    provider_condition: ProviderCondition | None = None
    repair_reason: RepairReason | None = None
    frozen_assignment: FrozenTeamAssignmentSummary | None = None
    # Non-secret staged-admission lease identity. It lets the dashboard repair
    # a locally reserved hash bundle after a process crash that followed remote
    # commit but preceded the local binding write.
    lease_id: PathSafeRunId | None = None
    # The persisted prepare reservation paired with ``lease_id``. This lets a
    # dashboard reconcile only the exact local reservation after a lost reply.
    reservation_id: PathSafeRunId | None = None
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

    run_id: PathSafeRunId
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

    content: str = Field(min_length=1, max_length=MAX_RUN_MESSAGE_CHARS)
    agent_id: str | None = Field(default=None, max_length=MAX_AGENT_ID_CHARS)


class RunMessageResponse(BaseModel):
    """Acknowledge a follow-up turn as queued behind the run's current turn.

    Acceptance is not execution and it is not even dispatch: the turn is
    reserved in the run's journal with a place in its queue, and it reaches
    the worker only once the turn now running has proven its terminal
    checkpoint. A caller reconciles progress from the stream or run-status,
    never from this body.

    ``queue_position`` is where this turn sits, counting from one, and it is
    stable across a replay of the same key: a caller that lost this response
    and retried reads the same place rather than a new one. ``None`` only for
    a response that reserved nothing.

    ``idempotency_key`` is the caller's own key echoed back, never a derived
    one, because this verb has no default to derive: it is required on the
    request, so an accepted turn always has a key and it is always the one the
    caller chose.
    """

    api_version: Literal["v1"] = _API_VERSION
    run_id: PathSafeRunId
    accepted: bool = True
    applied: bool = False
    action_status: str
    action_id: str | None = None
    idempotency_key: str
    queue_position: int | None = Field(default=None, ge=1)


class RunMessageRefusalCode(StrEnum):
    """The conditions a run action can be refused for.

    A closed subset of the dispatch failure vocabulary, so the published
    contract names only what this refusal can carry rather than every failure
    the gateway knows. Each value is spelled as its failure-type counterpart.

    Shared by every verb that reaches the worker through a run dispatch, not
    only the follow-up turn: the same worker refusal must mean the same thing
    whichever verb met it.
    """

    INPUT_REQUIRED = FailureType.INPUT_REQUIRED.value
    TERMINAL = FailureType.TERMINAL.value
    CONFLICT = FailureType.CONFLICT.value
    INCOMPATIBLE_STATE = FailureType.INCOMPATIBLE_STATE.value
    RUN_BUSY = FailureType.RUN_BUSY.value
    # A run that would have taken the turn and has nowhere to put it: its own
    # continuation queue, or the service-wide one, is already spent. Distinct
    # from RUN_BUSY, which says the run admits no continuation at all.
    QUEUE_FULL = FailureType.QUEUE_FULL.value


class RunMessageRefusalDetail(BaseModel):
    """Why a follow-up turn was refused, in terms a program can match.

    The refusals this verb can raise are several distinct conditions sharing one
    status code, and a prose message is the wrong place for a consumer to learn
    which one it met. ``code`` is the closed refusal vocabulary; ``message`` is
    the same sentence an operator reads. A refused follow-up changed nothing, so
    the consumer's next move is always to re-read run-status rather than to
    reconcile from this body.
    """

    code: RunMessageRefusalCode
    message: str = Field(max_length=1024)


class RunMessageRefusalResponse(BaseModel):
    """The body served for a refused follow-up turn."""

    detail: RunMessageRefusalDetail


class RunPermissionRefusalResponse(BaseModel):
    """The body served when a permission answer is refused with a conflict.

    Two shapes, deliberately stated as one union rather than as one shape the
    verb does not always serve. A worker that refused the dispatch is reported
    with the typed refusal every run action shares, because the condition is
    the dispatch outcome and a consumer must be able to tell a busy run from a
    request it should never send again. The guards this verb applies before
    anything is dispatched - an answer to a request that is no longer pending,
    an option the request never offered, a key already bound to a different
    answer - carry a plain sentence, because they are conditions of this
    request rather than of reaching the worker.
    """

    detail: RunMessageRefusalDetail | str


class RunPermissionRespondRequest(BaseModel):
    """Answer one permission request raised by a run.

    Carries the chosen option and, optionally, a reviewer comment. The options
    themselves were advertised on the versioned progress stream in the
    ``permission_request`` frame that raised the question, so the answer names
    one rather than restating it. ``notes`` survives into the verdict resume
    payload for a locally-respondable verdict-style pause; it is ignored
    for a plain tool-permission response, which resumes on the bare option id.
    """

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=MAX_PERMISSION_OPTION_ID_CHARS)
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
    # Says WHETHER this preset authors documents; ``supported_capabilities``
    # below says WHICH. Both are descriptive: nothing in run admission reads
    # either, so a wrong value here misinforms a reader rather than refusing a
    # run. See the owning module on the topology-versus-role keying question.
    authoring_capability: AuthoringCapability | None = None
    # The origin and document outputs are descriptive preset facts.
    origin: PresetOrigin | None = None
    supported_capabilities: list[DocumentCapability] = Field(default_factory=list)


class PresetsListResponse(BaseModel):
    """List of available team presets."""

    api_version: Literal["v1"] = _API_VERSION
    presets: list[PresetSummary] = Field(default_factory=list)


class GatewayHealthResponse(BaseModel):
    """The unarmed profile's probe body on ``GET /health``.

    Declared because this is the one surface an external prober has, and it
    was published as an untyped object: a reader of the contract learned no
    field name, no status vocabulary, and no way to tell this body from the
    armed profile's minimal liveness one.

    Open on purpose. The fields below are the ones the endpoint itself
    guarantees on every answer, including the degraded answer it gives when a
    runtime singleton is missing; the probe aggregate carries further
    dependency checks whose set depends on what this build probes, and
    publishing them as a closed shape would promise a client a stability the
    aggregate does not have. ``additionalProperties`` says so rather than
    leaving the whole body unnamed.
    """

    model_config = ConfigDict(extra="allow")

    service: Literal["gateway"] = "gateway"
    #: The probe verdict across every dependency this build checks.
    status: str = Field(max_length=32)
    #: The NARROWER local question: is this gateway's own worker usable. Not a
    #: restatement of ``status``; see the endpoint for why the two differ.
    ready: bool
    #: The live process id, so a lifecycle caller can confirm the owner of a
    #: discovery record is the process answering here.
    pid: int


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
    # How long THIS process spent running its dependency probes, measured by the
    # process that ran them. Additive v1 diagnostic: a caller's own stopwatch
    # also measures transport and host scheduling, so it cannot distinguish a
    # gateway that over-ran its probe deadline from a host that was busy. An
    # operator - and the deadline proof in the live gateway suite - reads this.
    probe_elapsed_ms: int | None = None
    # Free-form BY DESIGN, and not the same field as the run snapshot's list of
    # the same name. These are operator-readable sentences ("worker is down"),
    # one of them interpolated from the worker's own status, meant to be read
    # rather than matched. A client branching on service health reads the typed
    # facts under ``readiness``; nothing is expected to compare these to a
    # constant, so under this contract they are prose and not a vocabulary.
    degraded_reasons: list[str] = Field(default_factory=list)
    # Sorted "METHOD path" signature of the live route table (see
    # ``route_signature``, exported by ``api.routes``). The doctor CLI diffs this
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
    lease_id: PathSafeRunId
    terminal_status: ThreadStatus


# Resolve the readiness annotation to the imported desktop wire model.
ServiceStateResponse.model_rebuild()
