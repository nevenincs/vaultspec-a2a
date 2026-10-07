"""Run discovery, state, history, and lifecycle read endpoints."""

import logging
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from ...control._thread_metadata import run_lease_binding, run_lease_id
from ...control._worker_health import worker_liveness
from ...control.action_lease import RUN_NOT_FOUND
from ...control.execution_authority import read_frozen_team_selection_from_fields
from ...control.run_discovery_service import discover_active_runs
from ...control.team_service import build_team_status
from ...control.thread_listing import list_threads_service
from ...control.thread_service import (
    archive_thread,
    delete_thread_service,
)
from ...control.thread_state_service import (
    capture_thread_state,
    derive_run_semantic_context,
    project_semantic_phase,
)
from ...database import (
    Checkpointer,
    get_db,
    get_permission_logs_by_thread,
    resolve_session_factory,
)
from ...providers import ProviderCondition
from ...streaming import RelayHub
from ...thread.constants import (
    MAX_DISCOVERY_RESULTS,
    MAX_FEATURE_TAG_LENGTH,
    MAX_WORKSPACE_ROOT_LENGTH,
)
from ...thread.enums import (
    ApprovalStatus,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ...thread.snapshots import ThreadStateData
from .._replay_writer_seat import replay_writer_seat
from .._stream_replay import run_stream_resumability
from ..dependencies import (
    get_checkpointer,
    get_relay_hub,
)
from ..schemas.gateway import (
    ActiveRunRecord,
    ActiveRunsResponse,
    PathSafeRunId,
    RoleState,
    RunAgentSummary,
    RunArchiveResponse,
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
from ..thread_stream import (
    ThreadStreamRequest,
    build_thread_stream_response,
    offered_resume_cursor,
)
from ..workspace import require_existing_workspace_root
from .gateway import (
    _modern_frozen_disclosure,
    _optional_enum,
)

logger = logging.getLogger("vaultspec_a2a.api.routes.gateway")

# The run-history state is the Layer-1 snapshot itself. The projection steps
# assemble it from durable strings and live dicts, so it is validated on its way
# out: enums resolve, nested blocks take their declared shape, and the declared
# bounds hold, whatever a step assigned.
_THREAD_STATE_ADAPTER = TypeAdapter(ThreadStateData)


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
    limit: int = Query(default=50, ge=1, le=MAX_DISCOVERY_RESULTS)
    offset: int = Query(default=0, ge=0)


__all__ = ["_active_role", "register"]

# ---------------------------------------------------------------------------
# active-run discovery
# ---------------------------------------------------------------------------


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


async def run_status_endpoint(
    run_id: PathSafeRunId,
    request: Request,
    db: AsyncSession = Depends(get_db),
    relay_hub: RelayHub = Depends(get_relay_hub),
    checkpointer: Checkpointer = Depends(get_checkpointer),
) -> RunStatusResponse:
    """Return the authoritative recovery snapshot for a run."""
    capture = await capture_thread_state(
        db, thread_id=run_id, relay_hub=relay_hub, checkpointer=checkpointer
    )
    if capture is None:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)

    snapshot = capture.snapshot
    semantic = derive_run_semantic_context(capture.checkpoint_projection)
    semantic_phase = project_semantic_phase(
        status=snapshot.status,
        next_nodes=snapshot.next_nodes,
        repair_status=snapshot.repair_status,
    )
    modern_frozen = read_frozen_team_selection_from_fields(capture.metadata.fields)
    provenance = capture.metadata.provenance
    lease_binding = run_lease_binding(capture.metadata.fields)

    return RunStatusResponse(
        run_id=snapshot.thread_id,
        continues_run_id=(
            provenance.continues_run_id if provenance is not None else None
        ),
        status=snapshot.status,
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
        proposal_ids=capture.proposal_ids,
        changeset_ids=capture.changeset_ids,
        approval_status=snapshot.approval_status,
        approval_request_id=snapshot.approval_request_id,
        checkpoint_id=snapshot.checkpoint_id,
        last_sequence=snapshot.last_sequence,
        # Read beside the cursor it qualifies: last_sequence says where the
        # run's numbering stood, and this says whether that number is one the
        # stream will honour as a resumption point.
        stream_resumable=await run_stream_resumability(request.app, db, run_id),
        # From the same capture as everything else, so a queue depth is never
        # reported against a moment the run has already left. A run whose turn
        # ended with a continuation waiting is RUNNING with a quiet stream,
        # and this is the only field that distinguishes that from idle.
        queued_messages=snapshot.queued_messages,
        repair_status=snapshot.repair_status,
        execution_readiness=snapshot.execution_readiness,
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
        lease_id=run_lease_id(capture.metadata.fields),
        reservation_id=(
            lease_binding.reservation_id if lease_binding is not None else None
        ),
        # Read from the SAME capture as every other field above - the snapshot
        # computed it once from the capture's checkpoint projection - so a
        # questionnaire cannot be reported against a position the run has since
        # left, nor disagree with the one run-history serves. This is the
        # authoritative disclosure a reloaded client recovers from; the progress
        # relay only ever nudges it to look here.
        pending_clarification=snapshot.pending_clarification,
    )


# ---------------------------------------------------------------------------
# run-stream
# ---------------------------------------------------------------------------


#: Bounds the resumption cursor at the route. A cursor is a run id, a colon
#: and a decimal, so anything longer is not one; refusing to carry it further
#: keeps an unbounded query string out of the stream body's parser.
MAX_RESUME_CURSOR_CHARS = 160


async def run_stream_endpoint(
    run_id: PathSafeRunId,
    request: Request,
    # Function-scoped, unlike every other read here, because this handler
    # RETURNS a body that then runs for as long as the viewer stays attached. A
    # request-scoped session is torn down after the response completes, so each
    # attached viewer held a pooled connection and the read transaction the
    # status lookup opened, for the whole life of its stream: fifteen viewers
    # exhausted the pool and blocked every other database-using request, and the
    # WAL could not be checkpointed while any of them watched. Function scope
    # gives the connection back when this function returns, which is the last
    # moment the stream needs it.
    db: AsyncSession = Depends(get_db, scope="function"),
    relay_hub: RelayHub = Depends(get_relay_hub),
    last_event_id_header: Annotated[
        str | None,
        Header(
            alias="Last-Event-ID",
            max_length=MAX_RESUME_CURSOR_CHARS,
            description=(
                "The SSE id this viewer last received, re-sent to resume after "
                "the frame it names. A conforming client sends this by itself. "
                "'-' asks for the start of whatever window is still retained."
            ),
        ),
    ] = None,
    last_event_id: Annotated[
        str | None,
        Query(
            max_length=MAX_RESUME_CURSOR_CHARS,
            description=(
                "Resumption cursor for callers that cannot set a header; the "
                "browser EventSource constructor is the reason this exists. "
                "The Last-Event-ID header wins when both are supplied."
            ),
        ),
    ] = None,
) -> StreamingResponse:
    """Re-serve the run's bounded, versioned v1 SSE progress frames.

    The public streaming companion to run-status: run-status is the authoritative
    recovery snapshot, this is the droppable live progress relay. A run id is the
    thread id, so this delegates to the same stream builder the internal
    progress stream has always used - one code path, the same versioned
    256 KiB-bounded frames, the same terminal-replay-then-close semantics. Frames
    are non-authoritative by contract: a consumer reconciles run state from
    run-status, never from a relay frame.

    A reconnecting viewer may offer the id it last received, and the retained
    frames after it lead the live stream. Retention does not make those frames
    authoritative either: a replayed frame is the same droppable progress it
    was live.
    """
    return await build_thread_stream_response(
        ThreadStreamRequest(
            thread_id=run_id,
            relay_hub=relay_hub,
            session_factory=resolve_session_factory(request.app.state),
            resume_cursor=offered_resume_cursor(last_event_id_header, last_event_id),
            replay_writer=replay_writer_seat(request.app),
        ),
        db=db,
    )


# ---------------------------------------------------------------------------
# run-history
# ---------------------------------------------------------------------------


# The transcript verdicts that mean a run's record was LOST rather than never
# written. Absence on a run that has not been dispatched is normal and excluded.
_TRANSCRIPT_FAULTS: frozenset[TranscriptAvailability] = frozenset(
    {TranscriptAvailability.MISSING, TranscriptAvailability.UNREADABLE}
)


async def run_history_endpoint(
    run_id: PathSafeRunId,
    db: AsyncSession = Depends(get_db),
    relay_hub: RelayHub = Depends(get_relay_hub),
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
        relay_hub=relay_hub,
        checkpointer=checkpointer,
    )
    if capture is None:
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
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

    # The settled counterpart to the snapshot's PENDING permissions. A gate leaves
    # the pending list as soon as it is answered, and a terminal run expires
    # whatever was still outstanding, so a decision a human actually made was
    # durable in the audit log and readable on no surface at all. This is the wide
    # read - reporting the record is its job.
    decisions = await get_permission_logs_by_thread(db, run_id)

    return RunHistoryResponse(
        run_id=run_id,
        state=_THREAD_STATE_ADAPTER.validate_python(asdict(snapshot)),
        metadata=capture.metadata.provenance,
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
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    if not result.archived:
        raise HTTPException(status_code=409, detail=result.error_detail)
    return RunArchiveResponse(run_id=run_id)


# ---------------------------------------------------------------------------
# team-status
# ---------------------------------------------------------------------------


async def team_status_endpoint(
    request: Request,
    relay_hub: RelayHub = Depends(get_relay_hub),
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
        relay_hub=relay_hub,
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


async def run_delete_endpoint(
    run_id: PathSafeRunId,
    db: AsyncSession = Depends(get_db),
    relay_hub: RelayHub = Depends(get_relay_hub),
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
        raise HTTPException(status_code=404, detail=RUN_NOT_FOUND)
    if result.error_detail is not None:
        raise HTTPException(status_code=409, detail=result.error_detail)
    if result.cleanup_incomplete:
        raise HTTPException(
            status_code=503,
            detail="Run deletion is in progress; retry to complete cleanup.",
        )
    relay_hub.clear_thread_state(run_id)
    # The run's thread is gone, so a progress frame still held for it can
    # never become a row: its insert would reference a thread that no longer
    # exists. Held rather than dropped, it refused this gateway's every later
    # write of that run and offered a deleted run's frames to a resume.
    relay_hub.discard_run_replay(run_id)
    if result.abandoned_kinds:
        body = RunDeleteResponse(
            run_id=run_id,
            abandoned_kinds=list(result.abandoned_kinds),
        )
        return JSONResponse(status_code=200, content=body.model_dump(mode="json"))
    return Response(status_code=204)


def register(router: APIRouter) -> None:
    """Mount the run discovery, state, history, and lifecycle read verbs."""
    router.get(
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
    )(active_runs_endpoint)
    router.get("/runs/{run_id}", response_model=RunStatusResponse)(run_status_endpoint)
    router.get("/runs/{run_id}/stream")(run_stream_endpoint)
    router.get("/runs/{run_id}/history", response_model=RunHistoryResponse)(
        run_history_endpoint
    )
    router.post("/runs/{run_id}/archive", response_model=RunArchiveResponse)(
        run_archive_endpoint
    )
    router.get("/team/status", response_model=TeamStatusV1Response)(
        team_status_endpoint
    )
    router.delete(
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
    )(run_delete_endpoint)
