"""Run listing: the thread summaries served by the run-list read route.

Each summary joins the durable thread row with its latest checkpoint and any
pending approval, reading every checkpoint in one bounded pass.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..database import (
    get_pending_permission_requests,
    get_thread_execution_state,
    list_threads,
)
from ..domain_config import domain_config
from ..thread.enums import (
    TERMINAL_STATUS_VALUES,
    ApprovalStatus,
    RepairStatus,
    ThreadStatus,
)
from ..thread.snapshots import PLAN_APPROVAL_PAUSE_CAUSES, project_checkpoint_tuple
from .permission_options import extract_allowed_option_ids

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import ThreadExecutionStateModel, ThreadModel

__all__ = [
    "ListThreadsResult",
    "ThreadSummaryData",
    "list_threads_service",
]

# The listing moved out of the thread service; its records keep that name.
logger = logging.getLogger("vaultspec_a2a.control.thread_service")

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
# Flat read-model fields match the thread-list response contract.
class ThreadSummaryData:  # pylint: disable=too-many-instance-attributes
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
            checkpoint_id is not None and execution_state.checkpoint_id != checkpoint_id
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
