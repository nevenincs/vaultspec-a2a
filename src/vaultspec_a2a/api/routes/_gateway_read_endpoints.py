"""Run discovery, state, history, and lifecycle read endpoints."""

import logging
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal

import httpx
from fastapi import (
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ...context.metadata import ThreadMetadata
from ...control._worker_health import worker_liveness
from ...control.cancel_service import (
    CancelRuntime,
    cancel_thread,
    raise_for_cancel_failure,
)
from ...control.run_discovery_service import discover_active_runs
from ...control.team_service import build_team_status
from ...control.thread_listing import list_threads_service
from ...control.thread_service import (
    archive_thread,
    delete_thread_service,
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
    get_thread_metadata,
)
from ...database.checkpoints import Checkpointer
from ...domain_config import domain_config
from ...providers import ProviderCondition
from ...streaming.aggregator import EventAggregator
from ...thread.clarification import (
    pending_clarification,
)
from ...thread.constants import (
    MAX_FEATURE_TAG_LENGTH,
    MAX_WORKSPACE_ROOT_LENGTH,
)
from ...thread.enums import (
    TERMINAL_STATUSES,
    ApprovalStatus,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from .._utils import trace_headers
from ..dependencies import (
    get_aggregator,
    get_checkpointer,
    get_circuit_breaker,
    get_worker_client,
    get_worker_spawner,
)
from ..schemas.gateway import (
    ActiveRunRecord,
    ActiveRunsResponse,
    PathSafeRunId,
    RoleState,
    RunAgentSummary,
    RunArchiveResponse,
    RunCancelResponse,
    RunDeleteResponse,
    RunHistoryResponse,
    RunPendingPermission,
    RunPermissionDecision,
    RunStatusResponse,
    RunSummariesResponse,
    RunSummaryRecord,
    TeamStatusV1Response,
    TopologyPosition,
)
from ..schemas.snapshots import ThreadStateSnapshot
from ..thread_stream import build_thread_stream_response
from ..workspace import require_existing_workspace_root
from .gateway import (
    _modern_frozen_disclosure,
    _optional_enum,
    _persisted_lease_binding,
    _persisted_lease_id,
    _read_persisted_team_selection,
    admission_gate,
    router,
)

logger = logging.getLogger("vaultspec_a2a.api.routes.gateway")


class _ActiveRunsOptions(BaseModel):
    """Query options for the active-run and history listing endpoint."""

    state: Literal["active", "all"] = Query(default="active")
    workspace_root: str | None = Query(
        default=None, min_length=1, max_length=MAX_WORKSPACE_ROOT_LENGTH
    )
    feature_tag: str | None = Query(
        default=None, min_length=1, max_length=MAX_FEATURE_TAG_LENGTH
    )
    status: ThreadStatus | None = Query(default=None)
    limit: int = Query(default=50, ge=1, le=100)
    offset: int = Query(default=0, ge=0)


@dataclass(frozen=True, slots=True)
class _CancelEndpointDependencies:
    """Injected resources needed by the cancel service."""

    db: AsyncSession
    runtime: CancelRuntime


def _get_cancel_endpoint_dependencies(
    db: AsyncSession = Depends(get_db),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
    circuit_breaker: Any = Depends(get_circuit_breaker),
    worker_spawner: Any = Depends(get_worker_spawner),
) -> _CancelEndpointDependencies:
    """Group cancel's service dependencies without changing their providers."""
    return _CancelEndpointDependencies(
        db=db,
        runtime=CancelRuntime(
            circuit_breaker,
            worker_spawner,
            worker_client,
            domain_config.graph_recursion_limit,
            trace_headers(),
        ),
    )


__all__ = ["_active_role", "snapshot_to_wire"]

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
    options: Annotated[_ActiveRunsOptions, Query()],
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
    workspace = (
        require_existing_workspace_root(
            options.workspace_root,
            absolute_detail="workspace_root must be absolute",
        )
        if options.workspace_root is not None
        else None
    )

    if options.state == "all":
        listing = await list_threads_service(
            db,
            status_filter=options.status,
            limit=options.limit,
            offset=options.offset,
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
                    repair_status=_optional_enum(RepairStatus, thread.repair_status),
                    execution_readiness=_optional_enum(
                        RepairStatus, thread.execution_readiness
                    ),
                    approval_status=_optional_enum(
                        ApprovalStatus, thread.approval_status
                    ),
                    approval_request_id=thread.approval_request_id,
                    created_at=thread.created_at,
                    updated_at=thread.updated_at,
                    source_branch=thread.source_branch,
                    callee=thread.callee,
                )
                for thread in listing.threads
            ],
            truncated=(options.offset + len(listing.threads)) < listing.total,
            total=listing.total,
        )

    result = await discover_active_runs(
        db,
        checkpointer=request.app.state.checkpointer,
        workspace_root=workspace,
        feature_tag=options.feature_tag,
        limit=options.limit,
    )
    return ActiveRunsResponse(
        state=options.state,
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
        approval_status=_optional_enum(ApprovalStatus, snapshot.approval_status),
        approval_request_id=snapshot.approval_request_id,
        checkpoint_id=snapshot.checkpoint_id,
        last_sequence=snapshot.last_sequence,
        repair_status=_optional_enum(RepairStatus, snapshot.repair_status),
        execution_readiness=_optional_enum(RepairStatus, snapshot.execution_readiness),
        degraded_reasons=snapshot.degraded_reasons,
        failure_reason=snapshot.failure_reason,
        # Named explicitly beside the reason because this response is built with
        # keyword arguments rather than validated from the snapshot: nothing here
        # is dropped silently, but nothing arrives without being written either,
        # which is how the reason itself was missed when it was first persisted.
        provider_condition=_optional_enum(
            ProviderCondition, snapshot.provider_condition
        ),
        # The account of an operation that did not take on a run that is still
        # alive. Its writers decline to set the failure reason precisely because
        # the run survives, so without this line their account is durable and
        # unreadable - recorded for nobody.
        repair_reason=snapshot.repair_reason,
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
    dependencies: _CancelEndpointDependencies = Depends(
        _get_cancel_endpoint_dependencies
    ),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunCancelResponse:
    """Cancel a run idempotently."""
    result = await cancel_thread(
        db=dependencies.db,
        thread_id=run_id,
        idempotency_key=idempotency_key,
        runtime=dependencies.runtime,
    )

    raise_for_cancel_failure(result, resource_noun="Run")

    if result.cancelled:
        worker_liveness(request.app.state).record_contact()

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
    # disagreement is queued as its own finding.
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
        heartbeat_threads=worker_liveness(request.app.state).active_threads,
    )
    return TeamStatusV1Response(
        agents=[
            RunAgentSummary(
                run_id=agent.thread_id,
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
