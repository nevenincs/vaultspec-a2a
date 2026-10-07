"""Run listing: the thread summaries served by the run-list read route.

Each summary joins the durable thread row with its latest checkpoint and any
pending approval, reading every checkpoint in one bounded pass. The posture and
approval it serves are judged by the read-model steps run-status applies, so a
run lists as it reads.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..database import (
    CheckpointRead,
    CheckpointReadStatus,
    actionable_pending_permissions,
    list_threads,
    read_latest_checkpoint,
)
from ..domain_config import domain_config
from ..thread.enums import DegradedReason, RepairStatus, ThreadStatus
from ..thread.snapshots import ThreadStateData, record_repair_posture
from ..utils.coercion import coerce_nonempty_str, decode_json_object
from .projection import (
    clear_permissions_without_checkpoint_truth,
    durable_approval,
    enrich_snapshot_from_execution_state,
    finalize_snapshot_replay_status,
    mark_degraded,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import ThreadModel

__all__ = [
    "list_threads_service",
]


def _parse_thread_summary_metadata(
    raw_json: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Extract display fields from thread_metadata JSON.

    Returns ``(feature_tag, source_branch, callee)``.
    """
    meta = decode_json_object(raw_json)
    if meta is None:
        return None, None, None
    return (
        coerce_nonempty_str(meta.get("feature_tag")),
        coerce_nonempty_str(meta.get("source_branch")),
        coerce_nonempty_str(meta.get("callee")),
    )


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


#: A read the batch budget ran out on: uncertain, never absent.
_UNREAD = CheckpointRead(status=CheckpointReadStatus.TIMEOUT)


async def _bulk_read_checkpoints(
    checkpointer: Any,
    thread_ids: list[str],
    *,
    concurrency: int,
    deadline: float,
) -> dict[str, CheckpointRead]:
    """Read every thread's checkpoint concurrently under one shared deadline.

    Reading each checkpoint in the assembly loop cost one sequential round trip
    per thread, each with its own timeout, so a page of N slow threads took N
    times that timeout and had no overall bound. This issues the reads together,
    caps how many run at once, and bounds the whole batch by a single wall-clock
    budget.

    Every failure is an unreadable read rather than a raised error: a thread
    whose checkpoint could not be read within the budget is reported as
    uncertain, exactly as the sequential path reported a per-thread timeout,
    never as a thread with no checkpoint.
    """
    gate = asyncio.Semaphore(max(1, concurrency))

    async def _one(thread_id: str) -> tuple[str, CheckpointRead]:
        async with gate:
            # No single read may outlast the batch it belongs to.
            return thread_id, await read_latest_checkpoint(
                checkpointer, thread_id, timeout=deadline
            )

    tasks = [asyncio.create_task(_one(tid)) for tid in thread_ids]
    try:
        pairs = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=False), timeout=deadline
        )
    except TimeoutError:
        # The batch budget was exhausted. Every thread that had not resolved is
        # uncertain, not absent; a resolved task keeps its real result.
        results: dict[str, CheckpointRead] = {}
        for task, tid in zip(tasks, thread_ids, strict=True):
            if task.done() and not task.cancelled() and task.exception() is None:
                _, read = task.result()
                results[tid] = read
            else:
                task.cancel()
                results[tid] = _UNREAD
        return results
    return dict(pairs)


async def _judge_run_posture(
    db: AsyncSession,
    thread: ThreadModel,
    probe: CheckpointRead | None,
) -> ThreadStateData:
    """Judge one thread's repair posture and approval as run-status judges them.

    The summary serves only the posture fields of the snapshot, so this applies
    the read-model steps run-status applies, in its order, and nothing else:
    the durable approval, what the checkpoint read says about it, the
    execution-state row, then the replay verdict. ``probe`` is ``None`` when no
    checkpointer was given, and then no claim is made about the checkpoint
    either way.
    """
    snapshot = ThreadStateData(
        thread_id=thread.id, status=ThreadStatus(thread.status), last_sequence=0
    )
    record_repair_posture(snapshot, thread.repair_status)
    snapshot.approval_status, snapshot.approval_request_id = durable_approval(
        await actionable_pending_permissions(db, thread_id=thread.id)
    )
    if probe is None:
        return await enrich_snapshot_from_execution_state(
            db,
            thread=thread,
            snapshot=snapshot,
            checkpoint_present=None,
            checkpoint_id=None,
        )

    checkpoint_present = probe.checkpoint_tuple is not None
    if probe.unreadable:
        mark_degraded(
            snapshot,
            DegradedReason.CHECKPOINT_UNAVAILABLE,
            repair=RepairStatus.CHECKPOINT_UNAVAILABLE,
        )
    if not checkpoint_present:
        clear_permissions_without_checkpoint_truth(snapshot)
    snapshot = await enrich_snapshot_from_execution_state(
        db,
        thread=thread,
        snapshot=snapshot,
        checkpoint_present=checkpoint_present,
        checkpoint_id=probe.checkpoint_id,
    )
    finalize_snapshot_replay_status(
        snapshot,
        checkpoint_loaded=checkpoint_present,
        checkpoint_present=checkpoint_present,
        checkpoint_error=probe.unreadable,
        thread_status=thread.status,
    )
    return snapshot


async def _thread_summary(
    db: AsyncSession,
    thread: ThreadModel,
    probe: CheckpointRead | None,
) -> ThreadSummaryData:
    feature_tag, source_branch, callee = _parse_thread_summary_metadata(
        thread.thread_metadata
    )
    judged = await _judge_run_posture(db, thread, probe)
    return ThreadSummaryData(
        thread_id=thread.id,
        title=thread.title,
        status=thread.status,
        repair_status=judged.repair_status,
        execution_readiness=judged.execution_readiness,
        approval_status=judged.approval_status,
        approval_request_id=judged.approval_request_id,
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
    checkpoint_probes: dict[str, CheckpointRead] = {}
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
            None if checkpointer is None else checkpoint_probes.get(thread.id, _UNREAD),
        )
        for thread in threads
    ]
    return ListThreadsResult(threads=summaries, total=total)
