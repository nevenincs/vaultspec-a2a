"""The versioned gateway surface.

Mounts the run, preset, and service verbs under ``/v1`` as the engine-facing
edge, including bounded discovery and the droppable ``run-stream`` companion to
the authoritative status snapshot. Each verb reshapes an existing service
rather than reinventing it, so there is a single code path: the richer internal
``/api`` surface and these verbs call the same services beneath.

Run start composes :mod:`vaultspec_a2a.control.admission` and
:mod:`vaultspec_a2a.control.health` into ``start``, readiness-gated ``prepare``,
exact ``commit``, and uncommitted-reservation ``release`` stages. A committed
run persists its non-secret lease identifier and exact replay digest. Dispatch
exactly once under that replay contract is not end-to-end exactly-once delivery,
and a lease identifier is never a bearer credential.
"""

import asyncio
import hmac
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...context.metadata import ThreadMetadata
from ...control.admission import AdmissionBroker, AdmissionReadiness
from ...control.cancel_service import cancel_thread, raise_for_cancel_failure
from ...control.clarification_service import respond_to_clarification
from ...control.config import settings
from ...control.drain import DrainGate
from ...control.health import (
    assemble_desktop_readiness,
    build_full_health,
    probe_engine_discovery_freshness,
)
from ...control.message_service import send_followup_message
from ...control.permission_service import respond_to_permission
from ...control.run_discovery_service import discover_active_runs
from ...control.run_start_policy import (
    evaluate_execution_eligibility,
    evaluate_run_start_eligibility,
    required_role_ids,
)
from ...control.team_service import build_team_status
from ...control.thread_service import (
    ThreadCreationRequest,
    archive_thread,
    create_and_dispatch_thread,
    delete_thread_service,
    list_threads_service,
    process_metadata,
)
from ...control.thread_state_service import (
    capture_thread_state,
    derive_run_authoring_ids,
    derive_run_semantic_context,
    project_semantic_phase,
)
from ...database import (
    get_db,
    get_permission_logs_by_thread,
    get_permission_request,
    get_thread,
    get_thread_metadata,
    normalize_workspace_identity,
)
from ...database.checkpoints import Checkpointer
from ...domain_config import domain_config
from ...providers.provider_catalog import (
    ControlSelection,
    ProviderRecord,
    SelectionReference,
)
from ...providers.provider_catalog_service import (
    ProviderCatalogScopeCapacityError,
    ProviderCatalogService,
)
from ...providers.team_selection import (
    FrozenTeamSelection,
    TeamSelectionError,
    freeze_team_selection,
    normalize_replay_selection,
)
from ...streaming.aggregator import EventAggregator
from ...thread.clarification import (
    ClarificationAnswers,
    ClarificationContinuation,
    ClarificationDecline,
    ClarificationResolution,
    pending_clarification,
)
from ...thread.constants import DEFAULT_SUPERVISOR_ID
from ...thread.dispatch_policy import FailureType
from ...thread.enums import (
    TERMINAL_STATUSES,
    PermissionRequestStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ...thread.errors import NicknameConflictError
from .._utils import mark_worker_connected, trace_headers
from ..dependencies import (
    get_aggregator,
    get_checkpointer,
    get_circuit_breaker,
    get_services,
    get_worker_client,
    get_worker_spawner,
    require_attach,
)
from ..run_admission import (
    commit_singleflight,
    replay_digest_matches,
    request_digest,
    stamped_replay_digest,
)
from ..schemas.gateway import (
    ActiveRunRecord,
    ActiveRunsResponse,
    FrozenTeamAssignmentSummary,
    PathSafeRunId,
    PresetsListResponse,
    PresetSummary,
    ProfileSummary,
    ProviderCatalogSelection,
    RoleAssignmentSummary,
    RoleState,
    RunAgentSummary,
    RunArchiveResponse,
    RunCancelResponse,
    RunClarificationRespondRequest,
    RunClarificationRespondResponse,
    RunCommitResponse,
    RunDeleteResponse,
    RunHistoryResponse,
    RunMessageRequest,
    RunMessageResponse,
    RunPendingPermission,
    RunPermissionDecision,
    RunPermissionRespondRequest,
    RunPermissionRespondResponse,
    RunPrepareResponse,
    RunReleaseResponse,
    RunStage,
    RunStartRequest,
    RunStartResponse,
    RunStatusResponse,
    RunSummariesResponse,
    RunSummaryRecord,
    ServiceStateResponse,
    TeamStatusV1Response,
    TopologyPosition,
    WorkerLifecycleState,
)
from ..schemas.provider_catalog import ProviderCatalogResponse
from ..schemas.snapshots import ThreadStateSnapshot
from ..thread_stream import build_thread_stream_response

router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(require_attach)],
)
logger = logging.getLogger(__name__)

# Health-check statuses that represent a genuine dependency failure (as opposed
# to informational states like worker_spawned="yes"); these populate
# service-state degraded_reasons.
_DEGRADED_CHECK_STATUSES: frozenset[str] = frozenset(
    {"error", "open", "down", "restarting", "half_open", "timeout"}
)
_JSON_OBJECT = TypeAdapter(dict[str, object])


def provider_catalog_service(app: FastAPI) -> ProviderCatalogService:
    """Return the process-wide bounded provider-catalog service."""
    service = getattr(app.state, "provider_catalog_service", None)
    if service is None:
        service = ProviderCatalogService()
        app.state.provider_catalog_service = service
    return service


def _object_mapping(value: object) -> dict[str, object] | None:
    """Narrow an unstructured value to an object-keyed mapping."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError:
        return None


def _metadata_object(metadata_json: str | None) -> dict[str, object] | None:
    """Decode durable metadata only when it is a JSON object."""
    if not metadata_json:
        return None
    try:
        decoded: object = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return _object_mapping(decoded)


def _string_field(record: dict[str, object], field: str) -> str | None:
    value = record.get(field)
    return value if isinstance(value, str) else None


def _bool_field(record: dict[str, object], field: str) -> bool | None:
    value = record.get(field)
    return value if isinstance(value, bool) else None


def admission_gate(app: FastAPI) -> DrainGate:
    """Return the process-wide run-admission drain gate, creating it once.

    One :class:`DrainGate` per gateway process, seated on ``app.state`` so the
    run verbs here and the administrative stop path (gateway shutdown /
    receipt-bound admin shutdown, wired where those handlers live) share the
    single authority: run-start admits against it, and the stop path closes
    admission and drains it before bounded cancellation. Get-or-create is atomic
    on the single event loop - there is no await between the read and the store.
    """
    gate = getattr(app.state, "drain_gate", None)
    if gate is None:
        gate = DrainGate()
        app.state.drain_gate = gate
    return gate


def admission_broker(app: FastAPI) -> AdmissionBroker:
    """Return the process-wide run-admission reservation broker, creating it once.

    One :class:`AdmissionBroker` per gateway process, seated on ``app.state``
    beside the drain gate. The prepare and commit stages of run-start share it: a
    reservation is bounded by the configured concurrent-run capacity. Get-or-create
    is atomic on the single event loop - there is no await between read and store.
    """
    broker = getattr(app.state, "admission_broker", None)
    if broker is None:
        broker = AdmissionBroker(
            max_reservations=domain_config.max_concurrent_threads,
            reservation_ttl_seconds=domain_config.admission_reservation_ttl_seconds,
        )
        app.state.admission_broker = broker
    return broker


def _admission_readiness(
    app_state: Any,
    *,
    worker_probe_ready: bool | None = None,
    worker_adoptable: bool | None = None,
) -> AdmissionReadiness:
    """Project the seated desktop readiness facts into an admission-readiness view.

    Reads the single readiness authority (``assemble_desktop_readiness``) over the
    seated worker and database state - the cheap, non-blocking surface - so a
    prepare reports the same worker, provider, and admission facts the readiness
    model and service-state verb serve, never a second computation.
    """
    readiness = assemble_desktop_readiness(
        app_state=app_state,
        worker_probe_ready=worker_probe_ready,
        worker_adoptable=worker_adoptable,
    )
    return AdmissionReadiness(
        worker_state=readiness.worker_state,
        provider_eligibility=readiness.provider_eligibility,
        eligible_providers=tuple(readiness.eligible_providers),
        run_admission=readiness.run_admission,
        reasons=tuple(readiness.reasons),
    )


async def _probe_admission_readiness(
    app_state: Any, worker_client: httpx.AsyncClient
) -> AdmissionReadiness:
    from ...control.worker_management import (
        probe_worker_health,
        worker_ready_and_ours,
    )

    probe = await probe_worker_health(settings.worker_url, client=worker_client)
    reachable = probe.healthy
    # An indeterminate probe (the worker did not answer inside the budget) is not
    # an observation of absence, so it must not be reported as one: pass no live
    # verdict and let the readiness authority fall back to the watchdog's seated
    # worker state. A worker compiling a graph for an already-admitted run is
    # unresponsive for seconds, and refusing an unrelated admission on that basis
    # made every concurrent run-start fail while the first one booted.
    probe_verdict: bool | None = None if probe.indeterminate else reachable
    # Reachability and provenance are different questions, and admission needs
    # both: "some process holds this port" is exactly what a squatting orphan
    # satisfies. Only asked when the port answered at all, so the refusal path
    # costs nothing extra.
    #
    # The generation must come from the spawner that issued it. It is the highest
    # generation this gateway has minted, and a worker reporting a HIGHER one
    # classifies as unidentified - so defaulting it to zero here would disown our
    # own restarted worker on its own admission path.
    spawner = getattr(app_state, "worker_spawner", None)
    generation = getattr(spawner, "generation", 0)
    adoptable: bool | None
    if probe.indeterminate:
        # Provenance is unknown for the same reason health is; the promotion this
        # feeds requires an affirmative True, so None neither promotes nor demotes.
        adoptable = None
    else:
        adoptable = reachable and await worker_ready_and_ours(
            settings.worker_url, current_generation=generation
        )
    return _admission_readiness(
        app_state, worker_probe_ready=probe_verdict, worker_adoptable=adoptable
    )


# ---------------------------------------------------------------------------
# run-start
# ---------------------------------------------------------------------------


@router.post(
    "/runs",
    response_model=(
        RunStartResponse | RunPrepareResponse | RunCommitResponse | RunReleaseResponse
    ),
    status_code=201,
)
async def run_start_endpoint(
    request: Request,
    body: RunStartRequest,
    services: tuple[
        AsyncSession, EventAggregator, Checkpointer, httpx.AsyncClient
    ] = Depends(get_services),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> RunStartResponse | RunPrepareResponse | RunCommitResponse | RunReleaseResponse:
    """Start, prepare, commit, or release through the single run-start verb.

    The ``stage`` selector splits one verb into four shapes without growing the
    verb set: ``prepare`` reserves bounded capacity without tokens or a durable
    run; ``commit`` binds the exact actor-token role set to that reservation;
    ``release`` frees only an uncommitted reservation; and ``start`` (the
    default) preserves the one-shot engine/Compose path.
    """
    db, _aggregator, _checkpointer, worker_client = services
    if body.stage == RunStage.PREPARE:
        return await _run_prepare(request, body, worker_spawner, worker_client)
    if body.stage == RunStage.COMMIT:
        return await _run_commit(
            request, body, db, circuit_breaker, worker_spawner, worker_client
        )
    if body.stage == RunStage.RELEASE:
        return await _run_release(request, body)
    return await _run_direct_start(
        request, body, db, circuit_breaker, worker_spawner, worker_client
    )


@dataclass(frozen=True, slots=True)
class _RunDispatchResult:
    """The normalised outcome of creating and dispatching one durable run."""

    thread_id: str
    status: str
    nickname: str | None
    frozen: Any | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class _RunLeaseBinding:
    lease_id: str
    reservation_id: str
    commit_digest: str


async def _create_run_core(
    request: Request,
    body: RunStartRequest,
    db: AsyncSession,
    circuit_breaker: Any,
    worker_spawner: Any,
    worker_client: httpx.AsyncClient,
    *,
    commit_binding: _RunLeaseBinding | None,
) -> _RunDispatchResult:
    """Create and dispatch one durable run - the shared start/commit core.

    Refuses before any durable state is created: an unloadable preset, a
    document-authoring preset with no target feature, or an actor-token bundle
    that does not cover the preset's roles all raise a 4xx. A client-supplied
    ``run_id`` makes creation dispatch-exactly-once under retry. When
    *commit_binding* is supplied, the commit path persists it into the run's
    metadata so terminal settlement and restart reconciliation can recover the
    run's non-secret lease and replay identity durably.
    """
    # Client idempotency: a retry with the same stable run id returns the
    # existing run rather than starting a second one (dispatch-exactly-once).
    existing = await get_thread(db, body.run_id)
    if existing is not None:
        _replay_identity_or_conflict(existing.id, existing.thread_metadata, body)
        return _RunDispatchResult(
            thread_id=existing.id,
            status=existing.status,
            nickname=existing.nickname,
            frozen=_read_persisted_team_selection(existing.thread_metadata),
            replayed=True,
        )
    run_id = body.run_id

    # Thread the target feature onto the metadata so it reaches dispatch and the
    # vault index; the top-level field is authoritative when both are present.
    # ``process_metadata`` enriches its input with the generated nickname and
    # discovered context. Keep that durable enrichment off the request object:
    # the replay digest describes what the caller sent, and the same request on
    # a later retry has not yet been enriched.
    metadata = (
        body.metadata.model_copy(deep=True) if body.metadata is not None else None
    )
    if body.feature_tag and metadata is not None:
        metadata = metadata.model_copy(update={"feature_tag": body.feature_tag})
    # Thread the opaque feedback-batch id onto the metadata the same way, so it
    # reaches dispatch (and persists for restart). a2a never parses it - the
    # worker retrieves the authoritative batch from the engine read route.
    if body.feedback_batch_id and metadata is not None:
        metadata = metadata.model_copy(
            update={"feedback_batch_id": body.feedback_batch_id}
        )

    try:
        ws_root, nickname, metadata_json = process_metadata(
            metadata, run_id, body.team_preset
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("commit step: load_preset")
    team_config = _load_preset_or_refuse(body.team_preset, ws_root)
    effective_feature = body.feature_tag or (
        metadata.feature_tag if metadata is not None else None
    )
    eligibility = evaluate_run_start_eligibility(
        team_config,
        feature_tag=effective_feature or None,
        actor_tokens=body.actor_tokens,
        harness=_probe_harness(team_config, ws_root),
    )
    if not eligibility.eligible:
        raise HTTPException(status_code=422, detail=eligibility.reason)

    logger.info("commit step: validate_selection")
    frozen = await _validate_and_freeze_selection_or_refuse(
        request.app, body, team_config, ws_root
    )
    canonical_body = _body_with_frozen_selection(body, frozen)
    metadata_json = _persist_team_selection(metadata_json, frozen)
    # Persist what this run was started with, so a later replay is compared
    # against the whole request rather than one field of it. The stamped form
    # records the rule it was computed under: raw tokens are never persisted, so
    # a stored fingerprint cannot be recomputed and a rule change would
    # otherwise refuse a byte-identical replay of an older run.
    metadata_json = _persist_request_digest(
        metadata_json, stamped_replay_digest(canonical_body)
    )
    # Bind the committed reservation's non-secret lease identity to the run,
    # durably, so terminal settlement and post-restart reconciliation recover it.
    if commit_binding is not None:
        metadata_json = _persist_lease(metadata_json, commit_binding)

    # Admission gate: a draining gateway refuses a new run before any durable
    # state is created, so drain closes admission ahead of bounded cancellation.
    # An admitted run joins the active set the drain waits on and is released
    # from it by whichever of these ends its execution first: the worker's
    # terminal event (``control.event_handlers._handle_terminal_event``, the
    # primary release for any run that actually executes), a dispatch failure
    # that settled the run FAILED - the start-path one below, or a follow-up
    # one in the messages route or the WS dispatch handler - a cancel that
    # settles the run terminally (``run_cancel_endpoint``), or here, in the
    # finally, on EVERY path that leaves no durable run. Release is an
    # idempotent discard, so more than one of them firing is harmless.
    gate = admission_gate(request.app)
    admission = await gate.admit(run_id)
    if not admission.admitted:
        raise HTTPException(status_code=503, detail=admission.reason)

    # A run is "persisted" once ``create_and_dispatch_thread`` returns (or an
    # integrity race resolves to a durable winner); only then does the run own its
    # admission until its terminal outcome. Any failure before that - a nickname
    # conflict, a winnerless integrity race, or any unexpected exception - must
    # release the admission in the finally, or the drain gate would carry a phantom
    # active run forever and never quiesce.
    persisted = False
    try:
        try:
            result = await create_and_dispatch_thread(
                db,
                ThreadCreationRequest(
                    thread_id=run_id,
                    title=body.title,
                    initial_message=body.message,
                    team_preset=body.team_preset,
                    autonomous=body.autonomous,
                    nickname=nickname,
                    metadata=metadata,
                    metadata_json=metadata_json,
                    workspace_root=ws_root,
                    actor_tokens=body.actor_tokens,
                    profile_id=None,
                    model_assignment=frozen.compiler_map(),
                ),
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                worker_client=worker_client,
                recursion_limit=domain_config.graph_recursion_limit,
                trace_headers=trace_headers(),
            )
        except NicknameConflictError as exc:
            # No durable run was created; the finally drops the unused admission.
            raise HTTPException(
                status_code=409,
                detail=f"Run nickname already exists: {exc.nickname!r}",
            ) from exc
        except IntegrityError as exc:
            # Insert-or-return idempotency: two simultaneous requests with the same
            # run_id race past the check-then-act guard above; the loser's insert
            # hits the primary-key unique violation. Roll back and resolve against
            # the winner's run rather than a 500.
            await db.rollback()
            winner = await get_thread(db, run_id)
            if winner is not None:
                # The winner owns the durable run and its admission from here on,
                # whichever way the identity check below resolves; releasing the
                # admission on the loser's path would drop the winner's active run
                # out of the drain gate.
                persisted = True
                logger.info(
                    "Run %s lost a concurrent insert race for its run id; "
                    "resolving the losing request against the durable winner",
                    run_id,
                )
                # A racing loser gets exactly the identity check a sequential
                # replay gets: same run id plus the same request is the winner's
                # run replayed, and a colliding body is a different intention that
                # must be refused rather than answered with someone else's run.
                _replay_identity_or_conflict(winner.id, winner.thread_metadata, body)
                return _RunDispatchResult(
                    thread_id=winner.id,
                    status=winner.status,
                    nickname=winner.nickname,
                    frozen=_read_persisted_team_selection(winner.thread_metadata),
                    replayed=True,
                )
            if nickname is not None and "nickname" in str(exc).lower():
                raise HTTPException(
                    status_code=409,
                    detail=f"Run nickname already exists: {nickname!r}",
                ) from exc
            raise

        # The durable run row now exists and owns its admission; the finally no
        # longer releases it, because a durable run is released by its terminal
        # event in the relay handler.
        persisted = True
        if result.dispatched:
            mark_worker_connected(request)

        # A dispatch failure the policy resolved to FAILED is the one durable
        # outcome no terminal event ever follows: the run is already terminal and
        # no worker ever ran it, so nothing would later release its admission.
        # Release it here, before the failure is raised, or the gate carries a
        # dead run forever.
        if (
            result.failure_type is not None
            and result.status == ThreadStatus.FAILED.value
        ):
            await gate.release(run_id)

        _raise_for_dispatch_failure(result.failure_type, result.error_detail)

        return _RunDispatchResult(
            thread_id=result.thread_id,
            status=result.status,
            nickname=result.nickname,
            frozen=frozen,
            replayed=False,
        )
    finally:
        if not persisted:
            await gate.release(run_id)


async def _run_direct_start(
    request: Request,
    body: RunStartRequest,
    db: AsyncSession,
    circuit_breaker: Any,
    worker_spawner: Any,
    worker_client: httpx.AsyncClient,
) -> RunStartResponse:
    """One-shot start: create and dispatch a run in a single call (unchanged path)."""
    result = await _create_run_core(
        request,
        body,
        db,
        circuit_breaker,
        worker_spawner,
        worker_client,
        commit_binding=None,
    )
    return RunStartResponse(
        run_id=result.thread_id,
        status=result.status,
        nickname=result.nickname,
        eligible=True,
        frozen_assignment=_modern_frozen_disclosure(result.frozen),
    )


async def _run_prepare(
    request: Request,
    body: RunStartRequest,
    worker_spawner: Any,
    worker_client: httpx.AsyncClient,
) -> RunPrepareResponse:
    """Reserve a bounded admission slot and report execution readiness.

    Loads the preset only to derive the bounded required-role set the later
    commit must cover, then reserves through the process-wide broker. The broker
    triggers the gateway-owned worker's single-flight startup and probes seated
    readiness before assigning capacity; no token is accepted and no durable run
    is created. A capacity-exhausted or role-invalid prepare is refused with a
    503 carrying the safe reason.
    """
    logger.info("commit step: workspace_root")
    ws_root = _prepare_workspace_root(body)
    team_config = _load_preset_or_refuse(body.team_preset, ws_root)
    frozen = await _validate_and_freeze_selection_or_refuse(
        request.app, body, team_config, ws_root
    )
    canonical_body = _body_with_frozen_selection(body, frozen)
    broker = admission_broker(request.app)
    outcome = await broker.prepare(
        required_roles=required_role_ids(team_config),
        ensure_worker=worker_spawner.ensure_worker,
        probe_readiness=lambda: _probe_admission_readiness(
            request.app.state, worker_client
        ),
        binding_digest=request_digest(canonical_body, prepared=True),
        release_digest=_release_binding_digest(body),
    )
    if (
        not outcome.admitted
        or outcome.reservation_id is None
        or outcome.lease_id is None
    ):
        # The refusal reason is deliberately one safe sentence, so it cannot say
        # WHICH of the three readiness legs failed. Those facts are already
        # probed and carried on the outcome, and already served on the
        # service-state surface, so logging them here discloses nothing new -
        # and without them a refusal is only diagnosable by re-deriving the
        # probe by hand, which is how three admission failures stayed open.
        refused = outcome.readiness
        logger.warning(
            "run admission refused: reason=%s worker_state=%s "
            "provider_eligibility=%s run_admission=%s eligible_providers=%s "
            "readiness_reasons=%s",
            outcome.reason,
            refused.worker_state.value,
            refused.provider_eligibility.value,
            refused.run_admission.value,
            ",".join(refused.eligible_providers) or "none",
            "; ".join(refused.reasons) or "none",
        )
        raise HTTPException(status_code=503, detail=outcome.reason)
    readiness = outcome.readiness
    return RunPrepareResponse(
        reservation_id=outcome.reservation_id,
        lease_id=outcome.lease_id,
        required_roles=list(outcome.required_roles),
        expires_at=outcome.expires_at or "",
        worker_state=readiness.worker_state,
        provider_eligibility=readiness.provider_eligibility,
        run_admission=readiness.run_admission,
        reasons=list(readiness.reasons),
    )


async def _run_commit(
    request: Request,
    body: RunStartRequest,
    db: AsyncSession,
    circuit_breaker: Any,
    worker_spawner: Any,
    worker_client: httpx.AsyncClient,
) -> RunCommitResponse:
    """Bind actor tokens to a stable run under a prepared reservation.

    Re-evaluates execution eligibility and handles an exact durable replay before
    moving the reservation into its recoverable ``committing`` state. A new
    commit must match the prepared request and role set before the shared creation
    core receives its tokens. The reservation is consumed only after the exact
    run binding is durable; a proven pre-durability failure restores it. The
    non-secret lease identity is returned and persisted for terminal settlement.
    """
    if body.reservation_id is None:  # pragma: no cover - guarded by the schema
        raise HTTPException(status_code=422, detail="commit requires a reservation id")
    run_id = body.run_id
    logger.info("commit entered: run_id=%s reservation=%s", run_id, body.reservation_id)
    async with commit_singleflight(request.app).hold(run_id):
        return await _run_commit_locked(
            request,
            body,
            db,
            circuit_breaker,
            worker_spawner,
            worker_client,
        )


async def _run_commit_locked(
    request: Request,
    body: RunStartRequest,
    db: AsyncSession,
    circuit_breaker: Any,
    worker_spawner: Any,
    worker_client: httpx.AsyncClient,
) -> RunCommitResponse:
    """Linearized commit implementation; caller holds its per-run stripe."""
    reservation_id = body.reservation_id
    if reservation_id is None:  # pragma: no cover - guarded by the schema
        raise HTTPException(status_code=422, detail="commit requires a reservation id")
    run_id = body.run_id
    broker = admission_broker(request.app)

    # A commit acknowledgement can be lost after the durable run is created.
    # Recover that exact replay before consulting the now-consumed reservation,
    # returning the persisted non-secret gateway lease identity.
    existing = await get_thread(db, run_id)
    if existing is not None:
        canonical_body = _canonical_replay_body(existing.thread_metadata, body)
        commit_digest = request_digest(canonical_body, prepared=False)
        existing_modern = _read_persisted_team_selection(existing.thread_metadata)
        binding = _persisted_lease_binding(existing.thread_metadata)
        if binding is None:
            raise HTTPException(
                status_code=409,
                detail="existing run was not committed under a prepared lease",
            )
        if binding.reservation_id != reservation_id or not hmac.compare_digest(
            binding.commit_digest, commit_digest
        ):
            raise HTTPException(
                status_code=409,
                detail="commit replay does not exactly match the accepted request",
            )
        # Repair any in-memory ACTIVE/COMMITTING reservation left by a failure
        # after the exact durable row was written but before the response path
        # completed. A process restart simply has no in-memory row, so false is
        # benign here.
        await broker.complete_commit(reservation_id, binding.lease_id)
        return RunCommitResponse(
            run_id=existing.id,
            status=existing.status,
            lease_id=binding.lease_id,
            nickname=existing.nickname,
            frozen_assignment=_modern_frozen_disclosure(existing_modern),
        )
    ws_root = _prepare_workspace_root(body)
    team_config = _load_preset_or_refuse(body.team_preset, ws_root)
    frozen = await _validate_and_freeze_selection_or_refuse(
        request.app, body, team_config, ws_root
    )
    canonical_body = _body_with_frozen_selection(body, frozen)
    commit_digest = request_digest(canonical_body, prepared=False)
    # Evaluate worker and provider eligibility BEFORE consuming the reservation,
    # accepting the actor tokens, or creating a run (ADR: mint run credentials only
    # after the runtime and provider are eligible). The worker reachability is
    # probed live so the verdict never lags behind the watchdog's status ladder; a
    # refusal releases the reservation so a failed commit leaks nothing.
    from ...control.worker_management import probe_worker_health

    logger.info("commit step: probe_worker")
    probe = await probe_worker_health(settings.worker_url, client=worker_client)
    # Same tri-state as prepare: only a probe that OBSERVED absence may report it.
    # An indeterminate one defers to the watchdog's seated state, so a worker busy
    # with an in-flight run stays execution-ready for the next commit.
    readiness = _admission_readiness(
        request.app.state,
        worker_probe_ready=None if probe.indeterminate else probe.healthy,
    )
    worker_reachable = readiness.worker_state is WorkerLifecycleState.READY
    execution = evaluate_execution_eligibility(
        worker_reachable=worker_reachable,
        provider_eligibility=readiness.provider_eligibility,
    )
    if not execution.eligible:
        # Same disclosure the prepare refusal carries: a commit 503 otherwise
        # says only that something was ineligible, which cannot be told apart
        # from a refusal about the reservation itself.
        logger.warning(
            "run commit refused as ineligible: reason=%s worker_state=%s "
            "worker_probe=%s provider_eligibility=%s reservation=%s",
            execution.reason,
            readiness.worker_state.value,
            "indeterminate"
            if probe.indeterminate
            else ("healthy" if probe.healthy else "absent"),
            readiness.provider_eligibility.value,
            reservation_id,
        )
        await _release_ineligible_reservation(broker, reservation_id, canonical_body)
        raise HTTPException(status_code=503, detail=execution.reason)

    presented_roles: set[str] = (
        set(body.actor_tokens.tokens.keys()) if body.actor_tokens is not None else set()
    )
    outcome = await broker.commit(
        reservation_id,
        binding_digest=request_digest(canonical_body, prepared=True),
        presented_roles=presented_roles,
    )
    logger.info(
        "commit broker verdict: reservation=%s committed=%s reason=%s",
        reservation_id,
        outcome.committed,
        outcome.reason or "none",
    )
    if not outcome.committed or outcome.lease_id is None:
        raise HTTPException(status_code=409, detail=outcome.reason)
    binding = _RunLeaseBinding(
        lease_id=outcome.lease_id,
        reservation_id=reservation_id,
        commit_digest=commit_digest,
    )
    try:
        result = await _create_run_core(
            request,
            body,
            db,
            circuit_breaker,
            worker_spawner,
            worker_client,
            commit_binding=binding,
        )
    except BaseException:
        # Dispatch can fail after `_create_run_core` has committed the exact run
        # row. Never reopen that reservation: a replay will recover the durable
        # binding. Roll back the request session first because a pre-durability
        # conflict can leave SQLAlchemy's transaction unusable for the
        # authoritative read. Abort only when the run is authoritatively absent;
        # on a rollback/read error or conflicting durable row, retain COMMITTING
        # rather than create duplicate admission authority.
        try:
            await db.rollback()
            persisted = await get_thread(db, run_id)
        except Exception:
            logger.exception(
                "Could not classify failed commit durability for run %s reservation %s",
                run_id,
                reservation_id,
            )
        else:
            persisted_binding = (
                _persisted_lease_binding(persisted.thread_metadata)
                if persisted is not None
                else None
            )
            if (
                persisted_binding is not None
                and persisted_binding.lease_id == outcome.lease_id
                and persisted_binding.reservation_id == reservation_id
                and hmac.compare_digest(persisted_binding.commit_digest, commit_digest)
            ):
                await broker.complete_commit(reservation_id, outcome.lease_id)
            elif persisted is None:
                if not await broker.abort_commit(reservation_id, outcome.lease_id):
                    logger.error(
                        "Could not restore failed commit reservation %s for run %s",
                        reservation_id,
                        run_id,
                    )
            else:
                logger.error(
                    "Failed commit for run %s found a conflicting durable binding; "
                    "reservation %s remains committing until expiry",
                    run_id,
                    reservation_id,
                )
        raise
    if not await broker.complete_commit(reservation_id, outcome.lease_id):
        logger.error(
            "Durable run %s lost its in-memory committing reservation %s",
            result.thread_id,
            reservation_id,
        )
    return RunCommitResponse(
        run_id=result.thread_id,
        status=result.status,
        lease_id=outcome.lease_id,
        nickname=result.nickname,
        frozen_assignment=_modern_frozen_disclosure(result.frozen),
    )


async def _run_release(request: Request, body: RunStartRequest) -> RunReleaseResponse:
    """Explicitly free a prepared slot after a dashboard-side failure."""
    reservation_id = body.reservation_id
    if reservation_id is None:  # pragma: no cover - guarded by the schema
        raise HTTPException(status_code=422, detail="release requires a reservation id")
    run_id = body.run_id
    async with commit_singleflight(request.app).hold(run_id):
        released = await admission_broker(request.app).release(
            reservation_id,
            binding_digest=_release_binding_digest(body),
        )
    return RunReleaseResponse(reservation_id=reservation_id, released=released)


def _prepare_workspace_root(body: RunStartRequest) -> Path | None:
    """Resolve the preset-loading workspace for a prepare, or ``None``.

    A prepare carries no run id, so it never mints a workspace; it only needs a
    workspace context to resolve a workspace-local preset. When the request
    metadata names an absolute workspace root it is used, otherwise the bundled
    preset set is resolved (``None``).
    """
    metadata = body.metadata
    workspace_root = getattr(metadata, "workspace_root", None) if metadata else None
    if not workspace_root:
        return None
    candidate = Path(workspace_root)
    return candidate if candidate.is_absolute() else None


def _release_binding_digest(body: RunStartRequest) -> str:
    """Bind release to the raw prepared request, not canonical commit policy."""
    return request_digest(body, prepared=True)


async def _release_ineligible_reservation(
    broker: AdmissionBroker, reservation_id: str, canonical_body: RunStartRequest
) -> bool:
    """Release a refused commit under its canonical prepared identity."""
    return await broker.release_failed_commit(
        reservation_id,
        binding_digest=request_digest(canonical_body, prepared=True),
    )


def _selection_reference(value: ProviderCatalogSelection) -> SelectionReference:
    """Convert the bounded wire map into the canonical provider-domain type."""
    return SelectionReference(
        schema_version=value.schema_version,
        provider_id=value.provider_id,
        execution_mode=value.execution_mode,
        catalog_revision=value.catalog_revision,
        entry_id=value.entry_id,
        controls=tuple(
            ControlSelection(control_id=control_id, option_id=option_id)
            for control_id, option_id in sorted(value.controls.items())
        ),
    )


def _wire_reference(reference: SelectionReference) -> ProviderCatalogSelection:
    """Render a normalized domain reference into the canonical request wire."""
    return ProviderCatalogSelection(
        schema_version=1,
        provider_id=reference.provider_id,
        execution_mode=reference.execution_mode,
        catalog_revision=reference.catalog_revision,
        entry_id=reference.entry_id,
        controls={item.control_id: item.option_id for item in reference.controls},
    )


def _wire_selection(value: Any) -> ProviderCatalogSelection:
    """Render a normalized frozen lane back into the canonical request wire."""
    return _wire_reference(value.reference)


def _body_with_frozen_selection(
    body: RunStartRequest, frozen: FrozenTeamSelection
) -> RunStartRequest:
    """Return the request with authoritative catalog defaults made explicit."""
    return body.model_copy(
        update={
            "selection": _wire_selection(frozen.selection),
            "overrides": {
                role: _wire_selection(value) for role, value in frozen.overrides.items()
            },
            "fallbacks": [_wire_selection(value) for value in frozen.fallbacks],
        }
    )


def _canonical_replay_body(
    metadata_json: str | None, body: RunStartRequest
) -> RunStartRequest:
    """Canonicalize a replay from persisted defaults, without live discovery."""
    metadata = _metadata_object(metadata_json)
    record = metadata.get(_TEAM_SELECTION_METADATA_KEY) if metadata else None
    if record is None:
        return body
    try:
        selection, overrides, fallbacks = normalize_replay_selection(
            record=record,
            selection=_selection_reference(body.selection),
            overrides={
                role: _selection_reference(reference)
                for role, reference in body.overrides.items()
            },
            fallbacks=tuple(_selection_reference(item) for item in body.fallbacks),
        )
    except (TeamSelectionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return body.model_copy(
        update={
            "selection": _wire_reference(selection),
            "overrides": {
                role: _wire_reference(reference)
                for role, reference in overrides.items()
            },
            "fallbacks": [_wire_reference(reference) for reference in fallbacks],
        }
    )


async def _catalog_records_within_budget(
    app: FastAPI, canonical: str
) -> tuple[ProviderRecord, ...]:
    """Read *canonical*'s catalog records under a bounded wall-clock budget.

    A WARM catalog answers from the per-lane cache immediately, which is the
    normal case: a client cannot produce a valid selection without having read
    the catalog first. The cold case is real anyway - a gateway restart, or the
    workspace scope evicted under capacity, between that read and this start -
    and building cold probes every registered lane over subprocesses and the
    network. A run start absorbing that is indistinguishable to the caller from
    a hung gateway.

    The build is SHIELDED rather than cancelled on expiry. Cancelling it would
    make every retry pay the same cold cost and never converge; letting it finish
    populates the per-lane single-flight cache, so the caller's retry is warm.
    The refusal is therefore a genuine "not yet", not a failure.
    """
    service = provider_catalog_service(app)
    build = asyncio.ensure_future(service.records(canonical))
    try:
        return await asyncio.wait_for(
            asyncio.shield(build), domain_config.run_start_catalog_budget_seconds
        )
    except TimeoutError:
        # The shielded build outlives this request. Consume its outcome so a
        # later failure is neither an unretrieved-exception warning nor silent.
        build.add_done_callback(_log_detached_catalog_build)
        logger.warning(
            "run refused: provider catalog for workspace=%s did not build within "
            "%.1fs; the build continues and a retry will be served warm",
            canonical,
            domain_config.run_start_catalog_budget_seconds,
        )
        raise HTTPException(
            status_code=503,
            detail="the provider catalog for this workspace is still being built",
        ) from None


def _log_detached_catalog_build(task: asyncio.Future[Any]) -> None:
    """Record how a catalog build that outlived its request finished."""
    if task.cancelled():
        logger.warning("detached provider catalog build was cancelled")
        return
    error = task.exception()
    if error is not None:
        logger.warning(
            "detached provider catalog build failed: %s", type(error).__name__
        )


async def _validate_and_freeze_selection_or_refuse(
    app: FastAPI,
    body: RunStartRequest,
    team_config: Any,
    workspace_root: Path | None,
) -> FrozenTeamSelection:
    """Revalidate the complete new-run selection in its canonical workspace."""
    if workspace_root is None:
        raise HTTPException(
            status_code=422,
            detail="explicit provider selection requires an existing workspace_root",
        )
    canonical = normalize_workspace_identity(str(workspace_root))
    if len(canonical) > 4096 or not Path(canonical).is_dir():
        raise HTTPException(
            status_code=422,
            detail="workspace_root must identify an existing directory",
        )
    try:
        records = await _catalog_records_within_budget(app, canonical)
    except ProviderCatalogScopeCapacityError:
        # Disclosed for the same reason the admission refusals are: a bare 503
        # here is indistinguishable from an admission or eligibility refusal,
        # and this one is about the catalog's bounded workspace scopes rather
        # than about the run at all.
        logger.warning(
            "run refused: provider catalog workspace scope capacity exhausted "
            "for workspace=%s",
            canonical,
        )
        raise HTTPException(
            status_code=503,
            detail="provider catalog workspace capacity is temporarily busy",
        ) from None
    try:
        return freeze_team_selection(
            selection=_selection_reference(body.selection),
            overrides={
                role: _selection_reference(reference)
                for role, reference in body.overrides.items()
            },
            fallbacks=tuple(_selection_reference(item) for item in body.fallbacks),
            required_roles=tuple(required_role_ids(team_config)),
            records=records,
        )
    except (TeamSelectionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# The metadata key binding a run to its non-secret admission lease identity. The
# gateway writes it at commit and the terminal handler reads it back; both restate
# this key inline, matching the metadata convention used for the frozen profile.
_RUN_LEASE_METADATA_KEY = "run_lease"

# The canonical digest of the request that created a run. Persisted on every
# create so a later replay can be compared against what the run was actually
# started with, rather than against the single field the check previously read.
# The stored value is the rule-stamped form (``<rule>:<digest>``); an unstamped
# value is a run created before the marker existed and is compared under the
# rule it was written with.
_REQUEST_DIGEST_METADATA_KEY = "run_request_digest"


def _persist_request_digest(metadata_json: str | None, digest: str) -> str:
    """Embed the creating request's rule-stamped digest into run metadata."""
    data = _metadata_object(metadata_json) or {}
    data[_REQUEST_DIGEST_METADATA_KEY] = digest
    return json.dumps(data)


def _persisted_request_digest(metadata_json: str | None) -> str | None:
    """Read the creating request's digest, or ``None`` for a pre-existing run.

    ``None`` means the digest is UNKNOWN, never that the request was empty, so
    the caller falls back to the narrower comparison instead of refusing a
    legitimate replay. Two runs reach that state, and both are expected: a run
    created before digests were persisted, and a run whose id this service
    minted, since the digest is stored only for a caller-supplied id.

    The second case has a consequence worth naming. A caller can read a
    server-minted id off the response and later present it as its own, and that
    request is then compared on the frozen profile alone rather than on the whole
    body. Closing it is not merely a matter of persisting the digest anyway: the
    run id is itself a digested field, so the original request - which carried
    none - and the later one that carries it would never match, and every such
    replay would be refused instead. Narrowing here is the deliberate trade.
    """
    data = _metadata_object(metadata_json)
    digest = data.get(_REQUEST_DIGEST_METADATA_KEY) if data is not None else None
    return digest if isinstance(digest, str) and digest else None


def _replay_identity_or_conflict(
    run_id: str, metadata_json: str | None, body: RunStartRequest
) -> None:
    """Refuse a same-run-id request that is not a replay of the durable run.

    The single encoding of run-start replay identity, applied wherever a request
    meets a run that already owns its id: the sequential check-then-act retry,
    and the loser of a simultaneous insert race. Both arrive at the same
    question - is this the same intention wearing the same id, or a different
    one? - and a second encoding of the answer would be free to drift from the
    first.

    Every behaviour-affecting field - the prompt, the preset, the feature tag,
    the feedback batch, and the canonicalized catalog selection - is folded into
    the persisted replay fingerprint, so a differing request is refused rather
    than silently answered with the durable run and its distinct intention
    discarded.

    Credential VALUES are deliberately not part of that fingerprint. A replay
    returns the ORIGINAL run and never adopts the retry's bundle, and
    short-lived credentials are expected to rotate across a retry, so refusing a
    rotated bundle here would refuse exactly the lost-acknowledgement recovery
    this path exists to serve. Credential coverage remains enforced at first
    start by admission, which is where an uncovering bundle is refused. The
    stored fingerprint is compared under the rule it was written with, so a run
    created before that classification still replays.

    Raises:
        HTTPException: 409 when the request fingerprint differs.
    """
    # ``None`` means the digest is unknown - an older run, or one whose id this
    # service minted - not that the request was empty; refusing on it would
    # break a legitimate replay. Such a request passes the identity check
    # unfingerprinted, which is narrower rather than absent.
    persisted_digest = _persisted_request_digest(metadata_json)
    canonical_body = _canonical_replay_body(metadata_json, body)
    if persisted_digest is not None and not replay_digest_matches(
        persisted_digest, canonical_body
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run {run_id!r} was already started with a different request "
                "body; a replay must carry the same request to return the "
                "original run"
            ),
        )


def _persist_lease(metadata_json: str | None, binding: _RunLeaseBinding) -> str:
    """Embed the non-secret lease and exact replay binding into run metadata."""
    data = _metadata_object(metadata_json) or {}
    data[_RUN_LEASE_METADATA_KEY] = {
        "lease_id": binding.lease_id,
        "reservation_id": binding.reservation_id,
        "commit_digest": binding.commit_digest,
    }
    return json.dumps(data)


def _persisted_lease_id(metadata_json: str | None) -> str | None:
    """Read current or legacy non-secret lease metadata from a durable run."""
    binding = _persisted_lease_binding(metadata_json)
    if binding is not None:
        return binding.lease_id
    data = _metadata_object(metadata_json)
    lease = data.get(_RUN_LEASE_METADATA_KEY) if data is not None else None
    try:
        lease_object = _JSON_OBJECT.validate_python(lease)
    except ValidationError:
        return None
    lease_id = lease_object.get("lease_id")
    if (
        not isinstance(lease_id, str)
        or not 1 <= len(lease_id) <= 128
        or not lease_id[0].isalnum()
        or not all(
            character.isascii() and (character.isalnum() or character in {"_", "-"})
            for character in lease_id
        )
    ):
        return None
    return lease_id


def _persisted_lease_binding(metadata_json: str | None) -> _RunLeaseBinding | None:
    """Read the exact staged-commit replay binding from durable metadata."""
    data = _metadata_object(metadata_json)
    if data is None:
        return None
    try:
        lease = _JSON_OBJECT.validate_python(data.get(_RUN_LEASE_METADATA_KEY))
    except ValidationError:
        return None
    lease_id = lease.get("lease_id")
    reservation_id = lease.get("reservation_id")
    commit_digest = lease.get("commit_digest")
    if (
        not isinstance(lease_id, str)
        or not lease_id
        or not isinstance(reservation_id, str)
        or not reservation_id
        or not isinstance(commit_digest, str)
        or not commit_digest
    ):
        return None
    return _RunLeaseBinding(
        lease_id=lease_id,
        reservation_id=reservation_id,
        commit_digest=commit_digest,
    )


def _load_preset_or_refuse(team_preset: str, ws_root: Path | None) -> Any:
    """Load the preset with the run's workspace context or refuse with a 422.

    The v1 verb never silently drafts a run for a missing or unparseable preset:
    a load or validation failure is a client error, returned as a 422 with a safe
    reason rather than a non-running draft.
    """
    from pydantic import ValidationError

    from ...team.team_config import load_team_config
    from ...thread.errors import ConfigError, TeamConfigNotFoundError

    try:
        return load_team_config(team_preset, workspace_root=ws_root)
    except TeamConfigNotFoundError as exc:
        raise HTTPException(
            status_code=422, detail=f"Unknown team preset: {team_preset!r}"
        ) from exc
    except (ConfigError, ValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Team preset {team_preset!r} failed to load: {exc}",
        ) from exc


def _probe_harness(team_config: Any, ws_root: Path | None) -> Any:
    """Probe the agent harness for a document-authoring preset, else ``None``.

    A non-authoring preset carries no harness requirement, so it returns ``None``
    (composes nothing into eligibility; pre-existing refusals unchanged). A
    document-authoring preset ALWAYS yields a verdict: the verifier's over a
    resolved workspace, or a synthetic not-ready verdict when no workspace is
    resolved - a workspaceless authoring run cannot possibly carry a complete
    harness, so it is refused, not silently skipped (operator override possible,
    silent degradation never). This preserves the
    discovery-serves / run-start-refuses binding uniformly. Read-only.
    """
    from ...context.harness import HarnessReadiness
    from ...providers.model_profiles import probe_harness_ready

    harness_decl = team_config.effective_harness()
    if harness_decl is None:
        return None
    if ws_root is None:
        return HarnessReadiness(
            ready=False,
            reasons=["no workspace resolved for a document-authoring preset"],
        )
    return probe_harness_ready(
        ws_root, required_skills=harness_decl.all_required_skills()
    )


_TEAM_SELECTION_METADATA_KEY = "provider_catalog_selection"


def _persist_team_selection(
    metadata_json: str | None, frozen: FrozenTeamSelection
) -> str:
    """Persist the normalized schema-v1 selection without a legacy profile id."""
    data = _metadata_object(metadata_json) or {}
    data[_TEAM_SELECTION_METADATA_KEY] = frozen.to_record()
    return json.dumps(data)


def _read_persisted_frozen(metadata_json: str | None) -> Any:
    """Rebuild the persisted :class:`FrozenAssignment` from thread metadata, or None."""
    from ...providers.model_profiles import frozen_from_record

    data = _metadata_object(metadata_json)
    if data is None:
        return None
    return frozen_from_record(data.get("model_profile"))


def _read_persisted_team_selection(
    metadata_json: str | None,
) -> FrozenTeamSelection | None:
    """Rebuild the modern frozen execution authority without live discovery."""
    from ...providers.team_selection import frozen_team_selection_from_record

    data = _metadata_object(metadata_json)
    if data is None or _TEAM_SELECTION_METADATA_KEY not in data:
        return None
    return frozen_team_selection_from_record(data[_TEAM_SELECTION_METADATA_KEY])


def _modern_frozen_disclosure(
    frozen: Any,
) -> FrozenTeamAssignmentSummary | None:
    """Project only validated modern selections onto the public frozen shape."""
    if not isinstance(frozen, FrozenTeamSelection):
        return None
    return FrozenTeamAssignmentSummary.model_validate(frozen.disclosure())


def _frozen_disclosure(frozen: Any) -> list[RoleAssignmentSummary]:
    """Build the safe per-role disclosure from a frozen assignment record.

    Every field but one is reproduced verbatim from the frozen record - what the
    run DECIDED at start, deliberately immune to later config drift.
    ``provider_ready`` is the exception: readiness is a live host fact that no
    frozen record carries (``freeze_assignment`` does not persist it, and could
    not without making the run's digest depend on the host). It is therefore
    probed here, through the same production probe the preset listing uses, so
    the two disclosures of one question cannot disagree. Leaving it to the
    model's default instead published a confident ``False`` - asserting "not
    ready" where the truth was "not evaluated".

    The probe is memoized per call, so a run pays it once per distinct provider
    rather than once per role. Callers are on the event loop and must offload
    this (``asyncio.to_thread``), matching the preset listing: the probe reaches
    the filesystem to resolve a subprocess provider's launch command.
    """
    from ...graph.enums import Provider
    from ...providers.model_profiles import probe_provider_readiness

    readiness: dict[str, bool] = {}

    def _ready(provider_id: str) -> bool:
        if provider_id not in readiness:
            try:
                provider = Provider(provider_id)
            except ValueError:
                # A run frozen under a provider this build no longer knows: the
                # truthful verdict is "not ready", not a crash on a read path.
                readiness[provider_id] = False
            else:
                readiness[provider_id] = probe_provider_readiness(provider).ready
        return readiness[provider_id]

    summaries: list[RoleAssignmentSummary] = []
    for agent_id, role in frozen.roles.items():
        provider_id = str(role.get("provider", ""))
        summaries.append(
            RoleAssignmentSummary(
                role_id=str(role.get("role_id", "")),
                agent_id=agent_id,
                provider_id=provider_id,
                capability=role.get("capability"),
                model_name=role.get("model_name") or None,
                fallback_providers=list(role.get("fallback", [])),
                provider_ready=_ready(provider_id),
                source=str(role.get("source", "team_default")),
            )
        )
    return summaries


async def _disclose_frozen(frozen: Any) -> list[RoleAssignmentSummary]:
    """Disclose a frozen assignment (or nothing) without blocking the event loop.

    The single entry point every run-envelope path uses, so the absent-frozen
    case and the readiness offload are decided once rather than at four call
    sites. The offload matches ``presets_list_endpoint``: readiness reaches the
    filesystem, and ``/v1/runs/{run_id}`` is polled.
    """
    if frozen is None or isinstance(frozen, FrozenTeamSelection):
        return []
    return await asyncio.to_thread(_frozen_disclosure, frozen)


def _raise_for_dispatch_failure(
    failure_type: FailureType | None, detail: str | None
) -> None:
    """Map a dispatch failure to the same HTTP status the internal route uses."""
    if failure_type is None:
        return
    if failure_type == FailureType.CIRCUIT_OPEN:
        raise HTTPException(status_code=503, detail=detail or "Circuit breaker open")
    if failure_type == FailureType.AT_CAPACITY:
        raise HTTPException(status_code=503, detail="Worker at capacity — try again")
    if failure_type == FailureType.UNREACHABLE:
        raise HTTPException(status_code=502, detail="Worker unreachable")
    if failure_type == FailureType.REJECTED:
        raise HTTPException(
            status_code=502, detail=detail or "Worker dispatch rejected"
        )


# ---------------------------------------------------------------------------
# active-run discovery
# ---------------------------------------------------------------------------


@router.get(
    "/runs",
    # Serialization is left to the two explicit returns below: a single response
    # model - even a union one - would re-serialize the discovery reading through
    # a shape it does not own, and that response is certified byte for byte. The
    # ``responses`` entry restores what turning the model off would otherwise
    # cost: the documented 200 schema a generated client reads.
    response_model=None,
    responses={
        200: {
            "model": ActiveRunsResponse | RunSummariesResponse,
            "description": (
                "The discovery reading for ``state=active`` and the wider "
                "history reading for ``state=all``."
            ),
        }
    },
)
async def active_runs_endpoint(
    request: Request,
    state: Literal["active", "all"] = Query(default="active"),
    workspace_root: str | None = Query(default=None, min_length=1, max_length=4096),
    feature_tag: str | None = Query(default=None, min_length=1, max_length=128),
    status: ThreadStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ActiveRunsResponse | RunSummariesResponse:
    """List runs: non-terminal by default, or every run including terminal ones.

    The default is unchanged and remains the capped identity projection of
    durable non-terminal runs that the engine contract certified - a caller that
    passes nothing sees exactly what it saw before, byte for byte.

    ``state=all`` is the history read, and it differs from discovery in more than
    which rows it returns. It answers through the paginated list service rather
    than the discovery one, because discovery exists to find live work and is
    capped for that purpose while history has to walk a store that only grows;
    that is why this mode carries a total and an offset. And it answers with a
    WIDER record, because the two readings are asked different questions: a
    viewer binding to live work needs an identity, while a reader of history is
    asking what happened and needs the projection that separates a healthy run
    from a degraded one.

    The two shapes are returned as two models rather than one union, so widening
    history cannot perturb a single byte of the certified discovery response.
    """
    workspace = Path(workspace_root) if workspace_root is not None else None
    if workspace is not None and not workspace.is_absolute():
        raise HTTPException(status_code=422, detail="workspace_root must be absolute")

    if state == "all":
        listing = await list_threads_service(
            db,
            status_filter=status,
            limit=limit,
            offset=offset,
            checkpointer=request.app.state.checkpointer,
        )
        return RunSummariesResponse(
            runs=[
                RunSummaryRecord(
                    run_id=thread.thread_id,
                    status=ThreadStatus(thread.status),
                    feature_tag=thread.feature_tag,
                    title=thread.title,
                    nickname=thread.nickname,
                    team_preset=thread.team_preset,
                    repair_status=thread.repair_status,
                    execution_readiness=thread.execution_readiness,
                    approval_status=thread.approval_status,
                    approval_request_id=thread.approval_request_id,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                    source_branch=thread.source_branch,
                    callee=thread.callee,
                )
                for thread in listing.threads
            ],
            truncated=(offset + len(listing.threads)) < listing.total,
            total=listing.total,
        )

    result = await discover_active_runs(
        db,
        workspace_root=workspace,
        feature_tag=feature_tag,
        limit=limit,
    )
    return ActiveRunsResponse(
        state=state,
        runs=[
            ActiveRunRecord(
                run_id=run.run_id,
                status=run.status,
                feature_tag=run.feature_tag,
            )
            for run in result.runs
        ],
        truncated=result.truncated,
    )


# ---------------------------------------------------------------------------
# run-status
# ---------------------------------------------------------------------------


def _active_role(next_nodes: list[str], agents: list[Any]) -> str | None:
    """Active position in product ROLE vocabulary, never a node name.

    Maps the checkpoint's active node to the role of the matching agent (its
    node is named by its agent id, minus the ``mount_`` prefix). Internal
    orchestration and gate nodes have no matching agent, so they surface as
    ``None`` rather than leaking an internal LangGraph node name into the product
    status contract; per-role ``state`` and ``pause_cause`` carry the rest.
    """
    role_by_id = {agent.agent_id: agent.role for agent in agents}
    for node in next_nodes:
        if not node or node == "__end__":
            continue
        role = role_by_id.get(node.removeprefix("mount_"))
        if role:
            return role
    return None


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def run_status_endpoint(
    run_id: PathSafeRunId,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> RunStatusResponse:
    """Return the authoritative recovery snapshot for a run."""
    capture = await capture_thread_state(
        db, thread_id=run_id, aggregator=aggregator, checkpointer=checkpointer
    )
    if capture is None:
        raise HTTPException(status_code=404, detail="Run not found")

    snapshot = capture.snapshot
    proposal_ids, changeset_ids = derive_run_authoring_ids(capture.checkpoint_tuple)
    semantic = derive_run_semantic_context(capture.checkpoint_tuple)
    semantic_phase = project_semantic_phase(
        status=snapshot.status,
        next_nodes=snapshot.next_nodes,
        repair_status=snapshot.repair_status,
    )
    # model-profiles: disclose the run's frozen profile + effective assignment,
    # reproduced verbatim from run metadata (never re-resolved).
    frozen = _read_persisted_frozen(capture.thread_metadata)
    modern_frozen = _read_persisted_team_selection(capture.thread_metadata)

    return RunStatusResponse(
        run_id=snapshot.thread_id,
        status=ThreadStatus(snapshot.status),
        semantic_phase=semantic_phase,
        feature_tag=semantic.feature_tag,
        authoring_session_id=semantic.authoring_session_id,
        topology=TopologyPosition(
            team_preset=capture.team_preset,
            active_agent=_active_role(snapshot.next_nodes, snapshot.agents),
            pause_cause=snapshot.pause_cause,
        ),
        roles=[
            RoleState(
                agent_id=agent.agent_id,
                role=agent.role,
                state=agent.state,
                display_name=agent.display_name,
            )
            for agent in snapshot.agents
        ],
        proposal_ids=proposal_ids,
        changeset_ids=changeset_ids,
        approval_status=snapshot.approval_status,
        approval_request_id=snapshot.approval_request_id,
        checkpoint_id=snapshot.checkpoint_id,
        last_sequence=snapshot.last_sequence,
        repair_status=snapshot.repair_status,
        execution_readiness=snapshot.execution_readiness,
        degraded_reasons=snapshot.degraded_reasons,
        failure_reason=snapshot.failure_reason,
        # Named explicitly beside the reason because this response is built with
        # keyword arguments rather than validated from the snapshot: nothing here
        # is dropped silently, but nothing arrives without being written either,
        # which is how the reason itself was missed when it was first persisted.
        provider_condition=snapshot.provider_condition,
        # The account of an operation that did not take on a run that is still
        # alive. Its writers decline to set the failure reason precisely because
        # the run survives, so without this line their account is durable and
        # unreadable - recorded for nobody.
        repair_reason=snapshot.repair_reason,
        profile_id=frozen.profile_id if frozen is not None else None,
        assignments=await _disclose_frozen(frozen),
        frozen_assignment=_modern_frozen_disclosure(modern_frozen),
        lease_id=_persisted_lease_id(capture.thread_metadata),
        reservation_id=(
            binding.reservation_id
            if (binding := _persisted_lease_binding(capture.thread_metadata))
            is not None
            else None
        ),
        # Read from the SAME capture tuple as every other field above, so
        # a questionnaire cannot be reported against a position the run has since
        # left. This is the authoritative disclosure a reloaded client recovers
        # from; the progress relay only ever nudges it to look here.
        pending_clarification=pending_clarification(
            capture.checkpoint_tuple, thread_id=run_id
        ),
    )


# ---------------------------------------------------------------------------
# run-stream
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/stream")
async def run_stream_endpoint(
    run_id: PathSafeRunId,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
) -> StreamingResponse:
    """Re-serve the run's bounded, versioned v1 SSE progress frames.

    The public streaming companion to run-status: run-status is the authoritative
    recovery snapshot, this is the droppable live progress relay. A run id is the
    thread id, so this delegates to the same stream builder the internal
    progress stream has always used - one code path, the same versioned
    256 KiB-bounded frames, the same terminal-replay-then-close semantics. Frames
    are non-authoritative by contract: a consumer reconciles run state from
    run-status, never from a relay frame.
    """
    return await build_thread_stream_response(
        db=db,
        aggregator=aggregator,
        thread_id=run_id,
        not_found_detail="Run not found",
    )


# ---------------------------------------------------------------------------
# run-cancel
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/cancel", response_model=RunCancelResponse)
async def run_cancel_endpoint(
    run_id: PathSafeRunId,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunCancelResponse:
    """Cancel a run idempotently."""
    result = await cancel_thread(
        db=db,
        thread_id=run_id,
        idempotency_key=idempotency_key,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )

    raise_for_cancel_failure(result, resource_noun="Run")

    if result.cancelled:
        mark_worker_connected(request)

    # Cancellation is the drain's tool and is never itself admission-gated. When
    # a cancel settles the run terminally here (e.g. a submitted-but-undispatched
    # run), release it from the admission gate so a concurrent drain can quiesce;
    # a run that only reaches CANCELLING is deliberately left for the worker's
    # terminal event, which releases it in
    # ``control.event_handlers._handle_terminal_event``. Both sites can fire for
    # one run - the gate's release is an idempotent discard, so they cannot
    # corrupt the active set.
    if result.thread_status in TERMINAL_STATUSES:
        await admission_gate(request.app).release(result.thread_id)

    return RunCancelResponse(
        run_id=result.thread_id,
        status=result.thread_status,
        cancelled=result.cancelled,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        idempotency_key=result.idempotency_key,
    )


# ---------------------------------------------------------------------------
# run-history
# ---------------------------------------------------------------------------


# The transcript verdicts that mean a run's record was LOST rather than never
# written. Absence on a run that has not been dispatched is normal and excluded.
_TRANSCRIPT_FAULTS: frozenset[TranscriptAvailability] = frozenset(
    {TranscriptAvailability.MISSING, TranscriptAvailability.UNREADABLE}
)


def snapshot_to_wire(data: Any) -> ThreadStateSnapshot:
    """Project the domain run-state snapshot onto its wire model.

    Named rather than inlined so the conversion has a single production seam a
    parity test can drive directly. A field added to the domain snapshot but
    absent from the wire model is dropped silently here, which is exactly the
    kind of loss a test that re-derives the conversion cannot catch.
    """
    return ThreadStateSnapshot.model_validate(asdict(data))


@router.get("/runs/{run_id}/history", response_model=RunHistoryResponse)
async def run_history_endpoint(
    run_id: PathSafeRunId,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> RunHistoryResponse:
    """Read one run whole, including a terminal or archived one.

    Distinct from run-status by design. Run-status is the BOUNDED recovery
    snapshot an engine reconciles authority from, and widening it would have
    made every reconciliation pay for a transcript it does not read. This is the
    wide read for a consumer that wants the record: transcript, agents, plan,
    pending answers, and the run's metadata.

    "Whole" is a promise about honesty, not about always having everything. The
    transcript lives only in the checkpoint, and a checkpoint can be gone or
    unreachable; when it is, this answers 200 with the durable half of the
    record it CAN read - status, agents, plan, permissions, metadata - and says
    plainly that the transcript is not part of it. Refusing the whole read over
    an absent transcript would cost the caller the half that survived, and
    answering an unqualified empty message list would be worse still: silent
    loss dressed as a run that never spoke.

    The state snapshot is embedded rather than restated, so this response cannot
    drift from the snapshot it reports.
    """
    capture = await capture_thread_state(
        db,
        thread_id=run_id,
        aggregator=aggregator,
        checkpointer=checkpointer,
    )
    if capture is None:
        raise HTTPException(status_code=404, detail="Run not found")
    snapshot = capture.snapshot

    # A run past dispatch owes a transcript. Reporting the absence on the wire
    # serves the caller; logging it serves the operator, who otherwise learns of
    # the loss only if someone happens to read this run and happens to look. A
    # not-yet-dispatched run owes nothing yet and is deliberately not logged.
    if capture.transcript in _TRANSCRIPT_FAULTS:
        logger.warning(
            "run history: run %s (status %s) has no readable transcript (%s); "
            "reporting the record without it",
            run_id,
            snapshot.status,
            capture.transcript.value,
        )

    # Absent metadata is stored as null OR as an empty string depending on how
    # the run was created, and an empty string is not parseable JSON - so the
    # guard is truthiness, not "is not None".
    #
    # Unparseable metadata is reported as absent rather than failing the read.
    # Not defensive padding: the stored blob and the metadata model genuinely
    # disagree today - a run started without a workspace root persists metadata
    # the model rejects as incomplete - and this is the WIDE read, whose job is
    # to report the record, not to enforce a schema on it. Failing here would
    # cost a caller the whole transcript over one unrelated field. The
    # disagreement is queued as its own finding; the legacy metadata route
    # shares it and answers a server error for exactly these runs.
    metadata_json = await get_thread_metadata(db, run_id)
    metadata: ThreadMetadata | None = None
    if metadata_json:
        try:
            metadata = ThreadMetadata.model_validate_json(metadata_json)
        except ValidationError:
            logger.warning(
                "run history: stored metadata for %s does not satisfy the "
                "metadata model; reporting it absent",
                run_id,
            )
    # The settled counterpart to the snapshot's PENDING permissions. A gate leaves
    # the pending list as soon as it is answered, and a terminal run expires
    # whatever was still outstanding, so a decision a human actually made was
    # durable in the audit log and readable on no surface at all. This is the wide
    # read - reporting the record is its job.
    decisions = await get_permission_logs_by_thread(db, run_id)

    return RunHistoryResponse(
        run_id=run_id,
        state=snapshot_to_wire(snapshot),
        metadata=metadata,
        transcript_available=capture.transcript is TranscriptAvailability.AVAILABLE,
        transcript_status=capture.transcript,
        permission_decisions=[
            RunPermissionDecision(
                tool_name=decision.tool_name,
                action=decision.action,
                option_id=decision.option_id,
                agent_id=decision.agent_id,
                responded_at=decision.responded_at,
            )
            for decision in decisions
        ],
    )


# ---------------------------------------------------------------------------
# run-archive
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/archive", response_model=RunArchiveResponse)
async def run_archive_endpoint(
    run_id: PathSafeRunId,
    db: AsyncSession = Depends(get_db),
) -> RunArchiveResponse:
    """Move a terminal run to the archived state.

    Archiving is not deletion: the run and its records survive, marked
    historical. A run whose state does not permit archiving is refused rather
    than silently ignored, and repeating the call on an already-archived run is
    that same refusal - the conflict IS the replay signal here.
    """
    result = await archive_thread(db, run_id)
    if result.not_found:
        raise HTTPException(status_code=404, detail="Run not found")
    if not result.archived:
        raise HTTPException(status_code=409, detail=result.error_detail)
    return RunArchiveResponse(run_id=run_id)


# ---------------------------------------------------------------------------
# team-status
# ---------------------------------------------------------------------------


@router.get("/team/status", response_model=TeamStatusV1Response)
async def team_status_endpoint(
    request: Request,
    aggregator: EventAggregator = Depends(get_aggregator),
    db: AsyncSession = Depends(get_db),
) -> TeamStatusV1Response:
    """Report the team's live operational projection.

    A read, and deliberately a narrow one: which agents exist and what state
    they are in, which runs are active, and what is awaiting an answer. It
    carries no prompt, no document body, and no credential - the same
    disclosure discipline the progress channel holds.
    """
    status = await build_team_status(
        db=db,
        aggregator=aggregator,
        heartbeat_threads=getattr(request.app.state, "worker_active_threads", []),
    )
    return TeamStatusV1Response(
        agents=[
            RunAgentSummary(
                agent_id=agent.agent_id,
                display_name=agent.display_name,
                state=agent.state,
            )
            for agent in status.agents
        ],
        active_runs=list(status.active_threads),
        pending_permissions=[
            RunPendingPermission(
                request_id=pending.request_id,
                run_id=pending.thread_id,
                description=pending.description,
                request_status=(
                    pending.request_status or PermissionRequestStatus.PENDING
                ),
            )
            for pending in status.pending_permissions
        ],
    )


# ---------------------------------------------------------------------------
# run-delete
# ---------------------------------------------------------------------------


@router.delete(
    "/runs/{run_id}",
    status_code=204,
    response_model=None,
    responses={
        200: {
            "model": RunDeleteResponse,
            "description": (
                "Deleted, but cleanup was abandoned over permanently "
                "unremovable state; the body names the kinds left behind."
            ),
        },
        204: {"description": "Deleted; every store was cleaned."},
        404: {"description": "No such run."},
        409: {"description": "The run's lifecycle state refuses deletion."},
        503: {"description": "Cleanup is unfinished but resumable; retry."},
    },
)
async def run_delete_endpoint(
    run_id: PathSafeRunId,
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> Response:
    """Delete a run through the durable cross-store deletion saga.

    A replayed request resumes the same saga rather than starting a second
    teardown, so repeated calls converge on one deletion.

    Five outcomes, because the service distinguishes more states than two codes
    can carry: a lifecycle refusal before the saga begins, a clean deletion, a
    deletion that finalized over unremovable state, resumable incomplete
    cleanup, and an already-absent run. The retryable code is reserved for the
    genuinely resumable case - the abandoned case is terminal, and inviting a
    retry there would send the caller to a not-found.
    """
    result = await delete_thread_service(db, run_id, checkpointer=checkpointer)
    if result.not_found:
        raise HTTPException(status_code=404, detail="Run not found")
    if result.error_detail is not None:
        raise HTTPException(status_code=409, detail=result.error_detail)
    if result.cleanup_incomplete:
        raise HTTPException(
            status_code=503,
            detail="Run deletion is in progress; retry to complete cleanup.",
        )
    aggregator.clear_thread_state(run_id)
    if result.abandoned_kinds:
        body = RunDeleteResponse(
            run_id=run_id,
            abandoned_kinds=list(result.abandoned_kinds),
        )
        return JSONResponse(status_code=200, content=body.model_dump(mode="json"))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# run-message
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/messages",
    status_code=202,
    response_model=RunMessageResponse,
)
async def run_message_endpoint(
    run_id: PathSafeRunId,
    body: RunMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunMessageResponse:
    """Send a follow-up turn into an existing run.

    Run-start cannot carry this. A repeat run identifier there is a REPLAY - it
    answers with the original run and never adopts the new body - so without
    this verb the versioned surface can start a run and watch it, but never say
    anything further to it.

    Accepted is not applied: the turn is handed to the worker and execution
    continues asynchronously, so a caller reconciles from the stream or
    run-status rather than from this response.
    """
    result = await send_followup_message(
        db=db,
        thread_id=run_id,
        content=body.content,
        agent_id=body.agent_id or DEFAULT_SUPERVISOR_ID,
        idempotency_key=idempotency_key,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )

    if result.failure_type == FailureType.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Run not found")
    if result.failure_type == FailureType.NO_ACTIVE_PROJECT:
        # Same status the run-creation seam returns for the same missing
        # invariant, so one rule reads identically at both entry points.
        raise HTTPException(status_code=422, detail=result.error_detail)
    if result.failure_type in (
        FailureType.INPUT_REQUIRED,
        FailureType.TERMINAL,
        FailureType.CONFLICT,
    ):
        raise HTTPException(status_code=409, detail=result.error_detail)

    if result.dispatched:
        mark_worker_connected(request)

    if result.failure_type is not None:
        # A follow-up the service resolved to FAILED settles the run terminally
        # without a worker ever running it, so no terminal event will arrive to
        # release its admission. Read the gate rather than seating one: a gate
        # never created has admitted nothing.
        if result.thread_status == ThreadStatus.FAILED.value:
            drain_gate = getattr(request.app.state, "drain_gate", None)
            if drain_gate is not None:
                await drain_gate.release(result.thread_id)
        if result.failure_type in (FailureType.CIRCUIT_OPEN, FailureType.AT_CAPACITY):
            raise HTTPException(status_code=503, detail=result.error_detail)
        raise HTTPException(status_code=502, detail=result.error_detail)

    return RunMessageResponse(
        run_id=result.thread_id,
        action_status=(
            "accepted_not_applied" if result.dispatched else result.thread_status
        ),
        action_id=result.action_id,
        idempotency_key=idempotency_key,
    )


# ---------------------------------------------------------------------------
# permission-respond
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/permissions/{request_id}/respond",
    response_model=RunPermissionRespondResponse,
)
async def run_permission_respond_endpoint(
    run_id: PathSafeRunId,
    request_id: str,
    body: RunPermissionRespondRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    aggregator: EventAggregator = Depends(get_aggregator),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunPermissionRespondResponse:
    """Answer a permission request the run raised on its progress stream.

    The versioned surface already POSES this question - ``permission_request``
    is an enumerated frame on run-stream - and this is where the answer returns.
    Without it the only answering channel is the transition surface, so retiring
    that surface would strand every paused run.

    The verb adds no state machine of its own: it is a versioned projection of
    the same answer path, so at-most-once behaviour comes from there. Answering
    twice replays the stored outcome rather than acting again, an answer arriving
    after the request was applied reports the duplicate without re-dispatching,
    and a superseded or expired request is refused with a journaled rejection
    that replays identically.

    Scoping matters as much as the answer. The request is resolved and checked
    against the run in the path BEFORE anything acts on it, so a guessed request
    id cannot be used to answer another run's question - and because that check
    precedes the service call, a mismatch has no effect at all rather than being
    detected after the fact.
    """
    permission = await get_permission_request(db, request_id)
    if permission is None or permission.thread_id != run_id:
        raise HTTPException(
            status_code=404,
            detail=f"Permission request {request_id!r} not found for run {run_id!r}",
        )

    result = await respond_to_permission(
        db=db,
        request_id=request_id,
        option_id=body.option_id,
        idempotency_key=idempotency_key,
        aggregator=aggregator,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        worker_client=worker_client,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
        notes=body.notes,
    )

    if result.dispatched:
        mark_worker_connected(request)
    if result.circuit_open:
        raise HTTPException(status_code=503, detail=result.error_detail)
    if result.error_detail:
        raise HTTPException(
            status_code=result.error_status_code or 500,
            detail=result.error_detail,
        )

    return RunPermissionRespondResponse(
        run_id=result.thread_id,
        request_id=result.request_id,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        approval_status=result.approval_status,
        idempotency_key=result.idempotency_key,
    )


# ---------------------------------------------------------------------------
# clarification-respond
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/clarifications/{request_id}/respond",
    response_model=RunClarificationRespondResponse,
)
async def run_clarification_respond_endpoint(
    run_id: PathSafeRunId,
    request_id: str,
    body: RunClarificationRespondRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> RunClarificationRespondResponse:
    """Resolve through the durable clarification lease service."""
    resolution: ClarificationResolution
    if body.answers is not None:
        resolution = ClarificationAnswers(
            request_id=request_id, answers=dict(body.answers)
        )
    elif body.decline is not None:
        resolution = ClarificationDecline(request_id=request_id)
    else:
        prompt = body.prompt
        if prompt is None:
            raise RuntimeError("validated clarification resolution is missing")
        resolution = ClarificationContinuation(
            request_id=request_id,
            prompt=prompt,
        )

    result = await respond_to_clarification(
        db,
        thread_id=run_id,
        request_id=request_id,
        resolution=resolution,
        checkpointer=checkpointer,
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        recursion_limit=domain_config.graph_recursion_limit,
        trace_headers=trace_headers(),
    )
    if result.error_status_code is not None:
        raise HTTPException(
            status_code=result.error_status_code,
            detail=result.error_detail or "Clarification resolution failed",
        )

    if result.dispatched:
        mark_worker_connected(request)
    return RunClarificationRespondResponse(
        run_id=result.thread_id,
        request_id=result.request_id,
        accepted=result.accepted,
        applied=result.applied,
        action_status=result.action_status,
        idempotency_key=result.idempotency_key,
    )


# ---------------------------------------------------------------------------
# provider-catalog
# ---------------------------------------------------------------------------


@router.get("/provider-catalog", response_model=ProviderCatalogResponse)
async def provider_catalog_endpoint(
    request: Request,
    workspace_root: str = Query(min_length=1, max_length=4096),
) -> ProviderCatalogResponse:
    """Serve prompt-free, execution-lane-specific catalogs for one workspace."""
    supplied_keys = set(request.query_params.keys())
    if (
        supplied_keys != {"workspace_root"}
        or len(request.query_params.getlist("workspace_root")) != 1
    ):
        raise HTTPException(
            status_code=422,
            detail="provider-catalog accepts exactly one workspace_root query value",
        )
    requested = Path(workspace_root)
    if not requested.is_absolute():
        raise HTTPException(
            status_code=422, detail="workspace_root must be an absolute directory"
        )
    canonical = normalize_workspace_identity(workspace_root)
    if len(canonical) > 4096 or not Path(canonical).is_dir():
        raise HTTPException(
            status_code=422,
            detail="workspace_root must identify an existing directory",
        )
    try:
        records = await provider_catalog_service(request.app).records(canonical)
    except ProviderCatalogScopeCapacityError:
        raise HTTPException(
            status_code=503,
            detail="provider catalog workspace capacity is temporarily busy",
        ) from None
    return ProviderCatalogResponse.from_records(records)


# ---------------------------------------------------------------------------
# presets-list
# ---------------------------------------------------------------------------


@router.get("/presets", response_model=PresetsListResponse)
async def presets_list_endpoint(
    workspace_root: str | None = Query(default=None, max_length=4096),
) -> PresetsListResponse:
    """List team presets truthfully, marking each loadable or unloadable.

    Resolution uses the requested workspace context so workspace-local presets
    are listed alongside the bundled set. A single preset that fails to load or
    validate is reported with ``loadable=False`` and a reason rather than
    omitted or allowed to crash the whole listing. Each loadable preset carries
    its model profiles with per-role effective assignments (resolved by the same
    shared resolver launch uses) and backend-computed eligibility. The whole
    build - file I/O, provider readiness, and the engine reachability probe -
    runs off the event loop.
    """
    ws_root = Path(workspace_root) if workspace_root else None
    presets = await asyncio.to_thread(_build_preset_summaries, ws_root)
    return PresetsListResponse(presets=presets)


def _build_preset_summaries(ws_root: Path | None) -> list[PresetSummary]:
    """Summarize every discoverable preset, probing engine reachability once."""
    from ...providers.model_profiles import probe_engine_reachable
    from ...team.team_config import discover_team_preset_ids

    engine_reachable = probe_engine_reachable()
    return [
        _summarize_preset(preset_id, ws_root, engine_reachable)
        for preset_id in sorted(discover_team_preset_ids(ws_root))
    ]


def _safe_load_reason(exc: Exception) -> str:
    """Return a path-free unavailable reason for a preset load/validation failure.

    Raw exception strings (TOML parse errors, config errors) can embed the
    workspace/preset filesystem path; the served reason states the failure
    category without any path so discovery never leaks local paths.
    """
    from pydantic import ValidationError

    from ...thread.errors import ConfigError, TeamConfigNotFoundError

    if isinstance(exc, TeamConfigNotFoundError):
        return "preset not found"
    if isinstance(exc, ValidationError):
        return "preset failed schema validation"
    if isinstance(exc, ConfigError):
        return "preset TOML is invalid or missing its [team] section"
    return f"preset failed to load ({type(exc).__name__})"


def _preset_origin(preset_id: str, ws_root: Path | None, *, is_mock: bool) -> str:
    """Classify a preset's origin: test_mock, workspace, or bundled."""
    if is_mock:
        return "test_mock"
    if ws_root is not None:
        workspace_toml = ws_root / ".vaultspec" / "teams" / f"{preset_id}.toml"
        if workspace_toml.is_file():
            return "workspace"
    return "bundled"


def _summarize_preset(
    preset_id: str, ws_root: Path | None, engine_reachable: bool
) -> PresetSummary:
    """Load one preset and summarize it, capturing any load failure truthfully.

    Any load or validation error is caught and reported as an unloadable preset
    so one bad TOML never crashes the whole listing (a parse this broad is the
    point: the listing must survive an arbitrarily malformed preset).
    """
    from ...team.team_config import (
        authoring_capability,
        is_mock_preset,
        load_team_config,
        supported_capabilities,
    )

    is_mock = is_mock_preset(preset_id)
    try:
        tc = load_team_config(preset_id, workspace_root=ws_root)
    except Exception as exc:
        logger.warning("Team preset %s failed to load: %s", preset_id, exc)
        return PresetSummary(
            id=preset_id,
            loadable=False,
            unavailable_reason=_safe_load_reason(exc),
            is_mock=is_mock,
            origin=_preset_origin(preset_id, ws_root, is_mock=is_mock),
        )
    return PresetSummary(
        id=tc.id,
        loadable=True,
        display_name=tc.display_name,
        description=tc.description,
        topology=tc.topology.type,
        worker_count=len(tc.workers),
        # The same function run-start REFUSES against, not a second derivation of
        # it: discovery advertises the roles a caller must mint, and a caller that
        # mints exactly what it was told must never then be refused for missing
        # one. Two independent list comprehensions agreeing today is not that
        # guarantee - it is the guarantee's absence, and the failure it would
        # produce lands before the graph ever runs, where nothing downstream can
        # observe it.
        required_roles=required_role_ids(tc),
        authoring_capability=authoring_capability(tc.topology.type),
        is_mock=is_mock,
        origin=_preset_origin(preset_id, ws_root, is_mock=is_mock),
        supported_capabilities=supported_capabilities(tc.topology.type),
        default_profile_id=tc.default_profile_id,
        profiles=_summarize_profiles(tc, ws_root, engine_reachable),
    )


def _summarize_profiles(
    tc: Any, ws_root: Path | None, engine_reachable: bool
) -> list[ProfileSummary]:
    """Resolve and rate every profile of a loadable preset.

    Uses the shared model-profile resolver + eligibility service so the served
    assignments are the exact ones launch would freeze. Provider readiness is
    probed once and shared across profiles; the acceptance gate stays open
    (reported honestly as an unavailable reason).
    """
    from ...graph.enums import Provider
    from ...providers.model_profiles import (
        ProviderReadiness,
        evaluate_profile_eligibility,
        probe_provider_readiness,
        resolve_effective_assignment,
    )

    readiness: dict[Provider, ProviderReadiness] = {}

    def _ready(provider: Provider) -> ProviderReadiness:
        if provider not in readiness:
            readiness[provider] = probe_provider_readiness(provider)
        return readiness[provider]

    # Probe the harness once per preset (workspace-level, profile-independent) so
    # discovery SERVES the harness reason on an unprovisioned authoring preset -
    # the discovery half of the agent-harness contract.
    harness = _probe_harness(tc, ws_root)

    summaries: list[ProfileSummary] = []
    profiles = tc.effective_profiles()
    for profile_id, profile in profiles.items():
        assignment = resolve_effective_assignment(tc, profile_id, ws_root)
        eligibility = evaluate_profile_eligibility(
            assignment,
            readiness=readiness,
            engine_reachable=engine_reachable,
            acceptance_gate_passed=False,
            harness=harness,
        )
        # A role with no declared provider serves an EMPTY provider_id and is not
        # probed for readiness: there is no lane to probe, and substituting one
        # would advertise a provider no preset declared. The reason travels in
        # resolution_error, which the eligibility verdict above already reflects.
        assignments = [
            RoleAssignmentSummary(
                role_id=role.role_id,
                agent_id=role.agent_id,
                provider_id=role.provider.value if role.provider is not None else "",
                capability=role.capability.value if role.capability else None,
                model_name=role.model_name or None,
                fallback_providers=[p.value for p in role.fallback_providers],
                provider_ready=(
                    _ready(role.provider).ready if role.provider is not None else False
                ),
                source=role.source.value,
                resolution_error=role.resolution_error,
            )
            for role in assignment.roles
        ]
        summaries.append(
            ProfileSummary(
                id=profile_id,
                display_name=profile.display_name,
                description=profile.description,
                is_default=profile_id == tc.default_profile_id,
                eligible=eligibility.eligible,
                unavailable_reasons=eligibility.reasons,
                assignments=assignments,
            )
        )
    return summaries


# ---------------------------------------------------------------------------
# service-state
# ---------------------------------------------------------------------------


def route_signature(app: FastAPI) -> list[str]:
    """Return a sorted ``"METHOD path"`` signature from *app*'s OpenAPI schema.

    FastAPI's OpenAPI generation is the one place that correctly flattens the
    (internal, lazily-resolved) route table, so it is used here as the
    public, stable source of truth instead of walking ``app.routes``
    directly. Shared between the live endpoint (this process's app) and the
    doctor CLI's locally-constructed expectation (``create_app()``) so the
    two are comparable: a resident process started before a route landed
    serves a signature missing that entry - detectable without depending on
    a version string editable installs don't bump per-commit.
    """
    paths = app.openapi().get("paths", {})
    return sorted(
        f"{method.upper()} {path}"
        for path, operations in paths.items()
        for method in operations
    )


@router.get("/service", response_model=ServiceStateResponse)
async def service_state_endpoint(
    request: Request,
    services: tuple[
        AsyncSession, EventAggregator, Checkpointer, httpx.AsyncClient
    ] = Depends(get_services),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> ServiceStateResponse:
    """Return truthful, probe-backed readiness for the resident gateway.

    Runs the real dependency probes (database, checkpoint, worker) rather than
    reporting a hardcoded status, and separates process-alive from
    can-accept-run. Engine authoring-backend reachability is reported from
    non-blocking discovery-file freshness.
    """
    # Local import matching this module's convention for control-layer symbols.
    # The constant is minted once per gateway process, so this is the very
    # identity the spawner stamps into the workers it starts.
    from ...control.worker_management import GATEWAY_LIFETIME_ID

    db, _aggregator, _checkpointer, worker_client = services
    full = await build_full_health(
        db=db,
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        app_state=request.app.state,
        # This surface is attach-authenticated, which is the only place the
        # pairing identity may be disclosed; the unauthenticated health endpoint
        # serves the same payload and must not carry it.
        include_pairing=True,
    )
    checks = _object_mapping(full.get("checks")) or {}
    database_check = _object_mapping(checks.get("database")) or {}
    checkpoint_check = _object_mapping(checks.get("checkpoint")) or {}
    worker_check = _object_mapping(checks.get("worker")) or {}
    database_ready = _string_field(database_check, "status") == "ok"
    checkpoint_ready = _string_field(checkpoint_check, "status") == "ok"
    worker_ready = _string_field(worker_check, "status") == "ok"
    can_accept_run = full["status"] == "ok"

    if not database_ready:
        status = "unavailable"
    elif not can_accept_run:
        status = "degraded"
    else:
        status = "ready"

    # The separated readiness facts come from the one readiness authority, fed the
    # live database and worker probe verdicts just computed, so service-state and
    # the liveness surface never compute readiness twice. This is also the
    # projection a discovery contender probes to validate readiness before attach.
    readiness = assemble_desktop_readiness(
        app_state=request.app.state,
        database_ready=database_ready,
        worker_probe_ready=worker_ready,
    )

    # Only genuine failure statuses degrade readiness; informational checks such
    # as worker_spawned ("yes"/"no") or worker_stderr_log ("configured") are not
    # degradation signals.
    degraded_reasons: list[str] = []
    for name, check_value in checks.items():
        check = _object_mapping(check_value)
        if check is None:
            continue
        status_value = _string_field(check, "status")
        if status_value in _DEGRADED_CHECK_STATUSES:
            detail = _string_field(check, "detail") or status_value
            degraded_reasons.append(f"{name}: {detail}")

    return ServiceStateResponse(
        service_version=_service_version(),
        status=status,
        alive=True,
        ready=can_accept_run,
        can_accept_run=can_accept_run,
        gateway_pid=os.getpid(),
        # Pairing identity, served so a consumer never has to infer it from
        # addressing facts: this gateway's own incarnation identity, plus what
        # the worker reported about which incarnation spawned it. A mismatch
        # means the worker belongs to another gateway; both blank mean it was
        # not gateway-spawned at all.
        gateway_lifetime_id=GATEWAY_LIFETIME_ID,
        worker_paired_gateway_lifetime=_string_field(
            full, "worker_paired_gateway_lifetime"
        ),
        worker_generation=_string_field(full, "worker_reported_generation"),
        worker_status=_string_field(full, "worker_status"),
        worker_connected=_bool_field(full, "worker_connected"),
        circuit_breaker=_string_field(full, "circuit_breaker"),
        database_backend=settings.resolved_database_backend,
        checkpoint_backend=settings.resolved_checkpoint_backend,
        database_ready=database_ready,
        checkpoint_ready=checkpoint_ready,
        worker_ready=worker_ready,
        authoring_backend_reachable=probe_engine_discovery_freshness(),
        active_run_capacity=domain_config.max_concurrent_threads,
        degraded_reasons=degraded_reasons,
        routes=route_signature(request.app),
        readiness=readiness,
    )


def _service_version() -> str:
    """Return the installed a2a distribution version, or 'unknown'."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("vaultspec-a2a")
    except PackageNotFoundError:
        return "unknown"
