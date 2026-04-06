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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..context.metadata import ThreadMetadata, discover_context_refs, generate_nickname
from ..context.preamble import build_context_preamble
from ..control.dispatch import safe_dispatch
from ..control.repair_transitions import (
    mark_dispatch_failed,
    mark_ingest_applied,
    mark_ingest_requested,
)
from ..database import (
    create_control_action,
    create_thread,
    delete_thread,
    get_pending_permission_requests,
    get_thread,
    get_thread_execution_state,
    list_threads,
    update_thread_status,
)
from ..graph.compiler import build_initial_vault_index
from ..ipc.schemas import DispatchRequest
from ..team.team_config import load_team_config
from ..thread.creation import requires_dispatch, resolve_autonomous
from ..thread.dispatch_policy import FailureType, classify_dispatch_failure
from ..thread.enums import (
    TERMINAL_STATUSES,
    ApprovalStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
)
from ..thread.errors import ConfigError, TeamConfigNotFoundError
from ..thread.lifecycle_guards import can_archive, can_delete
from ..thread.snapshots import PLAN_APPROVAL_PAUSE_CAUSES, project_checkpoint_tuple
from .permission_options import extract_allowed_option_ids

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = [
    "ArchiveResult",
    "DeleteResult",
    "ListThreadsResult",
    "ThreadCreationRequest",
    "ThreadCreationResult",
    "ThreadSummaryData",
    "archive_thread",
    "create_and_dispatch_thread",
    "delete_thread_service",
    "generate_thread_id",
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


def generate_thread_id() -> str:
    """Generate a unique hex thread identifier."""
    return uuid4().hex


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


async def list_threads_service(
    db: AsyncSession,
    *,
    status_filter: ThreadStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    checkpointer: Any | None = None,
) -> ListThreadsResult:
    """Query threads and assemble summary data with parsed metadata."""
    threads, total = await list_threads(
        db, offset=offset, limit=limit, status=status_filter
    )
    summaries: list[ThreadSummaryData] = []
    for t in threads:
        feature_tag, source_branch, callee = _parse_thread_summary_metadata(
            t.thread_metadata
        )
        repair_status = t.repair_status
        execution_readiness = t.execution_readiness
        approval_status = t.approval_status
        approval_request_id = t.approval_request_id
        is_terminal_thread = t.status in {status.value for status in TERMINAL_STATUSES}
        execution_state = await get_thread_execution_state(db, t.id)
        checkpoint_id: str | None = None
        checkpoint_present = False
        checkpoint_unverified = False
        if checkpointer is not None:
            try:
                checkpoint_tuple = await asyncio.wait_for(
                    checkpointer.aget_tuple({"configurable": {"thread_id": t.id}}),
                    timeout=2.0,
                )
                if checkpoint_tuple is not None:
                    checkpoint_present = True
                    checkpoint_id = project_checkpoint_tuple(
                        checkpoint_tuple,
                        thread_id=t.id,
                    ).checkpoint_id
            except TimeoutError:
                checkpoint_unverified = True
            except Exception:
                logger.warning(
                    "Checkpoint probe failed for thread %s",
                    t.id,
                    exc_info=True,
                )
                checkpoint_unverified = True
        if checkpoint_unverified:
            repair_status = RepairStatus.CHECKPOINT_UNAVAILABLE.value
            execution_readiness = RepairStatus.CHECKPOINT_UNAVAILABLE.value
            # Checkpoint state is LangGraph's resumability authority. If the
            # probe itself is unverified, the summary surface must not expose a
            # still-actionable approval target.
            approval_status = None
            approval_request_id = None
        if execution_state is not None and (
            execution_state.recovery_epoch != t.recovery_epoch
            or (
                checkpoint_present
                and checkpoint_id is not None
                and execution_state.checkpoint_id != checkpoint_id
            )
        ):
            repair_status, execution_readiness = _degrade_stale_execution_state_summary(
                repair_status=repair_status,
                execution_readiness=execution_readiness,
            )
        if is_terminal_thread or checkpoint_unverified:
            approval_status = None
            approval_request_id = None
        else:
            live_plan_permissions = [
                permission
                for permission in await get_pending_permission_requests(
                    db,
                    thread_id=t.id,
                    include_answered_pending_apply=False,
                )
                if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES
            ]
            if live_plan_permissions:
                live_permission = live_plan_permissions[-1]
                if not extract_allowed_option_ids(live_permission.allowed_options_json):
                    approval_status = None
                    approval_request_id = None
                else:
                    approval_status = ApprovalStatus.PENDING.value
                    approval_request_id = live_permission.request_id
            else:
                approval_status = None
                approval_request_id = None
        summaries.append(
            ThreadSummaryData(
                thread_id=t.id,
                title=t.title,
                status=t.status,
                repair_status=repair_status,
                execution_readiness=execution_readiness,
                approval_status=approval_status,
                approval_request_id=approval_request_id,
                team_preset=t.team_preset,
                created_at=t.created_at,
                updated_at=t.updated_at,
                nickname=t.nickname,
                feature_tag=feature_tag,
                source_branch=source_branch,
                callee=callee,
            )
        )
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
    workspace_root: Path | None


@dataclass(frozen=True, slots=True)
class ThreadCreationResult:
    """Outcome of :func:`create_and_dispatch_thread`."""

    thread_id: str
    status: str
    nickname: str | None
    dispatched: bool
    error_detail: str | None
    failure_type: FailureType | None = None


def process_metadata(
    metadata: ThreadMetadata | None,
    thread_id: str,
    team_preset: str | None,
) -> tuple[Path | None, str | None, str | None]:
    """Validate and enrich thread metadata (ADR-014).

    Returns ``(workspace_root, nickname, metadata_json)``.

    Raises:
        ValueError: If ``workspace_root`` is not an existing directory.
    """
    if metadata is None:
        return None, None, None

    import pathlib

    ws_root = pathlib.Path(metadata.workspace_root).resolve()
    if not ws_root.is_dir():
        msg = (
            f"workspace_root is not an existing directory: {metadata.workspace_root!r}"
        )
        raise ValueError(msg)

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


async def create_and_dispatch_thread(
    db: AsyncSession,
    req: ThreadCreationRequest,
    *,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None,
) -> ThreadCreationResult:
    """Create a thread row, build dispatch payload, and dispatch to worker.

    Commits the session before returning — the service owns its
    transaction boundary.  Does **not** raise ``HTTPException`` — returns
    a result that the caller translates into HTTP status codes.

    Raises:
        NicknameConflictError: If the requested nickname is already taken.
    """
    thread = await create_thread(
        db,
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

    await create_control_action(
        db,
        thread_id=thread.id,
        action_type=ControlActionType.INGEST,
        idempotency_key=f"thread-create:{thread.id}",
        payload={
            "title": req.title,
            "team_preset": req.team_preset,
            "autonomous": req.autonomous,
        },
    )
    await mark_ingest_requested(db, thread.id)

    if not requires_dispatch(req.team_preset):
        await db.commit()
        return ThreadCreationResult(
            thread_id=thread.id,
            status=thread.status,
            nickname=req.nickname,
            dispatched=False,
            error_detail=None,
        )

    # -- Build context preamble ------------------------------------------------
    context_preamble: str | None = None
    if req.metadata is not None:
        preamble_msg = build_context_preamble(req.metadata)
        context_preamble = (
            preamble_msg.content
            if isinstance(preamble_msg.content, str)
            else str(preamble_msg.content)
        )

    # -- Resolve autonomous flag -----------------------------------------------
    team_config = None
    if req.team_preset:
        with contextlib.suppress(ConfigError, TeamConfigNotFoundError):
            team_config = load_team_config(
                req.team_preset, workspace_root=req.workspace_root
            )
    effective_autonomous = resolve_autonomous(req.autonomous, team_config)

    # -- Build vault index -----------------------------------------------------
    feature_tag = req.metadata.feature_tag if req.metadata else None
    vault_index = (
        build_initial_vault_index(req.workspace_root, req.metadata.feature_tag)
        if (req.metadata and req.metadata.feature_tag)
        else {}
    )

    # -- Construct dispatch request --------------------------------------------
    dispatch = DispatchRequest(
        action=ControlActionType.INGEST,  # ty: ignore[invalid-argument-type]
        thread_id=thread.id,
        team_preset=req.team_preset,
        workspace_root=str(req.workspace_root) if req.workspace_root else None,
        autonomous=effective_autonomous,
        metadata_json=req.metadata_json,
        content=req.initial_message,
        context_preamble=context_preamble,
        recursion_limit=recursion_limit,
        active_feature=feature_tag,
        pipeline_phase=None,
        vault_index=vault_index,
        validation_errors=[],
    )

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

    # -- Dispatch via safe_dispatch (non-raising) ------------------------------
    outcome = await safe_dispatch(
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        trace_headers=trace_headers,
    )

    if not outcome.success:
        policy = classify_dispatch_failure(outcome.failure_type)
        typed_failure = (
            FailureType(outcome.failure_type) if outcome.failure_type else None
        )
        if policy.should_mark_failed:
            await update_thread_status(db, thread.id, ThreadStatus.FAILED)
            await mark_dispatch_failed(db, thread.id)
        await db.commit()
        return ThreadCreationResult(
            thread_id=thread.id,
            status=(
                ThreadStatus.FAILED.value
                if policy.should_mark_failed
                else thread.status
            ),
            nickname=req.nickname,
            dispatched=False,
            error_detail=outcome.detail,
            failure_type=typed_failure,
        )

    # -- Success ---------------------------------------------------------------
    await update_thread_status(db, thread.id, ThreadStatus.RUNNING)
    await mark_ingest_applied(db, thread.id)
    await db.commit()

    return ThreadCreationResult(
        thread_id=thread.id,
        status=ThreadStatus.RUNNING.value,
        nickname=req.nickname,
        dispatched=True,
        error_detail=None,
    )


# ---------------------------------------------------------------------------
# Delete thread service
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeleteResult:
    """Outcome of :func:`delete_thread_service`."""

    deleted: bool
    not_found: bool = False
    error_detail: str | None = None


async def delete_thread_service(
    db: AsyncSession,
    thread_id: str,
    *,
    checkpointer: Any | None = None,
) -> DeleteResult:
    """Hard-delete a thread after lifecycle-guard validation.

    Commits the session before returning — the service owns its
    transaction boundary.
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return DeleteResult(deleted=False, not_found=True)

    eligibility = can_delete(thread.status)
    if not eligibility.allowed:
        return DeleteResult(deleted=False, error_detail=eligibility.reason)

    deleted = await delete_thread(db, thread_id)
    if not deleted:
        return DeleteResult(deleted=False, not_found=True)

    if checkpointer is not None:
        await checkpointer.adelete_thread(thread_id)

    await db.commit()
    return DeleteResult(deleted=True)


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

    await update_thread_status(db, thread_id, ThreadStatus.ARCHIVED)
    await db.commit()
    return ArchiveResult(archived=True)
