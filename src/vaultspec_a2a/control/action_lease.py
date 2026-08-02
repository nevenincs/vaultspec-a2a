"""Shared durable ownership for gateway-to-worker control dispatches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from ..database import (
    acquire_control_action_lease,
    commit_control_action_lease,
    release_control_action_lease,
    reserve_control_action,
)
from ..thread.dispatch_policy import FailureType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread.enums import ControlActionType

__all__ = [
    "CONTROL_ACTION_LEASE_TTL",
    "ControlActionClaim",
    "claim_control_action",
    "release_definite_non_delivery",
]


CONTROL_ACTION_LEASE_TTL = timedelta(seconds=90)
"""Fresh ownership window before an unapplied dispatch may be redriven."""

_DEFINITE_NON_DELIVERY = frozenset(
    {FailureType.CIRCUIT_OPEN, FailureType.AT_CAPACITY, FailureType.REJECTED}
)


@dataclass(frozen=True, slots=True)
class ControlActionClaim:
    """Immutable caller view of a durable reservation and lease attempt."""

    action_id: str
    dispatch_id: str
    created: bool
    payload_matches: bool
    acquired: bool
    applied: bool
    result_status: str
    claim_token: str | None


async def claim_control_action(
    db: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str,
    idempotency_key: str,
    payload: dict[str, object] | None,
    request_id: str | None = None,
    worker_generation: int = 0,
    now: datetime | None = None,
    lease_ttl: timedelta = CONTROL_ACTION_LEASE_TTL,
) -> ControlActionClaim:
    """Atomically reserve one intention and acquire its renewable dispatch lease.

    A winning lease is committed before this function returns. A replay with a
    fresh lease returns ``acquired=False`` and performs no write. A competing
    payload is reported without acquiring the winner or exposing its body.
    """
    instant = now or datetime.now(UTC)
    reservation = await reserve_control_action(
        db,
        thread_id=thread_id,
        action_type=action_type,
        idempotency_key=idempotency_key,
        request_id=request_id,
        payload=payload,
        worker_generation=worker_generation,
    )
    action = reservation.action
    if action.dispatch_id is None:
        await db.rollback()
        raise RuntimeError("reserved control action has no stable dispatch id")
    # A rollback expires ORM attributes. Snapshot the protocol-facing values
    # before a losing replay rolls its transaction back, otherwise merely
    # building the replay result attempts implicit async I/O outside greenlet
    # context and raises MissingGreenlet.
    action_id = action.id
    dispatch_id = action.dispatch_id
    applied = action.applied_at is not None
    result_status = action.result_status

    claim_token: str | None = None
    acquired = False
    if reservation.payload_matches and action.applied_at is None:
        claim_token = uuid4().hex
        acquired = await acquire_control_action_lease(
            db,
            action_id,
            claim_token=claim_token,
            claim_expires_at=instant + lease_ttl,
            now=instant,
        )

    if acquired and claim_token is not None:
        await commit_control_action_lease(
            db,
            action_id,
            claim_token=claim_token,
        )
    else:
        claim_token = None
        await db.rollback()

    return ControlActionClaim(
        action_id=action_id,
        dispatch_id=dispatch_id,
        created=reservation.created,
        payload_matches=reservation.payload_matches,
        acquired=acquired,
        applied=applied,
        result_status=result_status,
        claim_token=claim_token,
    )


async def release_definite_non_delivery(
    db: AsyncSession,
    claim: ControlActionClaim,
    failure_type: FailureType | None,
) -> bool:
    """Release a lease only when the worker certainly scheduled no task."""
    if claim.claim_token is None or failure_type not in _DEFINITE_NON_DELIVERY:
        return False
    released = await release_control_action_lease(
        db,
        claim.action_id,
        claim_token=claim.claim_token,
    )
    await db.commit()
    return released
