"""Cancel-thread service logic (Layer 2c — service extraction).

Owns the full cancel workflow: thread validation, idempotency dedup,
control-action creation, repair-state transition, and dispatch.
Commits durable transitions; does not raise HTTPException or touch FastAPI state.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError

from ..control.accepted_input import freeze_accepted_input
from ..control.action_lease import (
    ControlActionClaim,
    DispatchFailureDisposition,
    finalize_control_action_acceptance,
    prepare_control_action_claim,
    record_dispatch_failure,
)
from ..control.dispatch import safe_dispatch
from ..control.repair_transitions import (
    mark_cancel_requested,
    record_undelivered_dispatch,
)
from ..database import (
    ThreadStatusElectionOutcome,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_thread,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ..database.models import ThreadModel
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.cancel_policy import can_cancel
from ..thread.dispatch_policy import FailureType, evaluate_dispatch_failure
from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    ThreadStatus,
)
from ..thread.idempotency import default_cancel_key

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..control.circuit_breaker import WorkerCircuitBreaker
    from ..control.worker_management import LazyWorkerSpawner
    from ..database import ThreadWriteExpectation

__all__ = ["CancelResult", "CancelRuntime", "cancel_thread"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CancelResult:
    """Outcome of a cancel-thread service call."""

    action_id: str | None
    thread_id: str
    cancelled: bool
    thread_status: str
    error_detail: str | None = None
    accepted: bool = False
    applied: bool = False
    action_status: str = ControlActionResultStatus.REJECTED_INVALID_STATE.value
    idempotency_key: str | None = None
    failure_type: FailureType | None = None


@dataclass(frozen=True, slots=True)
class CancelRuntime:
    circuit_breaker: WorkerCircuitBreaker
    worker_spawner: LazyWorkerSpawner
    worker_client: httpx.AsyncClient
    recursion_limit: int
    trace_headers: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class _CancelContext:
    runtime: CancelRuntime
    thread_id: str
    response_idempotency_key: str
    thread_status: str


@dataclass(frozen=True, slots=True)
class _CancelPreflight:
    thread: ThreadModel
    thread_status: str
    expectation: ThreadWriteExpectation
    recovery_deadline_at: datetime


def raise_for_cancel_failure(result: CancelResult, *, resource_noun: str) -> None:
    """Translate a cancel outcome's failure into the HTTP error the route returns.

    Both the internal thread-cancel route and the versioned run-cancel verb
    performed this mapping inline and identically, differing only in the resource
    noun. Sharing it keeps the two edges from drifting to different status codes
    for the same underlying outcome, which is the failure a duplicated mapping
    invites.

    The mapping follows :class:`~..thread.dispatch_policy.FailureType`'s own
    split, which separates DOMAIN rejections from DISPATCH failures. A dispatch
    failure means the request could not be delivered - the worker was unreachable,
    the circuit was open, capacity was spent - and a bad gateway describes it
    exactly. A domain rejection means delivery was never attempted because the
    run's own state forbids the verb, and that is a statement about the resource,
    never about an upstream. Reporting the second as the first is what this
    function used to do, and it told a caller its infrastructure had failed when
    the truth was that its run had already finished.

    Three outcomes, therefore:

    * **Absent** - 404, naming the resource.
    * **Settled some other way** - 409, because a completed, failed, archived, or
      tearing-down run cannot be cancelled and no retry will change that. The
      status is the caller's signal to re-read the run rather than to retry.
    * **Already cancelled** - no error at all. The verb is idempotent and the
      state the caller asked for is the state that holds, so the route answers
      with the run's terminal status and ``applied`` set. Refusing here would
      make a second cancel fail purely for being second.

    Args:
        result: The cancel-service outcome to inspect.
        resource_noun: What the 404 names - ``"Thread"`` or ``"Run"`` - so each
            edge speaks its own vocabulary without owning the status logic.

    Raises:
        HTTPException: 404 when the target is absent, 409 when its state forbids
            cancellation, 502 on a genuine dispatch failure. Returns without
            raising when the cancel succeeded or was already satisfied.
    """
    from fastapi import HTTPException

    if result.failure_type == FailureType.NOT_FOUND:
        raise HTTPException(status_code=404, detail=f"{resource_noun} not found")
    if result.failure_type == FailureType.TERMINAL:
        # Discriminated on the run's own status rather than on ``applied``, which
        # carries a different meaning on the success path and would make this read
        # as a coincidence of two flags instead of the state check it is.
        if result.thread_status == ThreadStatus.CANCELLED.value:
            return
        raise HTTPException(
            status_code=409,
            detail=result.error_detail
            or (
                f"{resource_noun} is in {result.thread_status!r} state and cannot "
                "be cancelled"
            ),
        )
    if result.failure_type == FailureType.CONFLICT:
        raise HTTPException(status_code=409, detail=result.error_detail)
    if result.failure_type == FailureType.DEADLINE_EXCEEDED:
        raise HTTPException(status_code=409, detail=result.error_detail)
    if result.failure_type is not None:
        raise HTTPException(
            status_code=502, detail=result.error_detail or "Cancel dispatch failed"
        )


async def _cancel_preflight(
    db: AsyncSession, thread_id: str
) -> _CancelPreflight | CancelResult:
    thread = await get_thread(db, thread_id)
    if thread is None:
        return CancelResult(
            action_id=None,
            thread_id=thread_id,
            cancelled=False,
            thread_status="",
            error_detail="Thread not found",
            failure_type=FailureType.NOT_FOUND,
        )

    eligibility = can_cancel(thread.status)
    if not eligibility.allowed:
        return CancelResult(
            action_id=None,
            thread_id=thread_id,
            cancelled=False,
            thread_status=thread.status,
            accepted=False,
            applied=eligibility.already_cancelled,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
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
        return CancelResult(
            action_id=None,
            thread_id=thread_id,
            cancelled=False,
            thread_status=thread_status,
            error_detail="The accepted run carries no recovery deadline",
            failure_type=FailureType.INCOMPATIBLE_STATE,
        )
    if owning_action.recovery_deadline_at <= datetime.now(UTC):
        return CancelResult(
            action_id=None,
            thread_id=thread_id,
            cancelled=False,
            thread_status=thread_status,
            error_detail="The accepted run deadline has expired",
            failure_type=FailureType.DEADLINE_EXCEEDED,
        )
    return _CancelPreflight(
        thread, thread_status, expectation, owning_action.recovery_deadline_at
    )


async def cancel_thread(
    db: AsyncSession,
    *,
    thread_id: str,
    idempotency_key: str | None,
    runtime: CancelRuntime,
    _busy_retries: int = 0,
) -> CancelResult:
    """Execute the cancel-thread workflow.

    Returns a :class:`CancelResult` describing what happened.  Commits the
    session before returning — the service owns its transaction boundary.
    """
    preflight = await _cancel_preflight(db, thread_id)
    if isinstance(preflight, CancelResult):
        return preflight
    thread = preflight.thread
    thread_status = preflight.thread_status
    expectation = preflight.expectation

    # Cancellation is a resource transition, so one thread has one durable
    # ownership key even when racing callers supplied different retry labels.
    # The caller's label is still echoed in the response for compatibility;
    # it must not create a second dispatchable intention.
    resolved_idempotency_key = default_cancel_key(thread_id)
    response_idempotency_key = idempotency_key or resolved_idempotency_key
    dispatch = DispatchRequest(
        action=to_dispatch_action(ControlActionType.CANCEL),
        thread_id=thread_id,
        recursion_limit=runtime.recursion_limit,
    )
    try:
        claim = await prepare_control_action_claim(
            db,
            thread_id=thread_id,
            action_type=ControlActionType.CANCEL,
            idempotency_key=resolved_idempotency_key,
            payload=freeze_accepted_input(dispatch, intent={"cancel": True}),
            dispatch_id=dispatch.dispatch_id,
            recovery_deadline_at=preflight.recovery_deadline_at,
        )
    except OperationalError as exc:
        if (
            not isinstance(exc.orig, sqlite3.OperationalError)
            or "locked" not in str(exc.orig).lower()
            or _busy_retries >= 4
        ):
            raise
        await db.rollback()
        await asyncio.sleep(0.02 * (_busy_retries + 1))
        return await cancel_thread(
            db,
            thread_id=thread_id,
            idempotency_key=idempotency_key,
            runtime=runtime,
            _busy_retries=_busy_retries + 1,
        )
    replay = await _existing_cancel_claim(
        db, claim, thread_id, thread_status, response_idempotency_key
    )
    if replay is not None:
        return replay
    context = _CancelContext(
        runtime, thread_id, response_idempotency_key, thread_status
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
) -> CancelResult | None:
    if not claim.payload_matches:
        return CancelResult(
            action_id=claim.action_id,
            thread_id=thread_id,
            cancelled=False,
            thread_status=thread_status,
            error_detail="Idempotency key is already bound to a different action",
            idempotency_key=response_idempotency_key,
            failure_type=FailureType.CONFLICT,
        )
    if not claim.acquired:
        current_thread = await db.get(ThreadModel, thread_id, populate_existing=True)
        if current_thread is None:
            return CancelResult(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=False,
                thread_status="",
                error_detail="Thread disappeared while cancellation was leased",
                accepted=False,
                applied=False,
                action_status=claim.result_status,
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.NOT_FOUND,
            )
        claim_owns_thread = (
            current_thread.status == ThreadStatus.CANCELLING.value
            and current_thread.writer_action_type == ControlActionType.CANCEL.value
            and current_thread.writer_action_receipt_id == claim.dispatch_id
        )
        if not claim_owns_thread:
            return CancelResult(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=current_thread.status == ThreadStatus.CANCELLED.value,
                thread_status=current_thread.status,
                error_detail=(
                    "Cancellation action is leased but does not own thread authority"
                ),
                accepted=False,
                applied=current_thread.status == ThreadStatus.CANCELLED.value,
                action_status=claim.result_status,
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.CONFLICT,
            )
        return CancelResult(
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


async def _elect_cancel_authority(
    db: AsyncSession,
    thread: ThreadModel,
    claim: ControlActionClaim,
    expectation: ThreadWriteExpectation,
    context: _CancelContext,
) -> CancelResult | None:
    thread_id = context.thread_id
    thread_status = context.thread_status
    response_idempotency_key = context.response_idempotency_key
    already_owned = (
        expectation.status is ThreadStatus.CANCELLING
        and expectation.authority.action_type is ControlActionType.CANCEL
        and expectation.authority.action_receipt_id == claim.dispatch_id
    )
    election = (
        None
        if already_owned
        else await elect_thread_status(
            db,
            thread_id,
            expectation=expectation,
            status=ThreadStatus.CANCELLING,
            successor=successor_thread_write_authority(
                expectation,
                action_type=ControlActionType.CANCEL,
                action_receipt_id=claim.dispatch_id,
            ),
        )
    )
    if election is not None and election.outcome is not ThreadStatusElectionOutcome.WON:
        await db.rollback()
        if election.outcome is ThreadStatusElectionOutcome.NOT_FOUND:
            return CancelResult(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=False,
                thread_status="",
                error_detail="Thread disappeared during cancellation election",
                accepted=False,
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.NOT_FOUND,
            )
        if election.outcome is ThreadStatusElectionOutcome.RECEIPT_MISMATCH:
            return CancelResult(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=False,
                thread_status=thread_status,
                error_detail="Cancellation receipt does not match its durable action",
                accepted=False,
                idempotency_key=response_idempotency_key,
                failure_type=FailureType.CONFLICT,
            )
        await db.refresh(thread)
        eligibility = can_cancel(thread.status)
        if eligibility.already_cancelled:
            failure_type = None
            error_detail = None
        elif eligibility.allowed:
            failure_type = FailureType.CONFLICT
            error_detail = "Thread authority changed during cancellation election"
        else:
            failure_type = FailureType.TERMINAL
            error_detail = eligibility.reason
        return CancelResult(
            action_id=claim.action_id,
            thread_id=thread_id,
            cancelled=eligibility.already_cancelled,
            thread_status=thread.status,
            error_detail=error_detail,
            accepted=False,
            applied=eligibility.already_cancelled,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            idempotency_key=response_idempotency_key,
            failure_type=failure_type,
        )
    if election is not None:
        await mark_cancel_requested(db, thread_id)
    await finalize_control_action_acceptance(db, claim)
    return None


async def _dispatch_cancellation(
    db: AsyncSession,
    thread: ThreadModel,
    claim: ControlActionClaim,
    dispatch: DispatchRequest,
    context: _CancelContext,
) -> CancelResult:
    runtime = context.runtime
    thread_id = context.thread_id
    response_idempotency_key = context.response_idempotency_key
    dispatch = dispatch.model_copy(update={"dispatch_id": claim.dispatch_id})
    logger.info(
        "Dispatching cancel dispatch_id=%s for thread %s",
        dispatch.dispatch_id,
        thread_id,
        extra={
            "thread_id": thread_id,
            "dispatch_id": dispatch.dispatch_id,
            "action": dispatch.action,
        },
    )

    outcome = await safe_dispatch(
        runtime.worker_client,
        dispatch,
        runtime.circuit_breaker,
        runtime.worker_spawner,
        bypass_circuit_breaker=True,
        trace_headers=runtime.trace_headers,
    )

    if not outcome.success:
        _policy, typed_failure = evaluate_dispatch_failure(outcome.failure_type)
        if typed_failure is None:
            raise RuntimeError("failed dispatch carries no failure type")
        settlement = await record_dispatch_failure(
            db, claim, typed_failure, detail=outcome.detail
        )
        if settlement is DispatchFailureDisposition.AMBIGUOUS_DELIVERY:
            # UNREACHABLE is ambiguous: the worker may have scheduled the
            # cancellation before the acknowledgement was lost.  Keep both the
            # durable lease and the cancelling projection so restart/TTL
            # reconciliation can converge on the accepted intent.  Returning a
            # rejection here would contradict the journal and invite the caller
            # to submit a competing action.
            await db.commit()
            return CancelResult(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=True,
                thread_status=ThreadStatus.CANCELLING.value,
                accepted=True,
                applied=False,
                action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
                idempotency_key=response_idempotency_key,
            )
        if settlement is DispatchFailureDisposition.APPLICATION_WON:
            await db.refresh(thread)
            await db.commit()
            return CancelResult(
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
            return CancelResult(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=False,
                thread_status=thread.status,
                accepted=False,
                applied=False,
                action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
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
                "dispatch_id": dispatch.dispatch_id,
                "action": dispatch.action,
            },
        )
        await record_undelivered_dispatch(
            db,
            thread_id,
            reason=outcome.detail or "Cancel dispatch was not delivered",
        )
        await db.commit()
        return CancelResult(
            action_id=claim.action_id,
            thread_id=thread_id,
            cancelled=False,
            thread_status=ThreadStatus.CANCELLING.value,
            accepted=False,
            applied=False,
            action_status=ControlActionResultStatus.REJECTED_INVALID_STATE.value,
            idempotency_key=response_idempotency_key,
            failure_type=typed_failure,
        )

    await db.commit()
    return CancelResult(
        action_id=claim.action_id,
        thread_id=thread_id,
        cancelled=True,
        thread_status=ThreadStatus.CANCELLING.value,
        accepted=True,
        applied=False,
        action_status=ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value,
        idempotency_key=response_idempotency_key,
    )
