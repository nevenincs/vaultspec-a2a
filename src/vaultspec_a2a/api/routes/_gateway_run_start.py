"""Run start, preparation, lease commit, and release endpoints."""

import asyncio
import hmac
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import (
    Depends,
    HTTPException,
    Request,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ...context.metadata import ThreadMetadata
from ...control._worker_health import worker_liveness
from ...control.admission import AdmissionBroker
from ...control.config import settings
from ...control.run_start_policy import (
    evaluate_execution_eligibility,
    evaluate_run_start_eligibility,
    required_role_ids,
)
from ...control.thread_service import (
    ThreadCreationRequest,
    ThreadCreationResult,
    ThreadDispatchRuntime,
    create_and_dispatch_thread,
    process_metadata,
)
from ...database import (
    get_thread,
)
from ...database.checkpoints import Checkpointer
from ...database.models import ThreadModel
from ...domain_config import domain_config
from ...providers.team_selection import (
    FrozenTeamSelection,
)
from ...streaming.aggregator import EventAggregator
from ...thread.enums import (
    ThreadStatus,
)
from ...thread.errors import NicknameConflictError
from .._utils import trace_headers
from ..dependencies import (
    get_circuit_breaker,
    get_services,
    get_worker_spawner,
)
from ..run_admission import (
    commit_singleflight,
    request_digest,
    stamped_replay_digest,
)
from ..schemas.gateway import (
    RunCommitResponse,
    RunPrepareResponse,
    RunReleaseResponse,
    RunStage,
    RunStartRequest,
    RunStartResponse,
)
from ..schemas.gateway_readiness import WorkerLifecycleState
from .gateway import (
    _admission_readiness,
    _body_with_frozen_selection,
    _canonical_replay_body,
    _load_preset_or_refuse,
    _modern_frozen_disclosure,
    _persist_lease,
    _persist_request_digest,
    _persist_team_selection,
    _persisted_lease_binding,
    _prepare_workspace_root,
    _probe_admission_readiness,
    _probe_harness,
    _raise_for_dispatch_failure,
    _read_persisted_team_selection,
    _release_binding_digest,
    _release_ineligible_reservation,
    _replay_identity_or_conflict,
    _validate_and_freeze_selection_or_refuse,
    admission_broker,
    admission_gate,
    router,
)

__all__ = ["_RunLeaseBinding"]

logger = logging.getLogger("vaultspec_a2a.api.routes.gateway")

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
    runtime = _RunRuntime(circuit_breaker, worker_spawner, worker_client)
    if body.stage == RunStage.PREPARE:
        return await _run_prepare(request, body, worker_spawner, worker_client)
    if body.stage == RunStage.COMMIT:
        return await _run_commit(request, body, db, runtime)
    if body.stage == RunStage.RELEASE:
        return await _run_release(request, body)
    return await _run_direct_start(request, body, db, runtime)


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


@dataclass(frozen=True, slots=True)
class _RunRuntime:
    circuit_breaker: Any
    worker_spawner: Any
    worker_client: httpx.AsyncClient


@dataclass(frozen=True, slots=True)
class _RunAdmission:
    workspace_root: Path
    nickname: str
    metadata: ThreadMetadata | None
    metadata_json: str
    frozen: FrozenTeamSelection


@dataclass(frozen=True, slots=True)
class _RunWinner:
    thread_id: str
    status: str
    nickname: str | None
    metadata_json: str | None


def _run_metadata_with_request_fields(body: RunStartRequest) -> ThreadMetadata | None:
    # Keep process_metadata's enrichment off the request used for replay digest.
    metadata = (
        body.metadata.model_copy(deep=True) if body.metadata is not None else None
    )
    if body.feature_tag and metadata is not None:
        metadata = metadata.model_copy(update={"feature_tag": body.feature_tag})
    # The worker resolves this opaque batch id through the engine read route.
    if body.feedback_batch_id and metadata is not None:
        metadata = metadata.model_copy(
            update={"feedback_batch_id": body.feedback_batch_id}
        )
    return metadata


async def _prepare_run_admission(
    request: Request, body: RunStartRequest, commit_binding: _RunLeaseBinding | None
) -> _RunAdmission:
    run_id = body.run_id
    # Thread the target feature onto the metadata so it reaches dispatch and the
    # vault index; the top-level field is authoritative when both are present.
    metadata = _run_metadata_with_request_fields(body)
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
    return _RunAdmission(ws_root, nickname, metadata, metadata_json, frozen)


async def _attempt_thread_creation(
    db: AsyncSession,
    body: RunStartRequest,
    request: ThreadCreationRequest,
    runtime: _RunRuntime,
) -> ThreadCreationResult | _RunWinner:
    for attempt in range(4):
        try:
            return await create_and_dispatch_thread(
                db,
                request,
                runtime=ThreadDispatchRuntime(
                    circuit_breaker=runtime.circuit_breaker,
                    worker_spawner=runtime.worker_spawner,
                    worker_client=runtime.worker_client,
                    recursion_limit=domain_config.graph_recursion_limit,
                    trace_headers=trace_headers(),
                ),
            )
        except OperationalError as exc:
            if (
                db.get_bind().dialect.name != "sqlite"
                or "database is locked" not in str(exc).lower()
                or attempt == 3
            ):
                raise
            await db.rollback()
            winner = await get_thread(db, body.run_id)
            if winner is not None:
                return _RunWinner(
                    winner.id,
                    winner.status,
                    winner.nickname,
                    winner.thread_metadata,
                )
            await db.rollback()
            await asyncio.sleep(0.05 * (attempt + 1))
    raise RuntimeError("run admission retry exhausted without a result")


async def _create_thread_with_retry(
    db: AsyncSession,
    body: RunStartRequest,
    prepared: _RunAdmission,
    runtime: _RunRuntime,
) -> ThreadCreationResult | _RunWinner:
    request = ThreadCreationRequest(
        thread_id=body.run_id,
        title=body.title,
        initial_message=body.message,
        team_preset=body.team_preset,
        autonomous=body.autonomous,
        nickname=prepared.nickname,
        metadata=prepared.metadata,
        metadata_json=prepared.metadata_json,
        workspace_root=prepared.workspace_root,
        actor_tokens=body.actor_tokens,
        model_assignment=prepared.frozen.compiler_map(),
    )
    try:
        return await _attempt_thread_creation(db, body, request, runtime)
    except NicknameConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Run nickname already exists: {exc.nickname!r}",
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        winner = await get_thread(db, body.run_id)
        if winner is not None:
            logger.info(
                "Run %s lost a concurrent insert race for its run id; "
                "resolving the losing request against the durable winner",
                body.run_id,
            )
            return _RunWinner(
                winner.id,
                winner.status,
                winner.nickname,
                winner.thread_metadata,
            )
        if "nickname" in str(exc).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Run nickname already exists: {prepared.nickname!r}",
            ) from exc
        raise


async def _create_run_core(
    request: Request,
    body: RunStartRequest,
    db: AsyncSession,
    runtime: _RunRuntime,
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

    prepared = await _prepare_run_admission(request, body, commit_binding)
    frozen = prepared.frozen

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
        creation = await _create_thread_with_retry(db, body, prepared, runtime)
        persisted = True
        if isinstance(creation, _RunWinner):
            _replay_identity_or_conflict(
                creation.thread_id, creation.metadata_json, body
            )
            return _RunDispatchResult(
                thread_id=creation.thread_id,
                status=creation.status,
                nickname=creation.nickname,
                frozen=_read_persisted_team_selection(creation.metadata_json),
                replayed=True,
            )
        result = creation

        # The durable run row now exists and owns its admission; the finally no
        # longer releases it, because a durable run is released by its terminal
        # event in the relay handler.
        persisted = True
        if result.dispatched:
            worker_liveness(request.app.state).record_contact()

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
    runtime: _RunRuntime,
) -> RunStartResponse:
    """One-shot start: create and dispatch a run in a single call (unchanged path)."""
    result = await _create_run_core(
        request,
        body,
        db,
        runtime,
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
    runtime: _RunRuntime,
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
            runtime,
        )


async def _commit_replay(
    existing: ThreadModel,
    body: RunStartRequest,
    broker: AdmissionBroker,
    reservation_id: str,
) -> RunCommitResponse:
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
    await broker.complete_commit(reservation_id, binding.lease_id)
    return RunCommitResponse(
        run_id=existing.id,
        status=existing.status,
        lease_id=binding.lease_id,
        nickname=existing.nickname,
        frozen_assignment=_modern_frozen_disclosure(existing_modern),
    )


async def _prepare_commit_eligibility(
    request: Request,
    body: RunStartRequest,
    runtime: _RunRuntime,
    reservation_id: str,
) -> tuple[RunStartRequest, str]:
    broker = admission_broker(request.app)
    ws_root = _prepare_workspace_root(body)
    team_config = _load_preset_or_refuse(body.team_preset, ws_root)
    frozen = await _validate_and_freeze_selection_or_refuse(
        request.app, body, team_config, ws_root
    )
    canonical_body = _body_with_frozen_selection(body, frozen)
    commit_digest = request_digest(canonical_body, prepared=False)
    # Evaluate worker and provider eligibility BEFORE consuming the reservation,
    # accepting the actor tokens, or creating a run: run credentials are minted
    # only after the runtime and provider are eligible. The worker reachability is
    # probed live so the verdict never lags behind the watchdog's status ladder; a
    # refusal releases the reservation so a failed commit leaks nothing.
    from ...control._worker_health import probe_worker_health

    logger.info("commit step: probe_worker")
    probe = await probe_worker_health(settings.worker_url, client=runtime.worker_client)
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
    return canonical_body, commit_digest


async def _classify_failed_commit(
    db: AsyncSession,
    run_id: str,
    binding: _RunLeaseBinding,
    broker: AdmissionBroker,
) -> None:
    # A failed response may follow a durable commit. Reopen a reservation only
    # when a fresh authoritative read proves that no run row exists.
    try:
        await db.rollback()
        persisted = await get_thread(db, run_id)
    except Exception:
        logger.exception(
            "Could not classify failed commit durability for run %s reservation %s",
            run_id,
            binding.reservation_id,
        )
        return
    persisted_binding = (
        _persisted_lease_binding(persisted.thread_metadata)
        if persisted is not None
        else None
    )
    if (
        persisted_binding is not None
        and persisted_binding.lease_id == binding.lease_id
        and persisted_binding.reservation_id == binding.reservation_id
        and hmac.compare_digest(persisted_binding.commit_digest, binding.commit_digest)
    ):
        await broker.complete_commit(binding.reservation_id, binding.lease_id)
    elif persisted is None:
        if not await broker.abort_commit(binding.reservation_id, binding.lease_id):
            logger.error(
                "Could not restore failed commit reservation %s for run %s",
                binding.reservation_id,
                run_id,
            )
    else:
        logger.error(
            "Failed commit for run %s found a conflicting durable binding; "
            "reservation %s remains committing until expiry",
            run_id,
            binding.reservation_id,
        )


async def _run_commit_locked(
    request: Request,
    body: RunStartRequest,
    db: AsyncSession,
    runtime: _RunRuntime,
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
        return await _commit_replay(existing, body, broker, reservation_id)
    canonical_body, commit_digest = await _prepare_commit_eligibility(
        request, body, runtime, reservation_id
    )

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
            runtime,
            commit_binding=binding,
        )
    except BaseException:
        await _classify_failed_commit(db, run_id, binding, broker)
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
