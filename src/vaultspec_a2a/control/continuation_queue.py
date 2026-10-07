"""The durable queue of continuations waiting behind a run's in-flight turn.

A continuation admitted while a run is busy is accepted work that must not
become write authority yet: the turn already running owns the run, and a
second writer would refuse that turn's own terminal. So the reservation here
deliberately stops short of everything a dispatch needs. It takes a position,
it takes the lease that makes two identical admissions one, and it binds no
graph receipt, installs no writer and sends nothing. Promotion is what turns
it into a dispatch, once the predecessor turn's terminal checkpoint evidence
has committed.

Both limits are enforced inside the caller's write transaction, against rows
read under the lock that transaction already holds, so two admissions racing
for the last place cannot both find room.

That lock is the run's own row lock, taken through ``lock_thread_row``. One
admission and one terminal settlement are two transactions deciding opposite
things about the same run, and the only thing that orders them is the lock they
both take on that row before they read it. Without it a settlement can read an
empty queue while an uncommitted admission reads a live run, and both commit -
leaving a waiting turn on a settled run, the one outcome the queue rules say
cannot exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..database import (
    CONTROL_ACTION_LEASE_TTL,
    ControlActionModel,
    clear_lease,
    count_queued_continuations,
    enqueue_continuation,
    get_control_action_by_idempotency_key,
    reject_queued_continuations,
    reserve_control_action,
)
from ..domain_config import domain_config
from ..thread.enums import ControlActionResultStatus, ControlActionType
from ..thread.executable_graph import FrozenGraphDefinition
from .accepted_input import AcceptedActionInput
from .action_lease import take_action_lease

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ContinuationQueueLimits",
    "QueuedContinuation",
    "QueuedContinuationDisposition",
    "QueuedContinuationRequest",
    "open_promoted_continuation",
    "promoted_turn_deadline",
    "promotion_dispatch_pending",
    "refuse_queued_continuations",
    "reserve_queued_continuation",
    "run_lifetime_deadline",
    "served_continuation_queue_limits",
]

logger = logging.getLogger(__name__)

_QUEUED = ControlActionResultStatus.QUEUED.value
_CONTINUATION = ControlActionType.MESSAGE_FOLLOWUP_REQUESTED


@dataclass(frozen=True, slots=True)
class ContinuationQueueLimits:
    """How many continuations may wait, per run and across the service."""

    per_run_depth: int
    service_cap: int


def served_continuation_queue_limits() -> ContinuationQueueLimits:
    """Return the configured per-run depth and service-wide cap."""
    return ContinuationQueueLimits(
        per_run_depth=domain_config.run_continuation_queue_depth,
        service_cap=domain_config.run_continuation_service_queue_cap,
    )


def run_lifetime_deadline(run_created_at: datetime) -> datetime:
    """Return the instant past which this run may run no further turn.

    One bound for the whole run rather than one per turn: a queue that
    re-derived a fresh budget at every promotion would let a caller keep a run
    alive indefinitely one continuation at a time.
    """
    return run_created_at + timedelta(seconds=domain_config.max_run_lifetime_seconds)


class QueuedContinuationDisposition(StrEnum):
    """What one admission attempt did to the queue."""

    QUEUED = "queued"
    REPLAYED = "replayed"
    CONFLICT = "conflict"
    QUEUE_FULL = "queue_full"


@dataclass(frozen=True, slots=True)
class QueuedContinuation:
    """The outcome of one admission attempt and the place it was given.

    *result_status* is the journal row's own current status, which a replay
    has to carry: a turn admitted a moment ago is still waiting, one admitted
    before the predecessor ended has been promoted, and one whose turn has run
    is applied. Reporting every replay as "waiting" would tell a caller
    retrying after a lost response that its turn had not started yet.
    """

    disposition: QueuedContinuationDisposition
    action_id: str
    dispatch_id: str
    position: int | None
    claim_token: str | None
    result_status: str = _QUEUED


@dataclass(frozen=True, slots=True)
class QueuedContinuationRequest:
    """One continuation offered to a busy run, with its accepted envelope.

    *payload* is the frozen accepted dispatch input the promoted turn will be
    rebuilt from, so the turn carries its own complete envelope rather than
    reloading presets at promotion. *lifetime_deadline_at* is the run's total
    lifetime bound, which is what a waiting reservation is given: a turn's own
    budget would expire while the predecessor is still running.
    """

    thread_id: str
    idempotency_key: str
    payload: dict[str, object]
    dispatch_id: str
    lifetime_deadline_at: datetime
    limits: ContinuationQueueLimits
    now: datetime | None = None
    lease_ttl: timedelta = CONTROL_ACTION_LEASE_TTL


def promoted_turn_deadline(
    action: ControlActionModel,
    *,
    promoted_at: datetime,
    lifetime_deadline_at: datetime,
) -> datetime | None:
    """Re-derive the promoted turn's execution deadline from its own envelope.

    Read from the envelope the admission froze, never from a preset reloaded
    now: the turn was accepted against one program and must run under that
    one. The run's remaining lifetime caps it, so the last turn a run is
    allowed gets whatever time is left rather than a fresh full budget that
    would carry it past the bound. ``None`` says the stored envelope is not a
    usable ingest turn, which is a refusal to promote rather than a deadline
    to invent.
    """
    if action.payload_json is None:
        return None
    try:
        accepted = AcceptedActionInput.model_validate_json(action.payload_json)
        if accepted.dispatch["action"] != "ingest":
            return None
        definition = FrozenGraphDefinition.model_validate(
            accepted.dispatch["graph_definition"]
        )
        timeout = definition.run_timeout_seconds
    except (ValidationError, ValueError):
        return None
    return min(promoted_at + timedelta(seconds=timeout), lifetime_deadline_at)


async def refuse_queued_continuations(
    session: AsyncSession, *, thread_id: str, refused_at: datetime, reason: str
) -> int:
    """Settle every continuation still waiting on a run that will not promote.

    A run about to enter a terminal state can never promote what is queued on
    it, and a queued row left behind on one would wait for an event that
    cannot arrive. Settling each as an invalid-state refusal records the
    outcome where the caller's replay already looks, which is the difference
    between refusing accepted work and losing it. The place each was given
    stays, so the record says what was refused and where it sat.
    """
    refused = await reject_queued_continuations(
        session, thread_id=thread_id, rejected_at=refused_at
    )
    if refused:
        logger.warning(
            "Refused %d continuation(s) waiting on %s: %s",
            refused,
            thread_id,
            reason,
            extra={
                "thread_id": thread_id,
                "reason": reason,
                "action": "continuation_refused",
            },
        )
    return refused


def promotion_dispatch_pending(
    action: ControlActionModel, *, observed_at: datetime
) -> bool:
    """Whether this action is a promoted turn the dispatcher still owes.

    Three durable facts, all on the row: it came out of the queue, nothing has
    applied it, and its own deadline has not passed. The deadline is the bound
    on how long the promotion dispatcher's obligation lasts, and it is derived
    from the run rather than from a flat global, which is what the
    abandoned-transition rule requires of any such bound.
    """
    return (
        action.queue_position is not None
        and action.applied_at is None
        and action.recovery_deadline_at is not None
        and action.recovery_deadline_at > observed_at
    )


def open_promoted_continuation(
    action: ControlActionModel, *, deadline_at: datetime
) -> None:
    """Turn one waiting reservation into accepted work awaiting delivery.

    Called before the writer and the receipt are installed, because a queued
    row may hold neither: the journal's own invariant refuses a reservation
    that owns anything, so the status has to stop saying "waiting" first.

    The lease is released rather than held. Promotion is not the dispatcher -
    the durable recovery owner delivers - and a lease kept here would make the
    promoted turn wait out its own ownership window before anyone could send
    it. The position stays, as the durable record of where this turn came
    from.
    """
    action.result_status = ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value
    action.recovery_deadline_at = deadline_at
    clear_lease(action)


async def reserve_queued_continuation(
    session: AsyncSession, request: QueuedContinuationRequest
) -> QueuedContinuation:
    """Reserve one waiting continuation inside the caller's write transaction.

    Never commits and never dispatches. A repeat of the same idempotency key
    replays the place the first attempt was given; a different body under that
    key conflicts; a full queue refuses. The caller commits the acceptance
    with everything else it owes.
    """
    instant = request.now or datetime.now(UTC)
    # Locked before the limits are read: a replay must replay even when the
    # queue is full, and a competing admission must wait for this decision
    # rather than counting the same free place twice.
    held = await get_control_action_by_idempotency_key(
        session,
        thread_id=request.thread_id,
        idempotency_key=request.idempotency_key,
        lock=True,
    )
    if held is None:
        # Asked only where a row is about to be created. A replay reserves
        # nothing, so a run whose lifetime has since run out still answers for
        # the turn it already took rather than refusing to recognise it.
        if request.lifetime_deadline_at <= instant:
            raise ValueError("a waiting continuation needs a lifetime still to run")
        refusal = await _queue_refusal(session, request)
        if refusal is not None:
            return refusal
    reservation = await reserve_control_action(
        session,
        thread_id=request.thread_id,
        action_type=_CONTINUATION,
        idempotency_key=request.idempotency_key,
        payload=request.payload,
        dispatch_id=request.dispatch_id,
        recovery_deadline_at=request.lifetime_deadline_at,
    )
    action = reservation.action
    if action.dispatch_id is None:
        raise RuntimeError("reserved continuation has no stable dispatch id")
    if not reservation.payload_matches:
        return QueuedContinuation(
            QueuedContinuationDisposition.CONFLICT,
            action.id,
            action.dispatch_id,
            action.queue_position,
            None,
            action.result_status,
        )
    if not reservation.created:
        return QueuedContinuation(
            QueuedContinuationDisposition.REPLAYED,
            action.id,
            action.dispatch_id,
            action.queue_position,
            None,
            action.result_status,
        )
    claim_token = await take_action_lease(
        session, action.id, now=instant, ttl=request.lease_ttl
    )
    position = await enqueue_continuation(session, action)
    return QueuedContinuation(
        QueuedContinuationDisposition.QUEUED,
        action.id,
        action.dispatch_id,
        position,
        claim_token,
    )


async def _queue_refusal(
    session: AsyncSession, request: QueuedContinuationRequest
) -> QueuedContinuation | None:
    """Refuse when either configured limit is already spent."""
    per_run = await count_queued_continuations(session, thread_id=request.thread_id)
    service = await count_queued_continuations(session)
    if per_run >= request.limits.per_run_depth or service >= request.limits.service_cap:
        return QueuedContinuation(
            QueuedContinuationDisposition.QUEUE_FULL,
            "",
            request.dispatch_id,
            None,
            None,
        )
    return None
