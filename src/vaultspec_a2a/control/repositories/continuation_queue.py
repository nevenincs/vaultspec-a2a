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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select

from ...database import (
    ControlActionModel,
    acquire_control_action_lease,
    reserve_control_action,
)
from ...domain_config import domain_config
from ...thread.enums import ControlActionResultStatus, ControlActionType
from ..action_lease import CONTROL_ACTION_LEASE_TTL

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ContinuationQueueLimits",
    "QueuedContinuation",
    "QueuedContinuationDisposition",
    "QueuedContinuationRequest",
    "count_queued_continuations",
    "count_service_queued_continuations",
    "next_queue_position",
    "read_next_queued_continuation",
    "reserve_queued_continuation",
    "run_lifetime_deadline",
    "served_continuation_queue_limits",
]

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
    """The outcome of one admission attempt and the place it was given."""

    disposition: QueuedContinuationDisposition
    action_id: str
    dispatch_id: str
    position: int | None
    claim_token: str | None


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


async def count_queued_continuations(session: AsyncSession, *, thread_id: str) -> int:
    """Return how many continuations are waiting on one run."""
    return (
        await session.execute(
            select(func.count())
            .select_from(ControlActionModel)
            .where(
                ControlActionModel.thread_id == thread_id,
                ControlActionModel.result_status == _QUEUED,
            )
        )
    ).scalar_one()


async def count_service_queued_continuations(session: AsyncSession) -> int:
    """Return how many continuations are waiting across every run."""
    return (
        await session.execute(
            select(func.count())
            .select_from(ControlActionModel)
            .where(ControlActionModel.result_status == _QUEUED)
        )
    ).scalar_one()


async def next_queue_position(session: AsyncSession, *, thread_id: str) -> int:
    """Return the position the next continuation on this run would take.

    Derived from the highest position still waiting rather than from a count,
    so a queue drained out of order never hands a second caller a place that
    is already taken.
    """
    highest = (
        await session.execute(
            select(func.max(ControlActionModel.queue_position)).where(
                ControlActionModel.thread_id == thread_id,
                ControlActionModel.result_status == _QUEUED,
            )
        )
    ).scalar_one()
    return 1 if highest is None else int(highest) + 1


async def read_next_queued_continuation(
    session: AsyncSession, *, thread_id: str
) -> ControlActionModel | None:
    """Return the continuation this run must promote first, if any.

    Lowest position wins, and the row is locked for update: the reader is
    about to promote it inside the same transaction, and a second promoter
    must wait rather than read the same winner.
    """
    return await session.scalar(
        select(ControlActionModel)
        .where(
            ControlActionModel.thread_id == thread_id,
            ControlActionModel.result_status == _QUEUED,
        )
        .order_by(ControlActionModel.queue_position, ControlActionModel.requested_at)
        .limit(1)
        .with_for_update()
    )


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
    if request.lifetime_deadline_at <= instant:
        raise ValueError("a waiting continuation needs a lifetime still to run")
    # Locked before the limits are read: a replay must replay even when the
    # queue is full, and a competing admission must wait for this decision
    # rather than counting the same free place twice.
    held = await session.scalar(
        select(ControlActionModel)
        .where(
            ControlActionModel.thread_id == request.thread_id,
            ControlActionModel.idempotency_key == request.idempotency_key,
        )
        .with_for_update()
    )
    if held is None:
        refusal = await _queue_refusal(session, request)
        if refusal is not None:
            return refusal
    position = (
        await next_queue_position(session, thread_id=request.thread_id)
        if held is None
        else held.queue_position
    )
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
        )
    if not reservation.created:
        return QueuedContinuation(
            QueuedContinuationDisposition.REPLAYED,
            action.id,
            action.dispatch_id,
            action.queue_position,
            None,
        )
    claim_token = uuid4().hex
    acquired = await acquire_control_action_lease(
        session,
        action.id,
        claim_token=claim_token,
        claim_expires_at=instant + request.lease_ttl,
        now=instant,
    )
    action.result_status = _QUEUED
    action.queue_position = position
    await session.flush()
    return QueuedContinuation(
        QueuedContinuationDisposition.QUEUED,
        action.id,
        action.dispatch_id,
        position,
        claim_token if acquired else None,
    )


async def _queue_refusal(
    session: AsyncSession, request: QueuedContinuationRequest
) -> QueuedContinuation | None:
    """Refuse when either configured limit is already spent."""
    per_run = await count_queued_continuations(session, thread_id=request.thread_id)
    service = await count_service_queued_continuations(session)
    if per_run >= request.limits.per_run_depth or service >= request.limits.service_cap:
        return QueuedContinuation(
            QueuedContinuationDisposition.QUEUE_FULL,
            "",
            request.dispatch_id,
            None,
            None,
        )
    return None
