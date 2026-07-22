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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...control.admission import AdmissionBroker, AdmissionReadiness
from ...control.cancel_service import cancel_thread
from ...control.config import settings
from ...control.drain import DrainGate
from ...control.health import (
    assemble_desktop_readiness,
    build_full_health,
    probe_engine_discovery_freshness,
)
from ...control.run_discovery_service import discover_active_runs
from ...control.run_start_policy import (
    evaluate_execution_eligibility,
    evaluate_run_start_eligibility,
    required_role_ids,
)
from ...control.thread_service import (
    ThreadCreationRequest,
    create_and_dispatch_thread,
    generate_thread_id,
    process_metadata,
)
from ...control.thread_state_service import (
    build_thread_state,
    project_semantic_phase,
    read_run_authoring_ids,
    read_run_semantic_context,
)
from ...database import get_thread
from ...database.checkpoints import Checkpointer
from ...database.session import get_db
from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...thread.dispatch_policy import FailureType
from ...thread.enums import TERMINAL_STATUSES, ThreadStatus
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
from ..run_admission import commit_singleflight, request_digest
from ..schemas.gateway import (
    ActiveRunRecord,
    ActiveRunsResponse,
    PathSafeRunId,
    PresetsListResponse,
    PresetSummary,
    ProfileSummary,
    RoleAssignmentSummary,
    RoleState,
    RunCancelResponse,
    RunCommitResponse,
    RunPrepareResponse,
    RunReleaseResponse,
    RunStage,
    RunStartRequest,
    RunStartResponse,
    RunStatusResponse,
    ServiceStateResponse,
    TopologyPosition,
)
from .thread_stream import build_thread_stream_response

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
    app_state: Any, *, worker_probe_ready: bool | None = None
) -> AdmissionReadiness:
    """Project the seated desktop readiness facts into an admission-readiness view.

    Reads the single readiness authority (``assemble_desktop_readiness``) over the
    seated worker and database state - the cheap, non-blocking surface - so a
    prepare reports the same worker, provider, and admission facts the readiness
    model and service-state verb serve, never a second computation.
    """
    readiness = assemble_desktop_readiness(
        app_state=app_state, worker_probe_ready=worker_probe_ready
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
    from ...control.worker_management import _check_worker_health

    reachable = await _check_worker_health(settings.worker_url, client=worker_client)
    return _admission_readiness(app_state, worker_probe_ready=reachable)


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
    profile_id: str | None
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
    if body.run_id is not None:
        existing = await get_thread(db, body.run_id)
        if existing is not None:
            existing_profile = _persisted_profile_id(existing.thread_metadata)
            if existing_profile is not None and existing_profile != body.profile_id:
                # A retry that changes the frozen profile is a conflict, not a
                # dispatch-exactly-once replay - the run is already frozen.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Run {existing.id!r} was already started with profile "
                        f"{existing_profile!r}; cannot re-start with "
                        f"{body.profile_id!r}"
                    ),
                )
            # The profile check above covers one field. Every other
            # behaviour-affecting field - the prompt, the preset, the feature
            # tag, the feedback batch - could differ on a replay and the original
            # run was returned as though the request matched, silently
            # discarding the second intention. Compare the whole request.
            persisted_digest = _persisted_request_digest(existing.thread_metadata)
            if persisted_digest is not None and persisted_digest != request_digest(
                body, prepared=False
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Run {existing.id!r} was already started with a "
                        "different request body; a replay must carry the same "
                        "request to return the original run"
                    ),
                )
            return _RunDispatchResult(
                thread_id=existing.id,
                status=existing.status,
                nickname=existing.nickname,
                profile_id=existing_profile,
                frozen=None,
                replayed=True,
            )
    run_id = body.run_id or generate_thread_id()

    # Thread the target feature onto the metadata so it reaches dispatch and the
    # vault index; the top-level field is authoritative when both are present.
    metadata = body.metadata
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

    # model-profiles: validate the selected profile belongs to the preset and
    # is runnable, then freeze its effective per-role assignment. The frozen record
    # is threaded to the worker (compilation consumes it verbatim) and persisted in
    # metadata so restart reproduces it. Never silently falls back to team-defaults.
    frozen = _resolve_and_freeze_profile_or_refuse(
        team_config, body.profile_id, ws_root
    )
    metadata_json = _persist_frozen(metadata_json, frozen)
    # Persist what this run was started with, so a later replay is compared
    # against the whole request rather than one field of it.
    if body.run_id is not None:
        metadata_json = _persist_request_digest(
            metadata_json, request_digest(body, prepared=False)
        )
    # Bind the committed reservation's non-secret lease identity to the run,
    # durably, so terminal settlement and post-restart reconciliation recover it.
    if commit_binding is not None:
        metadata_json = _persist_lease(metadata_json, commit_binding)

    # Admission gate: a draining gateway refuses a new run before any durable
    # state is created, so drain closes admission ahead of bounded cancellation.
    # An admitted run joins the active set the drain waits on; it is released on
    # a terminal outcome (the execution-state settlement path) or here, in the
    # finally, on EVERY path that leaves no durable run.
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
                    profile_id=frozen.profile_id,
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
        except IntegrityError:
            # Insert-or-return idempotency: two simultaneous retries with the same
            # run_id race past the check-then-act guard above; the loser's insert
            # hits the primary-key unique violation. Roll back and return the
            # winner's run as the dispatch-exactly-once response rather than a 500.
            await db.rollback()
            winner = await get_thread(db, run_id)
            if winner is not None:
                persisted = True
                return _RunDispatchResult(
                    thread_id=winner.id,
                    status=winner.status,
                    nickname=winner.nickname,
                    profile_id=_persisted_profile_id(winner.thread_metadata),
                    frozen=None,
                    replayed=True,
                )
            raise

        # The durable run row now exists and owns its admission; a dispatch failure
        # below leaves the run durable (released on its terminal outcome), so the
        # admission is kept.
        persisted = True
        if result.dispatched:
            mark_worker_connected(request)

        _raise_for_dispatch_failure(result.failure_type, result.error_detail)

        return _RunDispatchResult(
            thread_id=result.thread_id,
            status=result.status,
            nickname=result.nickname,
            profile_id=frozen.profile_id,
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
        profile_id=result.profile_id,
        assignments=_frozen_disclosure(result.frozen)
        if result.frozen is not None
        else [],
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
    ws_root = _prepare_workspace_root(body)
    team_config = _load_preset_or_refuse(body.team_preset, ws_root)
    broker = admission_broker(request.app)
    outcome = await broker.prepare(
        required_roles=required_role_ids(team_config),
        ensure_worker=worker_spawner.ensure_worker,
        probe_readiness=lambda: _probe_admission_readiness(
            request.app.state, worker_client
        ),
        binding_digest=request_digest(body, prepared=True),
    )
    if (
        not outcome.admitted
        or outcome.reservation_id is None
        or outcome.lease_id is None
    ):
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
    if run_id is None:  # pragma: no cover - guarded by the schema
        raise HTTPException(status_code=422, detail="commit requires a stable run id")
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
    if run_id is None:  # pragma: no cover - guarded by the schema
        raise HTTPException(status_code=422, detail="commit requires a stable run id")
    commit_digest = request_digest(body, prepared=False)
    broker = admission_broker(request.app)

    # A commit acknowledgement can be lost after the durable run is created.
    # Recover that exact replay before consulting the now-consumed reservation,
    # returning the persisted non-secret gateway lease identity.
    existing = await get_thread(db, run_id)
    if existing is not None:
        existing_frozen = _read_persisted_frozen(existing.thread_metadata)
        if existing_frozen is None:
            raise HTTPException(
                status_code=409,
                detail="existing run has no committed model profile binding",
            )
        existing_profile = existing_frozen.profile_id
        if existing_profile != body.profile_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Run {existing.id!r} was already started with profile "
                    f"{existing_profile!r}; cannot re-start with "
                    f"{body.profile_id!r}"
                ),
            )
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
            profile_id=existing_profile,
            assignments=_frozen_disclosure(existing_frozen),
        )
    # Evaluate worker and provider eligibility BEFORE consuming the reservation,
    # accepting the actor tokens, or creating a run (ADR: mint run credentials only
    # after the runtime and provider are eligible). The worker reachability is
    # probed live so the verdict never lags behind the watchdog's status ladder; a
    # refusal releases the reservation so a failed commit leaks nothing.
    from ...control.worker_management import _check_worker_health

    worker_reachable = await _check_worker_health(
        settings.worker_url, client=worker_client
    )
    readiness = _admission_readiness(request.app.state)
    execution = evaluate_execution_eligibility(
        worker_reachable=worker_reachable,
        provider_eligibility=readiness.provider_eligibility,
    )
    if not execution.eligible:
        await broker.release(
            reservation_id,
            binding_digest=request_digest(body, prepared=True),
        )
        raise HTTPException(status_code=503, detail=execution.reason)

    presented_roles = (
        set(body.actor_tokens.tokens) if body.actor_tokens is not None else set()
    )
    outcome = await broker.commit(
        reservation_id,
        binding_digest=request_digest(body, prepared=True),
        presented_roles=presented_roles,
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
        profile_id=result.profile_id,
        assignments=_frozen_disclosure(result.frozen)
        if result.frozen is not None
        else [],
    )


async def _run_release(request: Request, body: RunStartRequest) -> RunReleaseResponse:
    """Explicitly free a prepared slot after a dashboard-side failure."""
    reservation_id = body.reservation_id
    if reservation_id is None:  # pragma: no cover - guarded by the schema
        raise HTTPException(status_code=422, detail="release requires a reservation id")
    run_id = body.run_id
    if run_id is None:  # pragma: no cover - guarded by the schema
        raise HTTPException(status_code=422, detail="release requires a stable run id")
    async with commit_singleflight(request.app).hold(run_id):
        released = await admission_broker(request.app).release(
            reservation_id,
            binding_digest=request_digest(body, prepared=True),
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


# The metadata key binding a run to its non-secret admission lease identity. The
# gateway writes it at commit and the terminal handler reads it back; both restate
# this key inline, matching the metadata convention used for the frozen profile.
_RUN_LEASE_METADATA_KEY = "run_lease"

# The canonical digest of the request that created a run. Persisted on every
# create so a later replay can be compared against what the run was actually
# started with, rather than against the single field the check previously read.
_REQUEST_DIGEST_METADATA_KEY = "run_request_digest"


def _persist_request_digest(metadata_json: str | None, digest: str) -> str:
    """Embed the creating request's canonical digest into run metadata."""
    data: dict[str, Any] = {}
    if metadata_json:
        try:
            loaded = json.loads(metadata_json)
        except (json.JSONDecodeError, TypeError):
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    data[_REQUEST_DIGEST_METADATA_KEY] = digest
    return json.dumps(data)


def _persisted_request_digest(metadata_json: str | None) -> str | None:
    """Read the creating request's digest, or ``None`` for a pre-existing run.

    ``None`` means the run predates digest persistence rather than that its
    request was empty, so the caller must treat it as unknown and fall back to
    the narrower comparison instead of refusing a legitimate replay.
    """
    if not metadata_json:
        return None
    try:
        data = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    digest = data.get(_REQUEST_DIGEST_METADATA_KEY) if isinstance(data, dict) else None
    return digest if isinstance(digest, str) and digest else None


def _persist_lease(metadata_json: str | None, binding: _RunLeaseBinding) -> str:
    """Embed the non-secret lease and exact replay binding into run metadata."""
    data: dict[str, Any] = {}
    if metadata_json:
        try:
            loaded = json.loads(metadata_json)
        except (json.JSONDecodeError, TypeError):
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
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
    if not metadata_json:
        return None
    try:
        data = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError):
        return None
    lease = data.get(_RUN_LEASE_METADATA_KEY) if isinstance(data, dict) else None
    lease_id = lease.get("lease_id") if isinstance(lease, dict) else None
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
    if not metadata_json:
        return None
    try:
        data = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    lease = data.get(_RUN_LEASE_METADATA_KEY)
    if not isinstance(lease, dict):
        return None
    lease_id = lease.get("lease_id")
    reservation_id = lease.get("reservation_id")
    commit_digest = lease.get("commit_digest")
    if not all(
        isinstance(value, str) and value
        for value in (lease_id, reservation_id, commit_digest)
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


def _resolve_and_freeze_profile_or_refuse(
    team_config: Any, profile_id: str, ws_root: Path | None
) -> Any:
    """Validate the selected profile and freeze its effective assignment, or 4xx.

    Refuses an unknown profile (422) and a profile that is not runnable - a role
    whose provider is not ready with no eligible fallback (422). Launch gates only
    on provider readiness: the production acceptance gate and engine reachability
    are discovery-certification signals surfaced by presets-list, not launch
    blockers (enforcing them here would refuse every run). Never silently replaces
    the selection with team-defaults.
    """
    from ...providers.model_profiles import (
        evaluate_profile_eligibility,
        freeze_assignment,
        resolve_effective_assignment,
    )

    profiles = team_config.effective_profiles()
    if profile_id not in profiles:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown model profile {profile_id!r} for preset "
                f"{team_config.id!r}; available: {sorted(profiles)!r}"
            ),
        )
    assignment = resolve_effective_assignment(team_config, profile_id, ws_root)
    eligibility = evaluate_profile_eligibility(
        assignment, engine_reachable=True, acceptance_gate_passed=True
    )
    if not eligibility.eligible:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Model profile {profile_id!r} is not runnable: "
                + "; ".join(eligibility.reasons)
            ),
        )
    return freeze_assignment(assignment)


def _persist_frozen(metadata_json: str | None, frozen: Any) -> str:
    """Embed the frozen profile record into the thread metadata JSON for restart."""
    import json

    data: dict[str, Any] = {}
    if metadata_json:
        try:
            loaded = json.loads(metadata_json)
        except (json.JSONDecodeError, TypeError):
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    data["model_profile"] = frozen.to_record()
    return json.dumps(data)


def _read_persisted_frozen(metadata_json: str | None) -> Any:
    """Rebuild the persisted :class:`FrozenAssignment` from thread metadata, or None."""
    import json

    from ...providers.model_profiles import frozen_from_record

    if not metadata_json:
        return None
    try:
        data = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return frozen_from_record(data.get("model_profile"))


def _persisted_profile_id(metadata_json: str | None) -> str | None:
    """Read only the persisted profile id from thread metadata, or None."""
    frozen = _read_persisted_frozen(metadata_json)
    return frozen.profile_id if frozen is not None else None


def _frozen_disclosure(frozen: Any) -> list[RoleAssignmentSummary]:
    """Build the safe per-role disclosure from a frozen assignment record."""
    return [
        RoleAssignmentSummary(
            role_id=str(role.get("role_id", "")),
            agent_id=agent_id,
            provider_id=str(role.get("provider", "")),
            capability=role.get("capability"),
            model_name=role.get("model_name") or None,
            fallback_providers=list(role.get("fallback", [])),
            source=str(role.get("source", "team_default")),
        )
        for agent_id, role in frozen.roles.items()
    ]


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


@router.get("/runs", response_model=ActiveRunsResponse)
async def active_runs_endpoint(
    state: Literal["active"] = Query(default="active"),
    workspace_root: str | None = Query(default=None, min_length=1, max_length=4096),
    feature_tag: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ActiveRunsResponse:
    """Return a capped identity projection for durable non-terminal runs."""
    workspace = Path(workspace_root) if workspace_root is not None else None
    if workspace is not None and not workspace.is_absolute():
        raise HTTPException(status_code=422, detail="workspace_root must be absolute")

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
    snapshot = await build_thread_state(
        db, thread_id=run_id, aggregator=aggregator, checkpointer=checkpointer
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Run not found")

    thread = await get_thread(db, run_id)
    team_preset = thread.team_preset if thread is not None else None
    proposal_ids, changeset_ids = await read_run_authoring_ids(checkpointer, run_id)
    semantic = await read_run_semantic_context(checkpointer, run_id)
    semantic_phase = project_semantic_phase(
        status=snapshot.status,
        next_nodes=snapshot.next_nodes,
        repair_status=snapshot.repair_status,
    )
    # model-profiles: disclose the run's frozen profile + effective assignment,
    # reproduced verbatim from run metadata (never re-resolved).
    frozen = _read_persisted_frozen(
        thread.thread_metadata if thread is not None else None
    )

    return RunStatusResponse(
        run_id=snapshot.thread_id,
        status=ThreadStatus(snapshot.status),
        semantic_phase=semantic_phase,
        feature_tag=semantic.feature_tag,
        authoring_session_id=semantic.authoring_session_id,
        topology=TopologyPosition(
            team_preset=team_preset,
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
        profile_id=frozen.profile_id if frozen is not None else None,
        assignments=_frozen_disclosure(frozen) if frozen is not None else [],
        lease_id=_persisted_lease_id(
            thread.thread_metadata if thread is not None else None
        ),
        reservation_id=(
            binding.reservation_id
            if (
                binding := _persisted_lease_binding(
                    thread.thread_metadata if thread is not None else None
                )
            )
            is not None
            else None
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
    ``/api/threads/{id}/stream`` route uses - one code path, the same versioned
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

    if result.failure_type == FailureType.NOT_FOUND:
        raise HTTPException(status_code=404, detail="Run not found")
    if result.failure_type is not None:
        raise HTTPException(
            status_code=502, detail=result.error_detail or "Cancel dispatch failed"
        )

    if result.cancelled:
        mark_worker_connected(request)

    # Cancellation is the drain's tool and is never itself admission-gated. When
    # a cancel settles the run terminally here (e.g. a submitted-but-undispatched
    # run), release it from the admission gate so a concurrent drain can quiesce;
    # a run that only reaches CANCELLING is released on its terminal event.
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
        required_roles=[w.agent_id for w in tc.workers],
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
        assignments = [
            RoleAssignmentSummary(
                role_id=role.role_id,
                agent_id=role.agent_id,
                provider_id=role.provider.value,
                capability=role.capability.value if role.capability else None,
                model_name=role.model_name or None,
                fallback_providers=[p.value for p in role.fallback_providers],
                provider_ready=_ready(role.provider).ready,
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
    db, _aggregator, _checkpointer, worker_client = services
    full = await build_full_health(
        db=db,
        worker_client=worker_client,
        circuit_breaker=circuit_breaker,
        worker_spawner=worker_spawner,
        app_state=request.app.state,
    )
    checks: dict[str, Any] = full["checks"]
    database_ready = checks.get("database", {}).get("status") == "ok"
    checkpoint_ready = checks.get("checkpoint", {}).get("status") == "ok"
    worker_ready = checks.get("worker", {}).get("status") == "ok"
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
    degraded_reasons = [
        f"{name}: {check.get('detail', check.get('status'))}"
        for name, check in checks.items()
        if isinstance(check, dict) and check.get("status") in _DEGRADED_CHECK_STATUSES
    ]

    return ServiceStateResponse(
        service_version=_service_version(),
        status=status,
        alive=True,
        ready=can_accept_run,
        can_accept_run=can_accept_run,
        gateway_pid=os.getpid(),
        worker_status=full.get("worker_status"),
        worker_connected=full.get("worker_connected"),
        circuit_breaker=full.get("circuit_breaker"),
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
