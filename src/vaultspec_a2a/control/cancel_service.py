"""Cancel-thread service logic (Layer 2c — service extraction).

Owns the full cancel workflow: thread validation, idempotency dedup,
control-action creation, repair-state transition, and dispatch.
Does NOT commit, raise HTTPException, or touch FastAPI request state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..control.action_lease import (
    claim_control_action,
    release_definite_non_delivery,
)
from ..control.dispatch import safe_dispatch
from ..control.repair_transitions import (
    mark_cancel_requested,
    record_undelivered_dispatch,
)
from ..database import (
    ThreadStatusElectionOutcome,
    elect_thread_status,
    get_thread,
    successor_thread_write_authority,
    thread_write_expectation,
)
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

__all__ = ["CancelResult", "cancel_thread"]

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
    if result.failure_type is not None:
        raise HTTPException(
            status_code=502, detail=result.error_detail or "Cancel dispatch failed"
        )


async def cancel_thread(
    db: AsyncSession,
    *,
    thread_id: str,
    idempotency_key: str | None,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
    worker_client: httpx.AsyncClient,
    recursion_limit: int,
    trace_headers: dict[str, str] | None = None,
) -> CancelResult:
    """Execute the cancel-thread workflow.

    Returns a :class:`CancelResult` describing what happened.  Commits the
    session before returning — the service owns its transaction boundary.
    """
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

    # Cancellation is a resource transition, so one thread has one durable
    # ownership key even when racing callers supplied different retry labels.
    # The caller's label is still echoed in the response for compatibility;
    # it must not create a second dispatchable intention.
    resolved_idempotency_key = default_cancel_key(thread_id)
    response_idempotency_key = idempotency_key or resolved_idempotency_key
    claim = await claim_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.CANCEL,
        idempotency_key=resolved_idempotency_key,
        payload={"cancel": True},
    )
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
        await db.refresh(thread)
        claim_owns_thread = (
            thread.status == ThreadStatus.CANCELLING.value
            and thread.writer_action_type == ControlActionType.CANCEL.value
            and thread.writer_action_receipt_id == claim.dispatch_id
        )
        if not claim_owns_thread:
            return CancelResult(
                action_id=claim.action_id,
                thread_id=thread_id,
                cancelled=thread.status == ThreadStatus.CANCELLED.value,
                thread_status=thread.status,
                error_detail=(
                    "Cancellation action is leased but does not own thread authority"
                ),
                accepted=False,
                applied=thread.status == ThreadStatus.CANCELLED.value,
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
        await release_definite_non_delivery(db, claim, FailureType.REJECTED)
        await db.commit()
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
    await db.commit()

    dispatch = DispatchRequest(
        dispatch_id=claim.dispatch_id,
        action=to_dispatch_action(ControlActionType.CANCEL),
        thread_id=thread_id,
        recursion_limit=recursion_limit,
    )
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
        worker_client,
        dispatch,
        circuit_breaker,
        worker_spawner,
        bypass_circuit_breaker=True,
        trace_headers=trace_headers,
    )

    if not outcome.success:
        _policy, typed_failure = evaluate_dispatch_failure(outcome.failure_type)
        released = await release_definite_non_delivery(db, claim, typed_failure)
        if not released:
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
