"""Checkpoint-first run recovery; notifications and reads only request a pass."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..database import (
    ThreadModel,
    ThreadStatusElectionOutcome,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    has_live_queued_continuation_lease,
    mark_control_action_applied,
    read_next_queued_continuation,
    thread_write_expectation,
)
from ..thread.checkpoint_evidence import (
    CheckpointEvidenceKind,
    read_checkpoint_evidence,
)
from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ControlActionType,
    ThreadStatus,
)
from ..thread.repair_policy import (
    RECONCILIATION_REQUIRED_TRANSITION,
    RepairPhase,
    repair_state_for_action,
)
from .dispatch_receipts import (
    prepare_graph_action_receipt,
    validate_current_graph_receipt,
)
from .repair_transitions import apply_repair_transition
from .repositories.continuation_queue import (
    open_promoted_continuation,
    promoted_turn_deadline,
    promotion_dispatch_pending,
    run_lifetime_deadline,
)
from .terminal_settlement import TerminalEvidence, lock_terminal_run, settle_terminal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.checkpoints import Checkpointer
    from ..thread import ThreadWriteExpectation
    from ..thread.action_receipts import GraphActionReceipt
    from ..thread.checkpoint_evidence import CheckpointEvidence

__all__ = [
    "AWAITING_PROMOTION_DISPATCH",
    "CONTINUATION_NOT_PROMOTABLE",
    "CONTINUATION_PROMOTED",
    "HOLDS_QUEUED_CONTINUATION",
    "PROMOTION_OWNED_CONDITIONS",
    "RecoveryObservation",
    "RecoveryRequest",
    "RecoveryTrigger",
    "reconcile_run_checkpoint",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    status: ThreadStatus | None
    condition: str
    checkpoint_id: str | None
    changed: bool


class RecoveryTrigger(StrEnum):
    STARTUP = "startup"
    READ = "read"
    WORKER_EVENT = "worker_event"
    RETRY = "retry"


#: Conditions a run can report instead of a settled or reconciled one. The
#: first says the next turn now owns the run; the second says a waiting turn
#: could not be made into one, so nothing was settled and nothing was
#: promoted; the third says a promoted turn is still owed its delivery.
CONTINUATION_PROMOTED = "continuation_promoted"
CONTINUATION_NOT_PROMOTABLE = "continuation_not_promotable"
AWAITING_PROMOTION_DISPATCH = "awaiting_promotion_dispatch"
HOLDS_QUEUED_CONTINUATION = "holds_queued_continuation"

#: The conditions that say a promoter, not a dead writer, explains this run.
#: A startup pass counts these apart from its repair backlog, because an
#: owned run needs nobody's attention.
PROMOTION_OWNED_CONDITIONS = frozenset(
    {AWAITING_PROMOTION_DISPATCH, HOLDS_QUEUED_CONTINUATION}
)

#: Why a run past its total lifetime refuses the continuations still waiting on
#: it: no further turn may start, so none of them can be promoted.
_LIFETIME_SPENT_REFUSAL = "the run's total lifetime is spent"


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    """Run, trigger, and bounded checkpoint read for one reconciliation pass."""

    thread_id: str
    trigger: RecoveryTrigger
    checkpoint_timeout_seconds: float
    last_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class _CheckpointDecision:
    thread_id: str
    status: ThreadStatus
    expectation: ThreadWriteExpectation
    receipt: GraphActionReceipt
    evidence: CheckpointEvidence
    trigger: RecoveryTrigger
    last_sequence: int | None
    #: The instant past which this run may run no further turn, derived from
    #: its own creation. Snapshotted with everything else before the read
    #: transaction closes.
    lifetime_deadline_at: datetime
    #: Whether this run's current writer is a promoted continuation that no
    #: dispatcher has delivered yet. Read off the journal row before the read
    #: transaction closes, because a rollback expires it.
    promotion_pending: bool = False
    #: Whether a waiting continuation's live lease still owns this run.
    queue_owned: bool = False


def _promotion_owner(decision: _CheckpointDecision) -> str | None:
    """Name the promoter answerable for this run, or ``None`` if there is none.

    Two shapes of the same window, and both look exactly like a writer that
    died. A promoted turn that has not reached the graph leaves a checkpoint
    naming the turn before it; a turn still waiting leaves a run that is
    RUNNING with no live worker. Each is distinguished by a durable local
    fact - the writer is an undelivered continuation inside its own deadline,
    or a waiting reservation still holds its lease - and each names someone
    answerable. Reconciling either would move the run into repair underneath
    the promoter and strand the turn it owes.
    """
    if (
        decision.promotion_pending
        and decision.evidence.kind is CheckpointEvidenceKind.PRIOR_ACTION
    ):
        return AWAITING_PROMOTION_DISPATCH
    if decision.queue_owned:
        return HOLDS_QUEUED_CONTINUATION
    return None


async def _reconcile_incomplete_checkpoint(
    db: AsyncSession, decision: _CheckpointDecision
) -> RecoveryObservation:
    status = decision.status
    evidence = decision.evidence
    owner = _promotion_owner(decision)
    if owner is not None:
        return RecoveryObservation(status, owner, evidence.checkpoint_id, False)
    if decision.trigger is RecoveryTrigger.STARTUP and status not in {
        ThreadStatus.RECONCILING,
        ThreadStatus.INPUT_REQUIRED,
    }:
        election = await elect_thread_status(
            db,
            decision.thread_id,
            expectation=decision.expectation,
            status=ThreadStatus.RECONCILING,
            action_type=decision.receipt.action_type,
            action_receipt_id=decision.receipt.dispatch_id,
        )
        if election.outcome is ThreadStatusElectionOutcome.WON:
            await apply_repair_transition(
                db,
                decision.thread_id,
                RECONCILIATION_REQUIRED_TRANSITION,
                reason=evidence.kind.value,
            )
        await db.commit()
        fresh = await db.get(ThreadModel, decision.thread_id, populate_existing=True)
        return RecoveryObservation(
            ThreadStatus(fresh.status) if fresh is not None else None,
            evidence.kind.value,
            evidence.checkpoint_id,
            election.outcome is ThreadStatusElectionOutcome.WON,
        )
    return RecoveryObservation(
        status, evidence.kind.value, evidence.checkpoint_id, False
    )


async def _promote_queued_continuation(
    db: AsyncSession,
    thread: ThreadModel,
    settled_action_id: str,
    decision: _CheckpointDecision,
    *,
    promoted_at: datetime,
) -> RecoveryObservation | None:
    """Hand the run to the continuation waiting behind this proven turn.

    Runs inside the transaction that would otherwise settle the run, and
    against the same witness, so a continuation either arrives before
    settlement and defers it or meets a settled run. There is no third
    outcome, and that is what keeps a terminal state from ever being reopened.

    Returns ``None`` when nothing is waiting, which leaves the caller to settle
    exactly as it always has.
    """
    waiting = await read_next_queued_continuation(db, thread_id=decision.thread_id)
    if waiting is None:
        return None
    deadline_at = promoted_turn_deadline(
        waiting,
        promoted_at=promoted_at,
        lifetime_deadline_at=decision.lifetime_deadline_at,
    )
    dispatch_id = waiting.dispatch_id
    if deadline_at is None or dispatch_id is None:
        return await _refuse_promotion(db, decision, "unreadable accepted envelope")
    # The reservation stops being one before anything is installed on it: the
    # journal refuses a waiting row that owns a receipt.
    open_promoted_continuation(waiting, deadline_at=deadline_at)
    await db.flush()
    await mark_control_action_applied(db, settled_action_id)
    election = await elect_thread_status(
        db,
        decision.thread_id,
        expectation=decision.expectation,
        status=ThreadStatus.RUNNING,
        action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        action_receipt_id=dispatch_id,
    )
    if election.outcome is not ThreadStatusElectionOutcome.WON:
        return await _refuse_promotion(db, decision, election.outcome.value)
    receipt = await prepare_graph_action_receipt(
        db, thread_id=decision.thread_id, dispatch_id=dispatch_id
    )
    if receipt is None:
        return await _refuse_promotion(db, decision, "receipt refused")
    if decision.last_sequence is not None:
        thread.last_sequence = decision.last_sequence
    await apply_repair_transition(
        db,
        decision.thread_id,
        repair_state_for_action(
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED, RepairPhase.REQUESTED
        ),
    )
    await db.commit()
    return RecoveryObservation(
        ThreadStatus.RUNNING,
        CONTINUATION_PROMOTED,
        decision.evidence.checkpoint_id,
        True,
    )


async def _refuse_promotion(
    db: AsyncSession, decision: _CheckpointDecision, reason: str
) -> RecoveryObservation:
    """Abandon a promotion attempt without settling the run in its place.

    Settling here would be the one thing this decision forbids: it would
    discard a continuation that was durably accepted. The run keeps its
    proven turn unsettled instead, and the accepted action's own deadline
    bounds how long that can last.
    """
    await db.rollback()
    logger.warning(
        "Could not promote the continuation waiting on %s: %s",
        decision.thread_id,
        reason,
        extra={
            "thread_id": decision.thread_id,
            "reason": reason,
            "action": "continuation_not_promoted",
        },
    )
    return RecoveryObservation(
        decision.status,
        CONTINUATION_NOT_PROMOTABLE,
        decision.evidence.checkpoint_id,
        False,
    )


async def _reconcile_completed_checkpoint(
    db: AsyncSession,
    thread: ThreadModel,
    action_id: str,
    decision: _CheckpointDecision,
) -> RecoveryObservation:
    # The queue is read under the settlement's own lock, so a promotion and
    # the settlement it defers decide against the same locked row.
    locked = await lock_terminal_run(db, decision.thread_id)
    if locked is not None:
        thread = locked
    observed_at = datetime.now(UTC)
    # A queue must not make a run immortal. Past its lifetime the run ends with
    # the terminal its last turn actually reached, and the settlement refuses
    # everything still waiting rather than leaving it on a settled run waiting
    # for a promotion that can never come.
    lifetime_spent = observed_at >= decision.lifetime_deadline_at
    if not lifetime_spent:
        promoted = await _promote_queued_continuation(
            db, thread, action_id, decision, promoted_at=observed_at
        )
        if promoted is not None:
            return promoted
    outcome = await settle_terminal(
        db,
        thread,
        ThreadStatus.COMPLETED,
        evidence=TerminalEvidence(
            expectation=decision.expectation,
            action_id=action_id,
            action_type=decision.receipt.action_type,
            action_receipt_id=decision.receipt.dispatch_id,
            queue_refusal_reason=_LIFETIME_SPENT_REFUSAL if lifetime_spent else None,
        ),
        last_sequence=decision.last_sequence,
    )
    await db.commit()
    fresh = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == decision.thread_id)
        .execution_options(populate_existing=True)
    )
    won = outcome is ThreadStatusElectionOutcome.WON
    return RecoveryObservation(
        ThreadStatus(fresh.status) if fresh is not None else None,
        decision.evidence.kind.value if won else outcome.value,
        decision.evidence.checkpoint_id,
        won,
    )


async def reconcile_run_checkpoint(
    db: AsyncSession,
    checkpointer: Checkpointer,
    request: RecoveryRequest,
) -> RecoveryObservation:
    """Settle completion only from current durable action and checkpoint evidence."""
    thread_id = request.thread_id
    thread = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == thread_id)
        .execution_options(populate_existing=True)
    )
    if thread is None:
        return RecoveryObservation(None, "run_missing", None, False)
    status = ThreadStatus(thread.status)
    if status in NON_ACTIVE_STATUSES:
        return RecoveryObservation(status, "run_inactive", None, False)
    expectation = thread_write_expectation(thread)
    action = await get_control_action_by_dispatch_id(
        db, thread_id=thread_id, dispatch_id=expectation.authority.action_receipt_id
    )
    if (
        action is not None
        and status is ThreadStatus.INPUT_REQUIRED
        and action.action_type == ControlActionType.PERMISSION_REQUEST_CREATED
        and expectation.authority.action_type
        is ControlActionType.PERMISSION_REQUEST_CREATED
    ):
        return RecoveryObservation(status, "awaiting_control", None, False)
    receipt = validate_current_graph_receipt(thread, action)
    if receipt is None or action is None:
        return RecoveryObservation(status, "incompatible_action_receipt", None, False)
    action_id = action.id
    observed_at = datetime.now(UTC)
    lifetime_deadline_at = run_lifetime_deadline(thread.created_at)
    promotion_pending = promotion_dispatch_pending(action, observed_at=observed_at)
    queue_owned = await has_live_queued_continuation_lease(
        db, thread_id=thread_id, observed_at=observed_at
    )
    # The checkpoint store is a different transaction owner. Release this read
    # snapshot before awaiting it; the later election compares the saved witness.
    await db.commit()
    evidence = await read_checkpoint_evidence(
        checkpointer, receipt, timeout_seconds=request.checkpoint_timeout_seconds
    )
    decision = _CheckpointDecision(
        thread_id,
        status,
        expectation,
        receipt,
        evidence,
        request.trigger,
        request.last_sequence,
        lifetime_deadline_at,
        promotion_pending,
        queue_owned,
    )
    if evidence.kind is not CheckpointEvidenceKind.COMPLETED:
        return await _reconcile_incomplete_checkpoint(db, decision)
    return await _reconcile_completed_checkpoint(db, thread, action_id, decision)
