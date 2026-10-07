"""Cancel-thread service logic (Layer 2c — service extraction).

Owns the full cancel workflow: thread validation, idempotency dedup,
control-action creation, repair-state transition, and dispatch.
Commits durable transitions; does not raise HTTPException or touch FastAPI state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ..control.accepted_input import freeze_accepted_input
from ..control.action_lease import (
    ControlActionClaim,
    ControlActionClaimRequest,
    ControlActionOutcome,
    DispatchFailureDisposition,
    prepare_control_action_claim,
)
from ..control.repair_transitions import (
    apply_repair_transition,
    record_undelivered_dispatch,
)
from ..database import (
    ThreadStatusElectionOutcome,
    begin_write_transaction,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_thread,
    retry_write_contention,
    thread_write_expectation,
)
from ..database.models import ThreadModel
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.cancel_policy import can_cancel
from ..thread.dispatch_policy import FailureType
from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ..thread.idempotency import default_cancel_key
from ..thread.repair_policy import RepairPhase, repair_state_for_action
from .leased_dispatch import dispatch_leased

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread import ThreadWriteExpectation
    from ..thread.cancel_policy import CancelEligibility
    from .leased_dispatch import DispatchTransport

__all__ = ["cancel_thread"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CancelContext:
    transport: DispatchTransport
    thread_id: str
    response_idempotency_key: str
    thread_status: str


@dataclass(frozen=True, slots=True)
class _CancelPreflight:
    thread: ThreadModel
    thread_status: str
    expectation: ThreadWriteExpectation
    recovery_deadline_at: datetime


async def _cancel_preflight(
    db: AsyncSession, thread_id: str
) -> _CancelPreflight | ControlActionOutcome:
    thread = await get_thread(db, thread_id)
    if thread is None:
        return ControlActionOutcome(
            thread_id=thread_id,
            error_detail="Thread not found",
            failure_type=FailureType.NOT_FOUND,
        )

    eligibility = can_cancel(thread.status)
    if not eligibility.allowed:
        return ControlActionOutcome(
            thread_id=thread_id,
            thread_status=thread.status,
            error_detail=eligibility.reason,
            applied=eligibility.already_cancelled,
            failure_type=FailureType.TERMINAL,
        )

    # Shared lease replays roll back the session and therefore expire loaded ORM
    # rows. Capture the response state and exact election witness before claiming.
    thread_status = thread.status
    expectation = thread_write_expectation(thread)
    owning_action = await get_control_action_by_dispatch_id(
        db,
        thread_id=thread_id,
        dispatch_id=expectation.authority.action_receipt_id,
    )
    if owning_action is None or owning_action.recovery_deadline_at is None:
        return ControlActionOutcome(
            thread_id=thread_id,
            thread_status=thread_status,
            error_detail="The accepted run carries no recovery deadline",
            failure_type=FailureType.INCOMPATIBLE_STATE,
        )
    if owning_action.recovery_deadline_at <= datetime.now(UTC):
        return ControlActionOutcome(
            thread_id=thread_id,
            thread_status=thread_status,
            error_detail="The accepted run deadline has expired",
            failure_type=FailureType.DEADLINE_EXCEEDED,
        )
    return _CancelPreflight(
        thread, thread_status, expectation, owning_action.recovery_deadline_at
    )


@dataclass(frozen=True, slots=True)
class _ClaimedCancel:
    preflight: _CancelPreflight
    dispatch: DispatchRequest
    claim: ControlActionClaim


async def _claim_cancel(
    db: AsyncSession, thread_id: str, idempotency_key: str
) -> _ClaimedCancel | ControlActionOutcome:
    """Claim one cancellation under the write lock, or refuse having written none."""
    # The preflight reads before the claim writes, so the acceptance transaction
    # has to hold the write lock from its first statement to wait for a racing
    # canceller instead of failing on its commit.
    await begin_write_transaction(db)
    preflight = await _cancel_preflight(db, thread_id)
    if isinstance(preflight, ControlActionOutcome):
        # A refusal wrote nothing; release the write lock before returning.
        await db.rollback()
        return preflight
    dispatch = DispatchRequest(
        action=to_dispatch_action(ControlActionType.CANCEL),
        thread_id=thread_id,
    )
    claim = await prepare_control_action_claim(
        db,
        request=ControlActionClaimRequest(
            thread_id=thread_id,
            action_type=ControlActionType.CANCEL,
            idempotency_key=idempotency_key,
            payload=freeze_accepted_input(dispatch, intent={"cancel": True}),
            dispatch_id=dispatch.dispatch_id,
            recovery_deadline_at=preflight.recovery_deadline_at,
        ),
    )
    return _ClaimedCancel(preflight, dispatch, claim)


async def cancel_thread(
    db: AsyncSession,
    *,
    thread_id: str,
    idempotency_key: str | None,
    transport: DispatchTransport,
) -> ControlActionOutcome:
    """Execute the cancel-thread workflow.

    Returns a :class:`ControlActionOutcome` describing what happened.  Commits the
    session before returning — the service owns its transaction boundary.
    """
    # Cancellation is a resource transition, so one thread has one durable
    # ownership key even when racing callers supplied different retry labels.
    # The caller's label is still echoed in the response for compatibility;
    # it must not create a second dispatchable intention.
    resolved_idempotency_key = default_cancel_key(thread_id)
    response_idempotency_key = idempotency_key or resolved_idempotency_key
    claimed = await retry_write_contention(
        db, lambda: _claim_cancel(db, thread_id, resolved_idempotency_key)
    )
    if isinstance(claimed, ControlActionOutcome):
        return claimed
    thread = claimed.preflight.thread
    thread_status = claimed.preflight.thread_status
    expectation = claimed.preflight.expectation
    dispatch = claimed.dispatch
    claim = claimed.claim
    replay = await _existing_cancel_claim(
        db, claim, thread_id, thread_status, response_idempotency_key
    )
    if replay is not None:
        return replay
    context = _CancelContext(
        transport, thread_id, response_idempotency_key, thread_status
    )
    election_result = await _elect_cancel_authority(
        db, thread, claim, expectation, context
    )
    if election_result is not None:
        return election_result

    return await _dispatch_cancellation(
        db,
        thread,
        claim,
        dispatch,
        context,
    )


async def _existing_cancel_claim(
    db: AsyncSession,
    claim: ControlActionClaim,
    thread_id: str,
    thread_status: str,
    response_idempotency_key: str,
) -> ControlActionOutcome | None:
    if not claim.payload_matches:
        return ControlActionOutcome(
            action_id=claim.action_id,
            thread_id=thread_id,
            thread_status=thread_status,
            error_detail="Idempotency key is already bound to a different action",
            idempotency_key=response_idempotency_key,
            failure_type=FailureType.CONFLICT,
        )
    if not claim.acquired:
        current_thread = await db.get(ThreadModel, thread_id, populate_existing=True)
        if current_thread is None:
            return ControlActionOutcome(
                action_id=claim.action_id,
                thread_id=thread_id,
                error_detail="Thread disappeared while cancellation was leased",
                action_status=claim.result_status,
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.NOT_FOUND,
            )
        if not _cancel_authority_already_owned(
            thread_write_expectation(current_thread), claim.dispatch_id
        ):
            return ControlActionOutcome(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=current_thread.status == ThreadStatus.CANCELLED.value,
                thread_status=current_thread.status,
                error_detail=(
                    "Cancellation action is leased but does not own thread authority"
                ),
                applied=current_thread.status == ThreadStatus.CANCELLED.value,
                action_status=claim.result_status,
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.CONFLICT,
            )
        return ControlActionOutcome(
            action_id=claim.action_id,
            thread_id=thread_id,
            cancelled=True,
            thread_status=ThreadStatus.CANCELLING.value,
            accepted=True,
            applied=claim.applied,
            action_status=claim.result_status,
            idempotency_key=response_idempotency_key,
        )
    return None


def _cancel_authority_already_owned(
    expectation: ThreadWriteExpectation, dispatch_id: str
) -> bool:
    """Return whether the expected writer already owns this cancel receipt."""
    return (
        expectation.status is ThreadStatus.CANCELLING
        and expectation.authority.owned_by(ControlActionType.CANCEL, dispatch_id)
    )


def _cancel_election_conflict(
    eligibility: CancelEligibility,
) -> tuple[FailureType | None, str | None]:
    """Classify a lost cancellation election against the refreshed thread."""
    if eligibility.already_cancelled:
        return None, None
    if eligibility.allowed:
        return (
            FailureType.CONFLICT,
            "Thread authority changed during cancellation election",
        )
    return FailureType.TERMINAL, eligibility.reason


async def _elect_cancel_authority(
    db: AsyncSession,
    thread: ThreadModel,
    claim: ControlActionClaim,
    expectation: ThreadWriteExpectation,
    context: _CancelContext,
) -> ControlActionOutcome | None:
    thread_id = context.thread_id
    thread_status = context.thread_status
    response_idempotency_key = context.response_idempotency_key
    already_owned = _cancel_authority_already_owned(expectation, claim.dispatch_id)
    election = (
        None
        if already_owned
        else await elect_thread_status(
            db,
            thread_id,
            expectation=expectation,
            status=ThreadStatus.CANCELLING,
            action_type=ControlActionType.CANCEL,
            action_receipt_id=claim.dispatch_id,
        )
    )
    if election is not None and election.outcome is not ThreadStatusElectionOutcome.WON:
        await db.rollback()
        if election.outcome is ThreadStatusElectionOutcome.NOT_FOUND:
            return ControlActionOutcome(
                action_id=claim.action_id,
                thread_id=thread_id,
                error_detail="Thread disappeared during cancellation election",
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.NOT_FOUND,
            )
        if election.outcome is ThreadStatusElectionOutcome.RECEIPT_MISMATCH:
            return ControlActionOutcome(
                action_id=claim.action_id,
                thread_id=thread_id,
                thread_status=thread_status,
                error_detail="Cancellation receipt does not match its durable action",
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.CONFLICT,
            )
        await db.refresh(thread)
        eligibility = can_cancel(thread.status)
        failure_type, error_detail = _cancel_election_conflict(eligibility)
        return ControlActionOutcome(
            action_id=claim.action_id,
            thread_id=thread_id,
            cancelled=eligibility.already_cancelled,
            thread_status=thread.status,
            error_detail=error_detail,
            applied=eligibility.already_cancelled,
            idempotency_key=response_idempotency_key,
            failure_type=failure_type,
        )
    if election is not None:
        await apply_repair_transition(
            db,
            thread_id,
            repair_state_for_action(ControlActionType.CANCEL, RepairPhase.REQUESTED),
        )
    return None


async def _dispatch_cancellation(
    db: AsyncSession,
    thread: ThreadModel,
    claim: ControlActionClaim,
    dispatch: DispatchRequest,
    context: _CancelContext,
) -> ControlActionOutcome:
    thread_id = context.thread_id
    response_idempotency_key = context.response_idempotency_key
    logger.info(
        "Dispatching cancel dispatch_id=%s for thread %s",
        claim.dispatch_id,
        thread_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": claim.dispatch_id,
            "action": dispatch.action,
        },
    )

    failure = await dispatch_leased(db, claim, dispatch, context.transport)
    if failure is not None:
        settlement = failure.disposition
        if settlement is DispatchFailureDisposition.AMBIGUOUS_DELIVERY:
            # UNREACHABLE is ambiguous: the worker may have scheduled the
            # cancellation before the acknowledgement was lost.  Keep both the
            # durable lease and the cancelling projection so restart/TTL
            # reconciliation can converge on the accepted intent.  Returning a
            # rejection here would contradict the journal and invite the caller
            # to submit a competing action.
            await db.commit()
            return ControlActionOutcome(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=True,
                thread_status=ThreadStatus.CANCELLING.value,
                accepted=True,
                action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
                idempotency_key=response_idempotency_key,
            )
        if settlement is DispatchFailureDisposition.APPLICATION_WON:
            await db.refresh(thread)
            await db.commit()
            return ControlActionOutcome(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=True,
                thread_status=thread.status,
                accepted=True,
                applied=True,
                action_status=ControlActionResultStatus.APPLIED.value,
                idempotency_key=response_idempotency_key,
            )
        if settlement in {
            DispatchFailureDisposition.AUTHORITY_LOST,
            DispatchFailureDisposition.DEADLINE_EXPIRED,
        }:
            await db.refresh(thread)
            await db.commit()
            return ControlActionOutcome(
                action_id=claim.action_id,
                thread_id=thread_id,
                thread_status=thread.status,
                idempotency_key=response_idempotency_key,
                error_detail=(
                    "Cancellation authority changed before failure settlement"
                    if settlement is DispatchFailureDisposition.AUTHORITY_LOST
                    else "The accepted run deadline expired"
                ),
                failure_type=(
                    FailureType.INCOMPATIBLE_STATE
                    if settlement is DispatchFailureDisposition.AUTHORITY_LOST
                    else FailureType.DEADLINE_EXCEEDED
                ),
            )
        logger.warning(
            "Cancel dispatch failed for thread %s after durable cancellation election",
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": claim.dispatch_id,
                "action": dispatch.action,
            },
        )
        await record_undelivered_dispatch(db, thread_id, reason=failure.detail)
        await db.commit()
        return ControlActionOutcome(
            action_id=claim.action_id,
            thread_id=thread_id,
            thread_status=ThreadStatus.CANCELLING.value,
            idempotency_key=response_idempotency_key,
            failure_type=failure.failure_type,
        )

    await db.commit()
    return ControlActionOutcome(
        action_id=claim.action_id,
        thread_id=thread_id,
        cancelled=True,
        thread_status=ThreadStatus.CANCELLING.value,
        accepted=True,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        idempotency_key=response_idempotency_key,
    )
