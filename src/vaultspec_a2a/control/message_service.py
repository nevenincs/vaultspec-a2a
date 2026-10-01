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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, Unpack

from ..database import begin_write_transaction
from ..ipc.schemas import DispatchRequest, to_dispatch_action
from ..thread.dispatch_policy import FailureType
from ..thread.enums import ControlActionType
from ..thread.message_policy import can_send_followup
from ._thread_metadata import dispatchable_workspace_root
from .accepted_input import freeze_accepted_input
from .execution_authority import ExecutionAuthorityError, resolve_execution_authority
from .graph_definition import read_accepted_graph_definition
from .repositories.continuation_queue import (
    QueuedContinuationDisposition,
    QueuedContinuationRequest,
    continuation_already_admitted,
    lock_run_for_continuation_decision,
    reserve_queued_continuation,
    run_lifetime_deadline,
    served_continuation_queue_limits,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["MessageResult", "send_followup_message"]

logger = logging.getLogger(__name__)

_REPLAYED = QueuedContinuationDisposition.REPLAYED

#: What each queue disposition means to a caller of this verb. Spelled as a
#: mapping rather than a chain of branches so a disposition added to the queue
#: repository cannot be answered here by falling through to "accepted".
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


@dataclass(frozen=True, slots=True)
class MessageResult:
    """What one follow-up offer did to a run's continuation queue.

    ``queued`` says a turn was taken; ``queue_position`` is the place it was
    given, counting from one, and it is the same place a replay of the same
    key reports. ``action_status`` is the journal row's own status, so a
    replay says what became of the turn rather than restating that it was
    once queued. A refusal carries none of the three and reserved nothing.
    """

    action_id: str
    thread_id: str
    thread_status: str
    queued: bool
    queue_position: int | None = None
    action_status: str = ""
    error_detail: str | None = None
    failure_type: FailureType | None = None


def _now() -> datetime:
    """Return the instant the run's remaining lifetime is measured against."""
    return datetime.now(UTC)


def _refused(
    thread_id: str,
    thread_status: str,
    failure_type: FailureType,
    detail: str,
    action_id: str = "",
) -> MessageResult:
    """Report one refusal that reserved nothing and queued nothing."""
    return MessageResult(
        action_id=action_id,
        thread_id=thread_id,
        thread_status=thread_status,
        queued=False,
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
) -> MessageResult:
    """Reserve a follow-up turn behind the one this run is executing.

    Returns a :class:`MessageResult` describing the outcome.  Never raises
    HTTP exceptions — the caller is responsible for translating the result
    into an appropriate HTTP response.  Commits the session before returning.
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
    replaying = await continuation_already_admitted(
        db,
        thread_id=options["thread_id"],
        idempotency_key=options["idempotency_key"],
    )
    eligibility = can_send_followup(thread_status)
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

    # The losing reservation path rolls its transaction back, which expires ORM
    # state. Snapshot every value needed afterwards before entering the queue
    # repository so a concurrent replay or conflict never triggers implicit
    # async I/O.
    thread_metadata = thread.thread_metadata
    try:
        graph_definition = await read_accepted_graph_definition(
            db, options["thread_id"]
        )
        execution_authority = resolve_execution_authority(thread_metadata)
    except (ExecutionAuthorityError, ValueError) as exc:
        await db.rollback()
        return _refused(
            options["thread_id"],
            thread_status,
            FailureType.INCOMPATIBLE_STATE,
            str(exc),
        )

    # -- Metadata extraction ---------------------------------------------
    # A follow-up inherits the active project the run was created with; it is
    # never re-derived and never defaulted. Degrading an unreadable or absent
    # workspace root to None here used to dispatch the turn anyway, and the
    # provider layer then sited the agent - and its filesystem sandbox - in
    # whatever directory the worker was started in. Refuse instead.
    workspace_root = dispatchable_workspace_root(thread_metadata)
    if workspace_root is None:
        await db.rollback()
        return _refused(
            options["thread_id"],
            thread_status,
            FailureType.NO_ACTIVE_PROJECT,
            "run carries no active project: its stored metadata names no "
            "workspace_root, so a follow-up cannot be sited. Start a new run.",
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

    # -- The accepted envelope the promoted turn is rebuilt from ----------
    # Complete and frozen at admission: the turn was offered against this
    # program and must run under this one, including its recursion budget,
    # which comes from the run's own accepted graph definition rather than
    # from a service-wide default read at some later moment.
    dispatch = DispatchRequest(
        action=to_dispatch_action(ControlActionType.INGEST),
        thread_id=options["thread_id"],
        agent_id=options["agent_id"],
        content=options["content"],
        team_preset=graph_definition.team_id,
        graph_definition=graph_definition,
        workspace_root=workspace_root,
        recursion_limit=graph_definition.recursion_limit,
        model_assignment=execution_authority.model_assignment,
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
    return MessageResult(
        action_id=reserved.action_id,
        thread_id=options["thread_id"],
        thread_status=thread_status,
        queued=True,
        queue_position=reserved.position,
        action_status=reserved.result_status,
    )
