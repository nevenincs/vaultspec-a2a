"""The run's pause recorder: one projection of every interrupt a run parks on.

The checkpoint owns whether a run is parked, on which interrupt and under which
request id, for every interrupt kind. This module is the one writer of what
follows from that on the run row: both edges of ``input_required``, the repair
posture a held permission request leaves, and the pending approval a plan or
document gate shows. The permission journal records requests; it never opens or
closes a pause.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..database import (
    ThreadModel,
    ThreadStatusElectionOutcome,
    begin_write_transaction,
    elect_thread_status,
    get_permission_request,
    lock_thread_row,
    read_latest_checkpoint,
    set_thread_approval_state,
    thread_write_expectation,
)
from ..thread import (
    ApprovalStatus,
    InterruptType,
    RepairStatus,
    ThreadStatus,
    project_checkpoint_tuple,
)
from ..thread.action_receipts import GRAPH_ACTION_VERB
from ..thread.permission_fsm import compute_permission_request_effects
from ..thread.repair_policy import RepairPhase, repair_state_for_action
from ..thread.snapshots import PERMISSION_REQUEST_EVENT_TYPES
from .repair_transitions import apply_repair_transition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import CheckpointRead
    from ..database.checkpoints import Checkpointer
    from ..thread import (
        CheckpointProjection,
        ProjectedInterrupt,
        ThreadWriteExpectation,
    )
    from ..thread.repair_policy import RepairTransition

__all__ = ["project_checkpoint_read", "reconcile_run_pause"]

logger = logging.getLogger(__name__)

#: The writers a pause is recorded under: the dispatches that run the graph. An
#: interrupt is raised inside one of them, answer resumes included, so the pause
#: is a fact about that dispatch rather than a control action of its own.
_GRAPH_RUN_WRITERS = frozenset(GRAPH_ACTION_VERB)
#: The statuses of a run whose graph may be executing, and so may park.
_PARKABLE_STATUSES = frozenset(
    {ThreadStatus.SUBMITTED, ThreadStatus.RUNNING, ThreadStatus.RECONCILING}
)


def project_checkpoint_read(
    checkpoint: CheckpointRead, thread_id: str
) -> CheckpointProjection | None:
    """Project one checkpoint read, or ``None`` when it holds nothing readable.

    A missing checkpoint, an unreadable one and one the projection cannot read
    all show nothing about what the run is parked on. The projection failure is
    logged because, unlike absence, it hides a checkpoint that exists.
    """
    if checkpoint.checkpoint_tuple is None:
        return None
    try:
        return project_checkpoint_tuple(
            checkpoint.checkpoint_tuple, thread_id=thread_id
        )
    except (AttributeError, TypeError, ValueError):
        logger.warning(
            "Could not project the checkpoint of thread %s",
            thread_id,
            exc_info=True,
        )
        return None


@dataclass(frozen=True, slots=True)
class _RecordedPause:
    """The pause-derived fields of a run row, as one read of it saw them."""

    expectation: ThreadWriteExpectation
    repair_status: str
    approval_status: str | None
    approval_request_id: str | None

    @classmethod
    def of(cls, thread: ThreadModel) -> _RecordedPause:
        return cls(
            thread_write_expectation(thread),
            thread.repair_status,
            thread.approval_status,
            thread.approval_request_id,
        )

    @property
    def parked(self) -> bool:
        return self.expectation.status is ThreadStatus.INPUT_REQUIRED

    @property
    def recordable(self) -> bool:
        """Whether a graph-run dispatch holds the run in a status a pause moves."""
        return self.expectation.authority.action_type in _GRAPH_RUN_WRITERS and (
            self.parked or self.expectation.status in _PARKABLE_STATUSES
        )


@dataclass(frozen=True, slots=True)
class _PauseWrites:
    """What the run row must change to say what its checkpoint holds."""

    status: ThreadStatus | None
    repair: RepairTransition | None
    pending_approval: str | None
    clear_approval: bool

    @property
    def required(self) -> bool:
        return (
            self.status is not None
            or self.repair is not None
            or self.pending_approval is not None
            or self.clear_approval
        )


def _pause_writes(
    recorded: _RecordedPause, held: Sequence[ProjectedInterrupt]
) -> _PauseWrites:
    """Compare the recorded pause with the interrupts the checkpoint holds.

    A healthy run held by a permission request reads paused-resumable, and any
    other repair posture belongs to the event that set it. A gate's request
    becomes the pending approval only when it is a request the row does not
    already name, so a verdict already submitted for it is never reset; a
    pending approval the checkpoint no longer holds is cleared.
    """
    status = None
    if bool(held) != recorded.parked:
        status = ThreadStatus.INPUT_REQUIRED if held else ThreadStatus.RUNNING
    permissions = [
        (
            interrupt.interrupt_id,
            compute_permission_request_effects(interrupt.interrupt_type),
        )
        for interrupt in held
        if interrupt.interrupt_type in PERMISSION_REQUEST_EVENT_TYPES
    ]
    repair = None
    if permissions and recorded.repair_status == RepairStatus.HEALTHY:
        repair = repair_state_for_action(
            permissions[0][1].last_applied_action, RepairPhase.APPLIED
        )
    approval = next(
        (request_id for request_id, effects in permissions if effects.is_plan_approval),
        None,
    )
    return _PauseWrites(
        status=status,
        repair=repair,
        pending_approval=(
            approval if approval != recorded.approval_request_id else None
        ),
        clear_approval=(
            approval is None and recorded.approval_status == ApprovalStatus.PENDING
        ),
    )


async def _record_pause(
    db: AsyncSession, thread_id: str, recorded: _RecordedPause, writes: _PauseWrites
) -> bool:
    """Apply *writes* under the witness *recorded* holds; ``False`` if it lost."""
    if writes.status is not None:
        authority = recorded.expectation.authority
        election = await elect_thread_status(
            db,
            thread_id,
            expectation=recorded.expectation,
            status=writes.status,
            action_type=authority.action_type,
            action_receipt_id=authority.action_receipt_id,
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            return False
    if writes.repair is not None:
        await apply_repair_transition(db, thread_id, writes.repair)
    if writes.pending_approval is not None:
        # The journal caches the gate's description; the row may not be there
        # yet when a resume's receipt is relayed before the request it raised.
        journal = await get_permission_request(db, writes.pending_approval)
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=ApprovalStatus.PENDING,
            approval_request_id=writes.pending_approval,
            approval_reason=journal.description if journal is not None else None,
            approval_response_action_id=None,
        )
    elif writes.clear_approval:
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=None,
            approval_request_id=None,
            approval_reason=None,
            approval_response_action_id=None,
        )
    return True


async def reconcile_run_pause(
    db: AsyncSession, *, thread_id: str, checkpointer: Checkpointer
) -> None:
    """Make the run row say what its checkpoint shows it parked on, if anything.

    A parked run reads ``input_required`` and refuses follow-up turns, and a
    released one reads ``running`` again, whatever kind of interrupt held it. A
    relayed frame only prompts this read, so a stale or replayed nudge changes
    nothing the checkpoint does not show.

    The witness is taken before the checkpoint read, and the writes happen only
    while the locked row still matches it: a writer that moved in between may
    postdate the checkpoint read, so this read decides nothing and the next
    prompt reads again. The status moves under the current writer's own identity
    because the pause is a fact about the dispatch that raised it.
    """
    thread = await db.get(ThreadModel, thread_id, populate_existing=True)
    recorded = _RecordedPause.of(thread) if thread is not None else None
    await db.rollback()
    if recorded is None or not recorded.recordable:
        return
    projection = project_checkpoint_read(
        await read_latest_checkpoint(checkpointer, thread_id), thread_id
    )
    if projection is None:
        return
    held = [
        interrupt
        for interrupt in projection.pending_interrupts
        if interrupt.interrupt_type in InterruptType
    ]
    if not _pause_writes(recorded, held).required:
        return
    await begin_write_transaction(db)
    try:
        locked = await lock_thread_row(db, thread_id)
        if locked is None:
            return
        current = _RecordedPause.of(locked)
        if current.expectation != recorded.expectation:
            return
        writes = _pause_writes(current, held)
        if writes.required and await _record_pause(db, thread_id, current, writes):
            await db.commit()
    finally:
        if db.in_transaction():
            await db.rollback()
