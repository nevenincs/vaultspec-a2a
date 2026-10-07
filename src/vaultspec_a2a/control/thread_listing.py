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
    actionable_pending_permissions,
    get_thread_execution_state,
    list_threads,
    read_latest_checkpoint,
)
from ..domain_config import domain_config
from ..thread.enums import TERMINAL_STATUS_VALUES, RepairStatus, ThreadStatus
from ..thread.snapshots import project_checkpoint_tuple
from .projection import (
    durable_approval,
    escalate_repair_posture,
    execution_state_is_stale,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import ThreadExecutionStateModel, ThreadModel

__all__ = [
    "list_threads_service",
]

# The listing moved out of the thread service; its records keep that name.
logger = logging.getLogger("vaultspec_a2a.control.thread_service")


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

    The cap is a pool of readers rather than a plain semaphore, because one
    saver holds a lock around every statement it issues: N probes sharing one
    would queue on that lock and use one connection between them. Each reader is
    a saver over the same connection pool, so a probe waits for a free reader
    rather than for the thread in front of it. Backends that cannot go wider
    hand back the same saver, which keeps the bound and the behaviour they had.

    Every failure is a probe marked ``unverified`` rather than a raised error: a
    thread whose checkpoint could not be read within the budget is reported as
    uncertain, exactly as the sequential path reported a per-thread timeout,
    never as a thread with no checkpoint.
    """
    from ..database.checkpoints import concurrent_checkpointer

    readers: asyncio.Queue[Any] = asyncio.Queue()
    for _ in range(max(1, min(concurrency, len(thread_ids)))):
        readers.put_nowait(await concurrent_checkpointer(checkpointer))

    async def _one(thread_id: str) -> tuple[str, _CheckpointProbe]:
        reader = await readers.get()
        try:
            # No single read may outlast the batch it belongs to.
            checkpoint = await read_latest_checkpoint(
                reader, thread_id, timeout=deadline
            )
            return thread_id, _CheckpointProbe(
                tuple=checkpoint.checkpoint_tuple, unverified=checkpoint.unreadable
            )
        finally:
            readers.put_nowait(reader)

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
) -> tuple[str | None, bool]:
    repair_status = thread.repair_status
    checkpoint_unverified = checkpointer_active and probe.unverified
    checkpoint_id: str | None = None
    if checkpointer_active and probe.tuple is not None:
        checkpoint_id = project_checkpoint_tuple(
            probe.tuple, thread_id=thread.id
        ).checkpoint_id
    if checkpoint_unverified:
        repair_status = escalate_repair_posture(
            repair_status, RepairStatus.CHECKPOINT_UNAVAILABLE
        )
    # Judged as run-status judges it, so the two surfaces report the same
    # posture for one run: a settled run keeps its row unjudged, and only a
    # listing that read checkpoints can say whether the row still matches one.
    if (
        checkpointer_active
        and execution_state is not None
        and thread.status not in TERMINAL_STATUS_VALUES
        and execution_state_is_stale(
            execution_state,
            checkpoint_present=probe.tuple is not None,
            checkpoint_id=checkpoint_id,
        )
    ):
        repair_status = escalate_repair_posture(
            repair_status, RepairStatus.NEEDS_RECONCILIATION
        )
    return repair_status, checkpoint_unverified


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
    repair_status, checkpoint_unverified = _summary_checkpoint_state(
        thread, execution_state, probe, checkpointer_active=checkpointer_active
    )
    approval_status: str | None = None
    approval_request_id: str | None = None
    # A settled run has no live request to read, so it needs no status check here.
    if not checkpoint_unverified:
        approval_status, approval_request_id = durable_approval(
            await actionable_pending_permissions(db, thread_id=thread.id)
        )
    return ThreadSummaryData(
        thread_id=thread.id,
        title=thread.title,
        status=thread.status,
        repair_status=repair_status,
        # Readiness is never judged apart from the repair posture: a run is as
        # fit to resume as the posture this listing settled on says.
        execution_readiness=repair_status,
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
