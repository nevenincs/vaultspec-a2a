"""Message follow-up service — business logic extracted from the messages route.

Owns the full send-followup-message workflow (thread lookup, eligibility,
queue reservation) without any FastAPI or HTTP coupling.  The route handler
remains a thin adapter that parses the request, calls this service, and maps
the result to an HTTP response.

A follow-up is never dispatched from here. A run that admits one is a run with
a turn already executing, and that turn owns the run's write authority: a
second writer installed now would refuse the executing turn's own terminal.
So this verb reserves a WAITING turn - a journal action with a queue position
and a lease, no graph receipt, no writer, no dispatch - and the promotion path
turns it into a dispatch once the predecessor's terminal checkpoint evidence
commits.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, Unpack

from ..database import (
    begin_write_transaction,
    idempotency_key_admitted,
    outstanding_permission_pause,
)
from ..thread.dispatch_policy import FailureType
from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
    ThreadStatus,
)
from ..thread.message_policy import (
    ParkedPause,
    PauseAnswerability,
    can_send_followup,
)
from .accepted_input import freeze_accepted_input
from .action_lease import ControlActionOutcome
from .continuation_queue import (
    QueuedContinuationDisposition,
    QueuedContinuationRequest,
    lock_run_for_continuation_decision,
    reserve_queued_continuation,
    run_lifetime_deadline,
    served_continuation_queue_limits,
)
from .leased_dispatch import DispatchRefusal, build_followon_dispatch

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["send_followup_message"]

logger = logging.getLogger(__name__)

_REPLAYED = QueuedContinuationDisposition.REPLAYED

#: What each queue disposition means to a caller of this verb. Spelled as a
#: mapping rather than a chain of branches so a disposition added to the queue
#: cannot be answered here by falling through to "accepted".
_REFUSALS: dict[QueuedContinuationDisposition, tuple[FailureType, str]] = {
    QueuedContinuationDisposition.CONFLICT: (
        FailureType.CONFLICT,
        "Idempotency key is already bound to a different message",
    ),
    QueuedContinuationDisposition.QUEUE_FULL: (
        FailureType.QUEUE_FULL,
        "The run already holds the continuations it may hold, or the service "
        "does. Nothing was reserved; retry once the waiting turn has run.",
    ),
}


def _now() -> datetime:
    """Return the instant the run's remaining lifetime is measured against."""
    return datetime.now(UTC)


async def _parked_pause(
    db: AsyncSession, thread_id: str, status: str
) -> ParkedPause | None:
    """Read which pause a parked run holds, so the refusal can name its verb.

    Asked of the journal rather than guessed from the status, because
    INPUT_REQUIRED is one status over two unrelated pauses with two unrelated
    respond verbs. An absent permission row is itself the answer: a parked run
    with none is parked at a clarification interrupt, which lives in the
    checkpoint and is disclosed on run-status.
    """
    if status != ThreadStatus.INPUT_REQUIRED.value:
        return None
    outstanding = await outstanding_permission_pause(db, thread_id=thread_id)
    if outstanding is None:
        return ParkedPause(run_id=thread_id)
    request_id, request_status = outstanding
    return ParkedPause(
        run_id=thread_id,
        permission_request_id=request_id,
        answerability=(
            PauseAnswerability.AWAITING_ANSWER
            if request_status == PermissionRequestStatus.PENDING.value
            else PauseAnswerability.APPLYING_ANSWER
        ),
    )


def _refused(
    thread_id: str,
    thread_status: str,
    failure_type: FailureType,
    detail: str,
    action_id: str | None = None,
) -> ControlActionOutcome:
    """Report one refusal that reserved nothing and queued nothing."""
    return ControlActionOutcome(
        action_id=action_id,
        thread_id=thread_id,
        thread_status=thread_status,
        error_detail=detail,
        failure_type=failure_type,
    )


class _FollowupMessageArgs(TypedDict):
    thread_id: str
    content: str
    agent_id: str
    # No default is derived for this verb. Two deliberate identical
    # continuations are two turns, and a key derived from the content folds the
    # second into the first and answers it as an already-accepted replay.
    idempotency_key: str


async def send_followup_message(
    db: AsyncSession, **options: Unpack[_FollowupMessageArgs]
) -> ControlActionOutcome:
    """Reserve a follow-up turn behind the one this run is executing.

    Returns a :class:`ControlActionOutcome` describing the outcome.  Never raises
    HTTP exceptions — the caller is responsible for translating the result
    into an appropriate HTTP response.  Commits the session before returning.

    ``accepted`` says a turn was taken; ``queue_position`` is the place it was
    given, counting from one, and it is the same place a replay of the same
    key reports. ``action_status`` is the journal row's own status, so a
    replay says what became of the turn rather than restating that it was
    once queued. A refusal reserved nothing and carries its ``failure_type``.
    """
    # -- Thread lookup & guard -------------------------------------------
    # The run's row is locked before its status is read, and held until this
    # transaction ends. That lock is the single ordering point between this
    # admission and a terminal settlement: a continuation either queues ahead
    # of the settlement transaction, which then promotes or refuses it, or it
    # waits and reads the settled status and is refused here. There is no
    # third outcome, and that is what keeps a waiting turn from being left on
    # a run that has ended.
    await begin_write_transaction(db)
    # Every refusal before the reservation wrote nothing; each releases the
    # lock before it returns.
    thread = await lock_run_for_continuation_decision(
        db, thread_id=options["thread_id"]
    )
    if thread is None:
        await db.rollback()
        return _refused(
            options["thread_id"], "", FailureType.NOT_FOUND, "Run not found"
        )

    # Read before any rollback below expires the loaded row.
    thread_status = thread.status
    created_at = thread.created_at
    # A repeat of an accepted key is not a new offer, so the run's current
    # state is not an answer to it: the caller is asking what became of a turn
    # it already sent. Eligibility decides new work only.
    replaying = await idempotency_key_admitted(
        db,
        thread_id=options["thread_id"],
        idempotency_key=options["idempotency_key"],
    )
    eligibility = can_send_followup(
        thread_status,
        parked_on=await _parked_pause(db, options["thread_id"], thread_status),
    )
    if not replaying and not eligibility.allowed:
        # Nothing has been reserved at this point, so the refusal leaves the run
        # exactly as it was: no journal action, no writer, no dispatch. The
        # refusal is typed by the policy that decided it rather than re-derived
        # from the status here, so one status cannot mean two things.
        await db.rollback()
        if eligibility.failure_type is None:
            raise RuntimeError("an ineligible follow-up carries no refusal type")
        return _refused(
            options["thread_id"],
            thread_status,
            eligibility.failure_type,
            eligibility.reason or "The run cannot take this now",
        )

    logger.info(
        "Message received for thread %s: %d chars",
        options["thread_id"],
        len(options["content"]),
    )

    # -- The accepted envelope the promoted turn is rebuilt from ----------
    # Complete and frozen at admission: the turn was offered against this
    # program and must run under this one, including its recursion budget,
    # which is decided now rather than read from a service-wide default at
    # some later moment. A follow-up inherits the active project the run was
    # created with; it is never re-derived and never defaulted, so a run that
    # names none is refused rather than sited wherever the worker started.
    dispatch = await build_followon_dispatch(
        db,
        thread_id=options["thread_id"],
        thread_metadata=thread.thread_metadata,
        action=ControlActionType.INGEST,
        agent_id=options["agent_id"],
        content=options["content"],
    )
    if isinstance(dispatch, DispatchRefusal):
        await db.rollback()
        return _refused(
            options["thread_id"], thread_status, dispatch.failure_type, dispatch.reason
        )

    lifetime_deadline_at = run_lifetime_deadline(created_at)
    if not replaying and lifetime_deadline_at <= _now():
        # The run has no lifetime left to run another turn in, so a reservation
        # here would be accepted work the promotion bound is already committed
        # to refusing. Say so now rather than take it and reject it later. A
        # replay reserves nothing, so the bound does not apply to one.
        await db.rollback()
        return _refused(
            options["thread_id"],
            thread_status,
            FailureType.TERMINAL,
            "The run's total lifetime is spent, so it can take no further "
            "turn. Start a new run naming this one as its predecessor.",
        )

    # -- Durable reservation, with no receipt, writer or dispatch ---------
    reserved = await reserve_queued_continuation(
        db,
        QueuedContinuationRequest(
            thread_id=options["thread_id"],
            idempotency_key=options["idempotency_key"],
            payload=freeze_accepted_input(
                dispatch,
                intent={"content": options["content"], "agent_id": options["agent_id"]},
            ),
            dispatch_id=dispatch.dispatch_id,
            lifetime_deadline_at=lifetime_deadline_at,
            limits=served_continuation_queue_limits(),
        ),
    )
    refusal = _REFUSALS.get(reserved.disposition)
    if refusal is not None:
        await db.rollback()
        failure_type, detail = refusal
        return _refused(
            options["thread_id"],
            thread_status,
            failure_type,
            detail,
            reserved.action_id,
        )
    await db.commit()
    logger.info(
        "%s a continuation for thread %s at position %s",
        "Replayed" if reserved.disposition is _REPLAYED else "Queued",
        options["thread_id"],
        reserved.position,
        extra={
            "thread_id": options["thread_id"],
            "dispatch_id": reserved.dispatch_id,
            "queue_position": reserved.position,
            "action": (
                "continuation_replayed"
                if reserved.disposition is _REPLAYED
                else "continuation_queued"
            ),
        },
    )
    return ControlActionOutcome(
        action_id=reserved.action_id,
        thread_id=options["thread_id"],
        thread_status=thread_status,
        accepted=True,
        applied=reserved.result_status == ControlActionResultStatus.APPLIED.value,
        queue_position=reserved.position,
        action_status=reserved.result_status,
    )
