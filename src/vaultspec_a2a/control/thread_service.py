"""Thread creation and dispatch orchestration service.

Encapsulates the business logic for creating a thread, building the
dispatch payload, and dispatching to the worker.  The route handler
delegates here and retains only request parsing, DB commit, and HTTP
response formatting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..context.metadata import ThreadMetadata, discover_context_refs, generate_nickname
from ..context.preamble import build_context_preamble
from ..control.accepted_input import freeze_accepted_input
from ..control.dispatch import DispatchOutcome, safe_dispatch
from ..control.dispatch_receipts import (
    bind_graph_action_receipt,
    prepare_graph_action_receipt,
)
from ..control.repair_transitions import (
    mark_ingest_applied,
    mark_ingest_requested,
)
from ..database import (
    ThreadStatusElectionOutcome,
    create_control_action,
    create_thread,
    elect_thread_status,
    get_artifacts_by_thread,
    get_pending_permission_requests,
    get_thread,
    get_thread_execution_state,
    list_threads,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ..database.models import RunWriteAuthority, ThreadExecutionStateModel, ThreadModel
from ..domain_config import domain_config
from ..graph.nodes.vault_reader import build_initial_vault_index
from ..ipc.schemas import DispatchRequest, canonical_project_root, to_dispatch_action
from ..team.team_config import load_team_config
from ..thread.creation import requires_dispatch, resolve_autonomous
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import (
    TERMINAL_STATUS_VALUES,
    ApprovalStatus,
    CleanupKind,
    ControlActionType,
    RecoveryCondition,
    RepairStatus,
    ThreadStatus,
)
from ..thread.errors import ConfigError, TeamConfigNotFoundError
from ..thread.executable_graph import freeze_graph_definition
from ..thread.lifecycle_guards import can_archive, can_delete
from ..thread.snapshots import PLAN_APPROVAL_PAUSE_CAUSES, project_checkpoint_tuple
from .cleanup import build_cleanup_manifest, execute_cleanup_manifest
from .permission_options import extract_allowed_option_ids
from .recovery import RecoveryAuthorityLostError, record_recovery_failure
from .repositories import (
    CleanupItemResult,
    advance_deletion_cleanup_item,
    claim_deletion_saga,
    create_deletion_saga,
    finalize_deletion_saga,
)

if TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread.actor_tokens import ActorTokenBundle
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "DeleteResult",
    "ThreadCreationRequest",
    "ThreadCreationResult",
    "ThreadDispatchRuntime",
    "archive_thread",
    "create_and_dispatch_thread",
    "delete_thread_service",
    "list_threads_service",
    "process_metadata",
]

logger = logging.getLogger(__name__)

_PLAN_APPROVAL_PAUSE_CAUSES = PLAN_APPROVAL_PAUSE_CAUSES


def _degrade_stale_execution_state_summary(
    *,
    repair_status: str | None,
    execution_readiness: str | None,
) -> tuple[str | None, str | None]:
    """Fail closed when summary lineage is stale but still readable."""
    if repair_status not in {
        RepairStatus.CHECKPOINT_UNAVAILABLE.value,
        RepairStatus.NEEDS_RECONCILIATION.value,
        RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value,
    }:
        repair_status = RepairStatus.NEEDS_RECONCILIATION.value
    if execution_readiness not in {
        RepairStatus.CHECKPOINT_UNAVAILABLE.value,
        RepairStatus.NEEDS_RECONCILIATION.value,
        RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value,
    }:
        execution_readiness = RepairStatus.NEEDS_RECONCILIATION.value
    return repair_status, execution_readiness


def _parse_thread_summary_metadata(
    raw_json: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Extract display fields from thread_metadata JSON.

    Returns ``(feature_tag, source_branch, callee)``.
    """
    if not raw_json:
        return None, None, None
    try:
        meta = json.loads(raw_json)
        return (
            meta.get("feature_tag") or None,
            meta.get("source_branch") or None,
            meta.get("callee") or None,
        )
    except (json.JSONDecodeError, TypeError):
        return None, None, None


@dataclass(frozen=True, slots=True)
class ThreadSummaryData:
    """Lightweight thread descriptor produced by :func:`list_threads_service`."""

    thread_id: str
    title: str | None
    status: str
    repair_status: str | None
    execution_readiness: str | None
    approval_status: str | None
    approval_request_id: str | None
    team_preset: str | None
    created_at: datetime
    updated_at: datetime
    nickname: str | None
    feature_tag: str | None
    source_branch: str | None
    callee: str | None


@dataclass(frozen=True, slots=True)
class ListThreadsResult:
    """Outcome of :func:`list_threads_service`."""

    threads: list[ThreadSummaryData]
    total: int


@dataclass(frozen=True, slots=True)
class _CheckpointProbe:
    """One thread's checkpoint read result, decoupled from when it was read.

    ``unverified`` is the honest third state between present and absent: the read
    timed out or errored, so the caller must not report the thread as having no
    checkpoint - absence and uncertainty are different, and only the certain
    ones may drive a resumability claim.
    """

    tuple: Any | None = None
    unverified: bool = False


async def _bulk_read_checkpoints(
    checkpointer: Any,
    thread_ids: list[str],
    *,
    concurrency: int,
    deadline: float,
) -> dict[str, _CheckpointProbe]:
    """Read every thread's checkpoint concurrently under one shared deadline.

    Reading each checkpoint in the assembly loop cost one sequential round trip
    per thread, each with its own timeout, so a page of N slow threads took N
    times that timeout and had no overall bound. This issues the reads together,
    caps how many run at once so a large page cannot open one connection per
    thread, and bounds the whole batch by a single wall-clock budget.

    Every failure is a probe marked ``unverified`` rather than a raised error: a
    thread whose checkpoint could not be read within the budget is reported as
    uncertain, exactly as the sequential path reported a per-thread timeout,
    never as a thread with no checkpoint.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _one(thread_id: str) -> tuple[str, _CheckpointProbe]:
        async with semaphore:
            try:
                checkpoint_tuple = await checkpointer.aget_tuple(
                    {"configurable": {"thread_id": thread_id}}
                )
            except Exception:
                logger.warning(
                    "Checkpoint probe failed for thread %s", thread_id, exc_info=True
                )
                return thread_id, _CheckpointProbe(unverified=True)
            return thread_id, _CheckpointProbe(tuple=checkpoint_tuple)

    tasks = [asyncio.create_task(_one(tid)) for tid in thread_ids]
    try:
        pairs = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=False), timeout=deadline
        )
    except TimeoutError:
        # The batch budget was exhausted. Every thread that had not resolved is
        # uncertain, not absent; a resolved task keeps its real result.
        results: dict[str, _CheckpointProbe] = {}
        for task, tid in zip(tasks, thread_ids, strict=True):
            if task.done() and not task.cancelled() and task.exception() is None:
                _, probe = task.result()
                results[tid] = probe
            else:
                task.cancel()
                results[tid] = _CheckpointProbe(unverified=True)
        return results
    return dict(pairs)


def _summary_checkpoint_state(
    thread: ThreadModel,
    execution_state: ThreadExecutionStateModel | None,
    probe: _CheckpointProbe,
    *,
    checkpointer_active: bool,
) -> tuple[str | None, str | None, bool]:
    repair_status = thread.repair_status
    execution_readiness = thread.execution_readiness
    checkpoint_unverified = checkpointer_active and probe.unverified
    checkpoint_id: str | None = None
    if checkpointer_active and probe.tuple is not None:
        checkpoint_id = project_checkpoint_tuple(
            probe.tuple, thread_id=thread.id
        ).checkpoint_id
    if checkpoint_unverified:
        repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value
        execution_readiness = RepairStatus.CHECKPOINT_UNAVAILABLE.value
    if execution_state is not None and (
        execution_state.recovery_epoch != thread.recovery_epoch
        or (
            checkpointer_active
            and probe.tuple is not None
            and checkpoint_id is not None
            and execution_state.checkpoint_id != checkpoint_id
        )
    ):
        repair_status, execution_readiness = _degrade_stale_execution_state_summary(
            repair_status=repair_status,
            execution_readiness=execution_readiness,
        )
    return repair_status, execution_readiness, checkpoint_unverified


async def _summary_approval(
    db: AsyncSession, thread: ThreadModel, *, checkpoint_unverified: bool
) -> tuple[str | None, str | None]:
    if thread.status in TERMINAL_STATUS_VALUES or checkpoint_unverified:
        return None, None
    live_plan_permissions = [
        permission
        for permission in await get_pending_permission_requests(
            db,
            thread_id=thread.id,
            include_answered_pending_apply=False,
        )
        if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES
    ]
    if not live_plan_permissions:
        return None, None
    live_permission = live_plan_permissions[-1]
    if not extract_allowed_option_ids(live_permission.allowed_options_json):
        return None, None
    return ApprovalStatus.PENDING.value, live_permission.request_id


async def _thread_summary(
    db: AsyncSession,
    thread: ThreadModel,
    probe: _CheckpointProbe,
    *,
    checkpointer_active: bool,
) -> ThreadSummaryData:
    feature_tag, source_branch, callee = _parse_thread_summary_metadata(
        thread.thread_metadata
    )
    execution_state = await get_thread_execution_state(db, thread.id)
    repair_status, execution_readiness, checkpoint_unverified = (
        _summary_checkpoint_state(
            thread, execution_state, probe, checkpointer_active=checkpointer_active
        )
    )
    approval_status, approval_request_id = await _summary_approval(
        db, thread, checkpoint_unverified=checkpoint_unverified
    )
    return ThreadSummaryData(
        thread_id=thread.id,
        title=thread.title,
        status=thread.status,
        repair_status=repair_status,
        execution_readiness=execution_readiness,
        approval_status=approval_status,
        approval_request_id=approval_request_id,
        team_preset=thread.team_preset,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        nickname=thread.nickname,
        feature_tag=feature_tag,
        source_branch=source_branch,
        callee=callee,
    )


async def list_threads_service(
    db: AsyncSession,
    *,
    status_filter: ThreadStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    checkpointer: Any | None = None,
) -> ListThreadsResult:
    """Query threads and assemble summary data with parsed metadata.

    Threads under deletion are hidden from this product listing; they are a
    cross-store cleanup subject, not a run, and remain visible only to the
    cleanup coordinator.
    """
    threads, total = await list_threads(
        db,
        offset=offset,
        limit=limit,
        status=status_filter,
        include_deleting=False,
    )
    checkpoint_probes: dict[str, _CheckpointProbe] = {}
    if checkpointer is not None and threads:
        checkpoint_probes = await _bulk_read_checkpoints(
            checkpointer,
            [t.id for t in threads],
            concurrency=domain_config.thread_list_checkpoint_concurrency,
            deadline=domain_config.thread_list_checkpoint_deadline_seconds,
        )
    summaries = [
        await _thread_summary(
            db,
            thread,
            checkpoint_probes.get(
                thread.id, _CheckpointProbe(unverified=checkpointer is not None)
            ),
            checkpointer_active=checkpointer is not None,
        )
        for thread in threads
    ]
    return ListThreadsResult(threads=summaries, total=total)


@dataclass(frozen=True, slots=True)
class ThreadCreationRequest:
    """Bundled request fields for :func:`create_and_dispatch_thread`."""

    thread_id: str
    title: str | None
    initial_message: str | None
    team_preset: str | None
    autonomous: bool | None
    nickname: str | None
    metadata: ThreadMetadata | None
    metadata_json: str | None
    # The minted active project, as :func:`process_metadata` returned it. Not
    # optional: admission is where the project becomes real, so a creation
    # request that names none is not a run this service can site.
    workspace_root: Path
    actor_tokens: ActorTokenBundle | None = None
    # The exact served selection frozen at admission and threaded to the worker.
    model_assignment: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ThreadCreationResult:
    """Outcome of :func:`create_and_dispatch_thread`."""

    thread_id: str
    status: str
    nickname: str | None
    dispatched: bool
    error_detail: str | None
    failure_type: FailureType | None = None


@dataclass(frozen=True, slots=True)
class ThreadDispatchRuntime:
    circuit_breaker: WorkerCircuitBreaker
    worker_spawner: LazyWorkerSpawner
    worker_client: httpx.AsyncClient
    recursion_limit: int
    trace_headers: dict[str, str] | None


@dataclass(frozen=True, slots=True)
class _CreationDispatchContext:
    request: ThreadCreationRequest
    thread: ThreadModel
    action_receipt_id: str
    recovery_deadline_at: datetime


def process_metadata(
    metadata: ThreadMetadata | None,
    thread_id: str,
    team_preset: str | None,
) -> tuple[Path, str, str]:
    """Validate and enrich thread metadata.

    Returns ``(workspace_root, nickname, metadata_json)``.

    This is the admission seam for the active project. Every run that becomes
    durable passes through here, so the requirement is enforced once, at the
    point a run is created, rather than left to the layers below - where the
    absence used to resolve into whatever directory the worker happened to be
    started in, siting agent subprocesses and their filesystem sandboxes in this
    service's own tree.

    It is also where the project is MINTED. The caller's spelling is turned into
    the run's canonical one exactly once here, and written back into the
    envelope before it is serialised, so the durable record and the run's first
    dispatch carry the same string. Every later dispatch - follow-up,
    clarification response, verdict resume, crash recovery - reads the project
    back out of that record, so all of them now name the run's project in the
    spelling it was admitted with instead of re-deriving one of their own.

    The durable discovery selector is unaffected: it hashes a case-folded
    symlink resolution of this value, and that resolution is idempotent, so an
    already-minted root hashes to the key the caller's raw spelling always
    produced and existing rows keep matching.

    Raises:
        ValueError: If the metadata envelope is absent, if its
            ``workspace_root`` is blank or relative, or if it is not an existing
            directory.
    """
    if metadata is None:
        msg = (
            "run requires an active project: metadata.workspace_root is missing. "
            "The active project is supplied by the caller that owns it and is "
            "never inferred from the serving process."
        )
        raise ValueError(msg)

    import pathlib

    ws_root = pathlib.Path(canonical_project_root(metadata.workspace_root))
    if not ws_root.is_dir():
        msg = (
            f"workspace_root is not an existing directory: {metadata.workspace_root!r}"
        )
        raise ValueError(msg)
    metadata.workspace_root = str(ws_root)

    if metadata.feature_tag and not metadata.context_refs:
        metadata.context_refs = discover_context_refs(ws_root, metadata.feature_tag)

    topology = "default"
    if team_preset:
        with contextlib.suppress(ConfigError, TeamConfigNotFoundError):
            tc = load_team_config(team_preset, workspace_root=ws_root)
            topology = tc.topology.type
    nickname = metadata.nickname or generate_nickname(
        metadata.feature_tag, topology, thread_id
    )
    metadata.nickname = nickname

    return ws_root, nickname, metadata.model_dump_json()


def _initial_dispatch(
    req: ThreadCreationRequest, *, dispatch_id: str, recursion_limit: int
) -> DispatchRequest:
    """Resolve the accepted graph input before acquiring a database write lock."""
    context_preamble: str | None = None
    if req.metadata is not None:
        preamble_msg = build_context_preamble(req.metadata)
        context_preamble = (
            preamble_msg.content
            if isinstance(preamble_msg.content, str)
            else str(preamble_msg.content)
        )
    if req.team_preset is None:
        raise ValueError("initial graph admission requires an explicit preset")
    team_config = load_team_config(req.team_preset, workspace_root=req.workspace_root)
    graph_definition = freeze_graph_definition(
        team_config, workspace_root=req.workspace_root
    )
    feature_tag = req.metadata.feature_tag if req.metadata else None
    return DispatchRequest(
        dispatch_id=dispatch_id,
        graph_definition=graph_definition,
        action=to_dispatch_action(ControlActionType.INGEST),
        thread_id=req.thread_id,
        team_preset=req.team_preset,
        workspace_root=str(req.workspace_root),
        autonomous=resolve_autonomous(req.autonomous, team_config),
        metadata_json=req.metadata_json,
        content=req.initial_message,
        context_preamble=context_preamble,
        recursion_limit=recursion_limit,
        active_feature=feature_tag,
        feedback_batch_id=(
            (req.metadata.feedback_batch_id or None) if req.metadata else None
        ),
        pipeline_phase=None,
        vault_index=(
            build_initial_vault_index(req.workspace_root, req.metadata.feature_tag)
            if (req.metadata and req.metadata.feature_tag)
            else {}
        ),
        validation_errors=[],
        actor_tokens=req.actor_tokens,
        model_assignment=req.model_assignment,
    )


async def _failed_initial_dispatch(
    db: AsyncSession, context: _CreationDispatchContext, outcome: DispatchOutcome
) -> ThreadCreationResult:
    req = context.request
    thread = context.thread
    action_receipt_id = context.action_receipt_id
    recovery_deadline_at = context.recovery_deadline_at
    _policy, typed_failure = evaluate_dispatch_failure(outcome.failure_type)
    if typed_failure is None:
        raise RuntimeError("failed initial dispatch carries no failure type")
    observed_at = datetime.now(UTC)
    # A checkpoint or another accepted action may win while dispatch is in
    # flight. Its exact authority decides the result, so discard stale work.
    with suppress(RecoveryAuthorityLostError):
        await record_recovery_failure(
            db,
            thread_id=thread.id,
            authority=thread_write_expectation(thread).authority,
            condition=RecoveryCondition(typed_failure.value),
            observed_at=observed_at,
            next_eligible_at=min(
                observed_at + timedelta(seconds=2), recovery_deadline_at
            ),
            deadline_at=recovery_deadline_at,
            detail=outcome.detail,
        )
    await db.commit()
    current_thread = await db.get(ThreadModel, thread.id, populate_existing=True)
    if current_thread is None:
        return ThreadCreationResult(
            thread_id=thread.id,
            status="",
            nickname=req.nickname,
            dispatched=False,
            error_detail="Thread disappeared while initial dispatch settled",
            failure_type=FailureType.NOT_FOUND,
        )
    if (
        current_thread.writer_action_type == ControlActionType.INGEST.value
        and current_thread.writer_action_receipt_id == action_receipt_id
        and current_thread.status
        in {ThreadStatus.COMPLETED.value, ThreadStatus.FAILED.value}
    ):
        return ThreadCreationResult(
            thread_id=thread.id,
            status=current_thread.status,
            nickname=req.nickname,
            dispatched=True,
            error_detail=None,
            failure_type=None,
        )
    return ThreadCreationResult(
        thread_id=thread.id,
        status=current_thread.status,
        nickname=req.nickname,
        dispatched=False,
        error_detail=outcome.detail,
        failure_type=typed_failure,
    )


async def create_and_dispatch_thread(
    db: AsyncSession,
    req: ThreadCreationRequest,
    *,
    runtime: ThreadDispatchRuntime,
) -> ThreadCreationResult:
    """Create a thread row, build dispatch payload, and dispatch to worker.

    Durably reserves the thread id before any external worker dispatch, then
    commits final dispatch state before returning. The service owns both
    transaction boundaries. Does **not** raise ``HTTPException`` — returns
    a result that the caller translates into HTTP status codes.

    Raises:
        NicknameConflictError: If the requested nickname is already taken.
    """
    action_receipt_id = uuid4().hex
    if not req.thread_id.strip():
        raise ValueError("run admission requires an allocated thread identity")
    dispatch = (
        _initial_dispatch(
            req, dispatch_id=action_receipt_id, recursion_limit=runtime.recursion_limit
        )
        if requires_dispatch(req.team_preset)
        else None
    )
    accepted_input = (
        freeze_accepted_input(dispatch, intent={"initial_message": req.initial_message})
        if dispatch is not None
        else None
    )
    thread = await create_thread(
        db,
        write_authority=RunWriteAuthority(
            run_revision=0,
            writer_generation=1,
            action_type=ControlActionType.INGEST,
            action_receipt_id=action_receipt_id,
        ),
        title=req.title,
        status=ThreadStatus.SUBMITTED,
        metadata=req.metadata_json,
        nickname=req.nickname,
        thread_id=req.thread_id,
        team_preset=req.team_preset,
    )

    logger.info(
        "Created thread %s (title=%s, preset=%s, nickname=%s)",
        thread.id,
        req.title,
        req.team_preset,
        req.nickname,
        extra={
            "thread_id": thread.id,
            "action": "create_thread",
            "team_preset": req.team_preset,
            "thread_title": req.title,
            "thread_nickname": req.nickname,
        },
    )

    if dispatch is None:
        await create_control_action(
            db,
            thread_id=thread.id,
            action_type=ControlActionType.INGEST,
            dispatch_id=action_receipt_id,
            idempotency_key=f"thread-create:{thread.id}",
            payload={"dispatch_required": False},
        )
        await mark_ingest_requested(db, thread.id)
        await db.commit()
        return ThreadCreationResult(
            thread_id=thread.id,
            status=thread.status,
            nickname=req.nickname,
            dispatched=False,
            error_detail=None,
        )

    # Durable acceptance includes the actual graph input. Recovery cannot
    # reconstruct a user's message from title/preset metadata after a crash.
    # Tokens remain ephemeral; their required presence is an explicit fact.
    recovery_deadline_at = datetime.now(UTC) + timedelta(
        seconds=dispatch.require_graph_definition().run_timeout_seconds
    )
    await create_control_action(
        db,
        thread_id=thread.id,
        action_type=ControlActionType.INGEST,
        dispatch_id=action_receipt_id,
        idempotency_key=f"thread-create:{thread.id}",
        payload=accepted_input,
        recovery_deadline_at=recovery_deadline_at,
    )
    await mark_ingest_requested(db, thread.id)
    receipt = await prepare_graph_action_receipt(
        db,
        thread_id=thread.id,
        dispatch_id=action_receipt_id,
    )
    if receipt is None:
        await db.rollback()
        raise ValueError("initial action could not establish graph receipt authority")
    await db.commit()

    logger.info(
        "Dispatching ingest dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread.id,
        extra={
            "thread_id": thread.id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
            "team_preset": dispatch.team_preset,
            "autonomous": dispatch.autonomous,
        },
    )

    dispatch = await bind_graph_action_receipt(db, dispatch)
    # -- Dispatch via safe_dispatch (non-raising) ------------------------------
    outcome = await safe_dispatch(
        runtime.worker_client,
        dispatch,
        runtime.circuit_breaker,
        runtime.worker_spawner,
        trace_headers=runtime.trace_headers,
    )

    if not outcome.success:
        return await _failed_initial_dispatch(
            db,
            _CreationDispatchContext(
                req, thread, action_receipt_id, recovery_deadline_at
            ),
            outcome,
        )

    # -- Success ---------------------------------------------------------------
    expectation = thread_write_expectation(thread)
    election = await elect_thread_status(
        db,
        thread.id,
        expectation=expectation,
        status=ThreadStatus.RUNNING,
        successor=successor_thread_write_authority(
            expectation,
            action_type=ControlActionType.INGEST,
            action_receipt_id=action_receipt_id,
        ),
    )
    if election.outcome is ThreadStatusElectionOutcome.WON:
        await mark_ingest_applied(db, thread.id)
    await db.commit()
    current_thread = await db.get(ThreadModel, thread.id, populate_existing=True)
    if current_thread is None:
        return ThreadCreationResult(
            thread_id=thread.id,
            status="",
            nickname=req.nickname,
            dispatched=True,
            error_detail="Thread disappeared while initial dispatch settled",
            failure_type=FailureType.NOT_FOUND,
        )
    if election.outcome is ThreadStatusElectionOutcome.RECEIPT_MISMATCH:
        return ThreadCreationResult(
            thread_id=thread.id,
            status=current_thread.status,
            nickname=req.nickname,
            dispatched=True,
            error_detail="Initial dispatch receipt no longer matches its action",
            failure_type=FailureType.INCOMPATIBLE_STATE,
        )

    return ThreadCreationResult(
        thread_id=thread.id,
        status=current_thread.status,
        nickname=req.nickname,
        dispatched=True,
        error_detail=None,
    )


# ---------------------------------------------------------------------------
# Delete thread service
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeleteResult:
    """Outcome of :func:`delete_thread_service`.

    ``deleted`` is true only when the saga finalized and every control row is
    gone. ``cleanup_incomplete`` means the deletion started durably but has not
    finished - either a cleanup item did not complete, or another pass holds the
    saga - so the thread stays hidden and the saga is resumable on retry.
    ``abandoned_kinds`` names the kinds of state a finalized delete left behind:
    it is non-empty exactly when the delete finalized over at least one cleanup
    item judged permanently unremovable. The kinds are carried rather than
    flattened to a flag because a caller reporting the outcome has to say *what*
    was stranded, and the per-item detail behind it - a checkpoint id, an
    artifact path - stays in the log and never leaves the control plane.
    ``error_detail`` carries a lifecycle-guard refusal reason when the delete was
    refused before it began.
    """

    deleted: bool
    not_found: bool = False
    error_detail: str | None = None
    cleanup_incomplete: bool = False
    abandoned_kinds: tuple[CleanupKind, ...] = ()


async def delete_thread_service(
    db: AsyncSession,
    thread_id: str,
    *,
    checkpointer: Any | None = None,
) -> DeleteResult:
    """Delete a thread through the durable cross-store deletion saga.

    Replaces irreversible hard deletion with a resumable saga. A fresh delete
    captures the cleanup manifest and marks the thread ``deleting`` in one
    durable commit before any external effect; a replayed or resumed request on
    an already-``deleting`` thread rejoins the same saga. Cleanup then removes
    the checkpoint and artifact files from the durable manifest, and the control
    rows are removed only once every item is done.

    Commits the session at each durable boundary — the service owns its
    transaction boundaries. Does **not** raise ``HTTPException``.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return DeleteResult(deleted=False, not_found=True)

    if thread.status != ThreadStatus.DELETING.value:
        eligibility = can_delete(thread.status)
        if not eligibility.allowed:
            return DeleteResult(deleted=False, error_detail=eligibility.reason)
        manifest = build_cleanup_manifest(
            thread,
            await get_artifacts_by_thread(db, thread_id),
            include_checkpoint=checkpointer is not None,
        )
        saga = await create_deletion_saga(
            db,
            thread_id=thread_id,
            manifest=manifest,
        )
        if saga is None:
            current_thread = await db.get(
                ThreadModel, thread_id, populate_existing=True
            )
            if current_thread is None:
                return DeleteResult(deleted=False, not_found=True)
            if current_thread.status != ThreadStatus.DELETING.value:
                return DeleteResult(
                    deleted=False,
                    error_detail="Thread state changed before deletion could begin",
                )
        await db.commit()

    return await _run_deletion_saga(db, thread_id, checkpointer=checkpointer)


async def _run_deletion_saga(
    db: AsyncSession,
    thread_id: str,
    *,
    checkpointer: Any | None,
) -> DeleteResult:
    """Claim, drive, and finalize the deletion saga for one thread.

    Idempotent by construction: already-done cleanup items are skipped, and a
    saga that another pass finalized between reads reports a completed delete.

    Only the pass that wins the claim drives the manifest. A concurrent request
    that finds the saga owned reports the delete as still in progress rather
    than executing a second pass over a result snapshot taken before the owner's
    progress was recorded.
    """
    saga = await claim_deletion_saga(db, thread_id=thread_id)
    await db.commit()
    if saga is None:
        # The saga was finalized between the status read and the claim; the
        # thread is already fully deleted.
        return DeleteResult(deleted=True)
    if not saga.owned:
        return DeleteResult(deleted=False, cleanup_incomplete=True)

    async def _advance(result: CleanupItemResult) -> None:
        await advance_deletion_cleanup_item(db, thread_id=thread_id, result=result)
        await db.commit()

    await execute_cleanup_manifest(
        saga.manifest,
        saga.results,
        checkpointer=checkpointer,
        advance=_advance,
    )

    outcome = await finalize_deletion_saga(db, thread_id=thread_id)
    await db.commit()
    if outcome.finalized:
        return DeleteResult(deleted=True, abandoned_kinds=outcome.abandoned_kinds)
    return DeleteResult(deleted=False, cleanup_incomplete=True)


# ---------------------------------------------------------------------------
# Archive thread service
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    """Outcome of :func:`archive_thread`."""

    archived: bool
    already_archived: bool = False
    not_found: bool = False
    error_detail: str | None = None


async def _archive_election_failure(db: AsyncSession, thread_id: str) -> ArchiveResult:
    await db.rollback()
    current_thread = await db.get(ThreadModel, thread_id, populate_existing=True)
    if current_thread is None:
        return ArchiveResult(archived=False, not_found=True)
    refreshed = can_archive(current_thread.status)
    if refreshed.already_archived:
        return ArchiveResult(archived=True, already_archived=True)
    return ArchiveResult(
        archived=False,
        error_detail=(
            refreshed.reason or "Thread authority changed during archive election"
        ),
    )


async def archive_thread(db: AsyncSession, thread_id: str) -> ArchiveResult:
    """Transition a thread to ARCHIVED status after lifecycle-guard validation.

    Commits the session before returning — the service owns its
    transaction boundary.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return ArchiveResult(archived=False, not_found=True)

    eligibility = can_archive(thread.status)
    if eligibility.already_archived:
        return ArchiveResult(archived=True, already_archived=True)
    if not eligibility.allowed:
        return ArchiveResult(archived=False, error_detail=eligibility.reason)

    expectation = thread_write_expectation(thread)
    election = await elect_thread_status(
        db,
        thread_id,
        expectation=expectation,
        status=ThreadStatus.ARCHIVED,
        successor=successor_thread_write_authority(
            expectation,
            action_type=expectation.authority.action_type,
            action_receipt_id=expectation.authority.action_receipt_id,
        ),
    )
    if election.outcome is not ThreadStatusElectionOutcome.WON:
        return await _archive_election_failure(db, thread_id)
    await db.commit()
    return ArchiveResult(archived=True)
