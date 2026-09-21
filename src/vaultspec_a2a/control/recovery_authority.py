"""Checkpoint-first run recovery; notifications and reads only request a pass."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..database import (
    ThreadModel,
    ThreadStatusElectionOutcome,
    elect_thread_status,
    expire_pending_permission_requests,
    get_control_action_by_dispatch_id,
    mark_control_action_applied,
    set_thread_approval_state,
    set_thread_repair_state,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ..thread.checkpoint_evidence import (
    CheckpointEvidenceKind,
    read_checkpoint_evidence,
)
from ..thread.enums import (
    NON_ACTIVE_STATUSES,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
)
from ..thread.terminal_effects import compute_terminal_effects
from .dispatch_receipts import validate_current_graph_receipt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.checkpoints import Checkpointer
    from ..database.thread_repository import ThreadWriteExpectation
    from ..thread.action_receipts import GraphActionReceipt
    from ..thread.checkpoint_evidence import CheckpointEvidence


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


async def _reconcile_incomplete_checkpoint(
    db: AsyncSession, decision: _CheckpointDecision
) -> RecoveryObservation:
    status = decision.status
    evidence = decision.evidence
    if decision.trigger is RecoveryTrigger.STARTUP and status not in {
        ThreadStatus.RECONCILING,
        ThreadStatus.INPUT_REQUIRED,
    }:
        election = await elect_thread_status(
            db,
            decision.thread_id,
            expectation=decision.expectation,
            status=ThreadStatus.RECONCILING,
            successor=successor_thread_write_authority(
                decision.expectation,
                action_type=decision.receipt.action_type,
                action_receipt_id=decision.receipt.dispatch_id,
            ),
        )
        if election.outcome is ThreadStatusElectionOutcome.WON:
            await set_thread_repair_state(
                db,
                decision.thread_id,
                repair_status=RepairStatus.NEEDS_RECONCILIATION,
                repair_reason=evidence.kind.value,
                execution_readiness=RepairStatus.NEEDS_RECONCILIATION.value,
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


async def _reconcile_completed_checkpoint(
    db: AsyncSession,
    thread: ThreadModel,
    action_id: str,
    decision: _CheckpointDecision,
) -> RecoveryObservation:
    election = await elect_thread_status(
        db,
        decision.thread_id,
        expectation=decision.expectation,
        status=ThreadStatus.COMPLETED,
        successor=successor_thread_write_authority(
            decision.expectation,
            action_type=decision.receipt.action_type,
            action_receipt_id=decision.receipt.dispatch_id,
        ),
    )
    if election.outcome is ThreadStatusElectionOutcome.WON:
        if decision.last_sequence is not None:
            thread.last_sequence = decision.last_sequence
        await mark_control_action_applied(db, action_id)
        await expire_pending_permission_requests(db, thread_id=decision.thread_id)
        await set_thread_approval_state(
            db,
            decision.thread_id,
            approval_status=None,
            approval_request_id=None,
            approval_reason=None,
            approval_response_action_id=None,
        )
        effects = compute_terminal_effects(
            ThreadStatus.COMPLETED, has_cancel_action=False
        )
        await set_thread_repair_state(
            db,
            decision.thread_id,
            repair_status=effects.repair_status,
            repair_reason=effects.repair_reason,
            execution_readiness=effects.repair_status.value,
            last_applied_action=effects.last_applied_action,
        )
    await db.commit()
    fresh = await db.scalar(
        select(ThreadModel)
        .where(ThreadModel.id == decision.thread_id)
        .execution_options(populate_existing=True)
    )
    return RecoveryObservation(
        ThreadStatus(fresh.status) if fresh is not None else None,
        decision.evidence.kind.value
        if election.outcome is ThreadStatusElectionOutcome.WON
        else election.outcome.value,
        decision.evidence.checkpoint_id,
        election.outcome is ThreadStatusElectionOutcome.WON,
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
    )
    if evidence.kind is not CheckpointEvidenceKind.COMPLETED:
        return await _reconcile_incomplete_checkpoint(db, decision)
    return await _reconcile_completed_checkpoint(db, thread, action_id, decision)
