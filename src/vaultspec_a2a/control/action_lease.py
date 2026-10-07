"""Shared durable ownership for gateway-to-worker control dispatches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from ..database import (
    CONTROL_ACTION_LEASE_TTL,
    ControlActionModel,
    ControlActionReservation,
    acquire_control_action_lease,
    commit_control_action_lease,
    get_control_action,
    lock_thread_row,
    new_claim_token,
    release_control_action_lease,
    reserve_control_action,
    thread_write_expectation,
)
from ..thread.dispatch_policy import FailureType
from ..thread.enums import (
    RECOVERY_ACTION_TYPES,
    ControlActionResultStatus,
    ControlActionType,
    RecoveryCondition,
)
from .dispatch_receipts import prepare_graph_action_receipt
from .recovery import RecoveryAuthorityLostError, record_recovery_failure

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..thread import RunWriteAuthority, ThreadWriteExpectation

__all__ = [
    "DEFINITE_NON_DELIVERY",
    "ControlActionClaim",
    "ControlActionClaimRequest",
    "ControlActionOutcome",
    "DispatchFailureDisposition",
    "finalize_control_action_acceptance",
    "prepare_control_action_claim",
    "record_dispatch_failure",
    "take_action_lease",
]


DEFINITE_NON_DELIVERY = frozenset(
    {FailureType.CIRCUIT_OPEN, FailureType.AT_CAPACITY, FailureType.REJECTED}
)
"""The failures that prove the dispatch did not arrive, so ownership is given back.

Every other failure is ambiguous and keeps its claim until reconciliation or
expiry. A worker busy with this very run is the clearest case: it is reporting
work in flight, so releasing the claim would invite a second dispatcher to
redeliver what the worker is already executing. Live dispatch and recovery read
this one set, because the rule is one rule and two copies of it drift.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlActionClaim:
    """Immutable caller view of a durable reservation and lease attempt."""

    action_id: str
    dispatch_id: str
    created: bool
    payload_matches: bool
    acquired: bool
    authority_matches: bool
    applied: bool
    result_status: str
    claim_token: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlActionClaimRequest:
    """Accepted dispatch identity, recovery deadline, and receipt expectation."""

    thread_id: str
    action_type: ControlActionType | str
    idempotency_key: str
    payload: dict[str, object] | None
    dispatch_id: str
    request_id: str | None = None
    worker_generation: int = 0
    now: datetime | None = None
    lease_ttl: timedelta = CONTROL_ACTION_LEASE_TTL
    write_expectation: ThreadWriteExpectation | None = None
    recovery_timeout_seconds: int | None = None
    recovery_deadline_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlActionOutcome:
    """What one run-control verb did, in the terms every verb shares.

    Permission answers, clarification answers, cancellations and follow-up
    messages each end by reporting the journal action they reserved or replayed
    and whether it was taken. The record defaults to a refusal that reserved
    nothing, so a verb names only what it learned. A refusal about the request
    itself carries its own ``error_status_code``; one that met a dispatch
    outcome carries only its ``failure_type``, and the protocol mapping chooses
    the status.

    ``approval_status`` belongs to permission answers, ``thread_status`` and
    ``cancelled`` to cancellation, ``thread_status`` and ``queue_position`` to
    follow-up messages. A verb that has no use for one leaves it at its default.
    """

    thread_id: str
    request_id: str = ""
    action_id: str | None = None
    idempotency_key: str | None = None
    accepted: bool = False
    applied: bool = False
    action_status: str = ControlActionResultStatus.REJECTED_INVALID_STATE.value
    dispatched: bool = False
    approval_status: str | None = None
    thread_status: str = ""
    cancelled: bool = False
    queue_position: int | None = None
    error_detail: str | None = None
    error_status_code: int | None = None
    failure_type: FailureType | None = None


class DispatchFailureDisposition(StrEnum):
    """Exact durable result of settling one failed dispatch attempt."""

    DEFINITE_NON_DELIVERY = "definite_non_delivery"
    AMBIGUOUS_DELIVERY = "ambiguous_delivery"
    AUTHORITY_LOST = "authority_lost"
    DEADLINE_EXPIRED = "deadline_expired"
    APPLICATION_WON = "application_won"


def _resolved_recovery_deadline(
    action_type: ControlActionType,
    instant: datetime,
    timeout_seconds: int | None,
    deadline_at: datetime | None,
) -> datetime | None:
    if action_type not in RECOVERY_ACTION_TYPES:
        if timeout_seconds is not None or deadline_at is not None:
            raise ValueError("non-recoverable action cannot carry a recovery deadline")
        return None
    if (timeout_seconds is None) == (deadline_at is None):
        raise ValueError(
            "recoverable action requires exactly one run timeout or deadline"
        )
    if timeout_seconds is not None:
        if timeout_seconds < 1:
            raise ValueError("recovery_timeout_seconds must be positive")
        deadline_at = instant + timedelta(seconds=timeout_seconds)
    if deadline_at is None or deadline_at <= instant:
        raise ValueError("recovery deadline must be later than acceptance")
    return deadline_at


async def take_action_lease(
    db: AsyncSession, action_id: str, *, now: datetime, ttl: timedelta
) -> str | None:
    """Take the unapplied action's lease for *ttl* under a fresh claim token.

    Returns the token when this call won the lease, and ``None`` when another
    dispatcher holds it.
    """
    claim_token = new_claim_token()
    won = await acquire_control_action_lease(
        db,
        action_id,
        claim_token=claim_token,
        claim_expires_at=now + ttl,
        now=now,
    )
    return claim_token if won else None


async def _claim_reserved_action(
    db: AsyncSession,
    reservation: ControlActionReservation,
    action_type: ControlActionType,
    instant: datetime,
    lease_ttl: timedelta,
) -> tuple[str | None, bool]:
    action = reservation.action
    authority_matches = action_type not in RECOVERY_ACTION_TYPES or (
        action.recovery_deadline_at is not None
        and action.recovery_deadline_at > instant
    )
    if not authority_matches or not reservation.payload_matches or action.applied_at:
        return None, authority_matches
    claim_token = await take_action_lease(db, action.id, now=instant, ttl=lease_ttl)
    return claim_token, authority_matches


async def prepare_control_action_claim(
    db: AsyncSession,
    request: ControlActionClaimRequest,
) -> ControlActionClaim:
    """Prepare one accepted action inside the caller's acceptance transaction.

    The winner remains uncommitted so requested projections join the receipt,
    writer and lease. The caller must finalize acceptance before any network
    delivery. Losing claims roll back their attempted acceptance.
    """
    instant = request.now or datetime.now(UTC)
    resolved_type = ControlActionType(request.action_type)
    recovery_deadline_at = _resolved_recovery_deadline(
        resolved_type,
        instant,
        request.recovery_timeout_seconds,
        request.recovery_deadline_at,
    )
    reservation = await reserve_control_action(
        db,
        thread_id=request.thread_id,
        action_type=request.action_type,
        idempotency_key=request.idempotency_key,
        request_id=request.request_id,
        payload=request.payload,
        dispatch_id=request.dispatch_id,
        worker_generation=request.worker_generation,
        recovery_deadline_at=recovery_deadline_at,
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

    claim_token, authority_matches = await _claim_reserved_action(
        db, reservation, resolved_type, instant, request.lease_ttl
    )
    acquired = claim_token is not None

    if acquired and request.action_type != ControlActionType.CANCEL:
        receipt = await prepare_graph_action_receipt(
            db,
            thread_id=request.thread_id,
            dispatch_id=dispatch_id,
            install_from=request.write_expectation,
        )
        if receipt is None:
            acquired = False
            authority_matches = False
    if not acquired:
        claim_token = None
        await db.rollback()

    return ControlActionClaim(
        action_id=action_id,
        dispatch_id=dispatch_id,
        created=reservation.created,
        payload_matches=reservation.payload_matches,
        acquired=acquired,
        authority_matches=authority_matches,
        applied=applied,
        result_status=result_status,
        claim_token=claim_token,
    )


async def finalize_control_action_acceptance(
    db: AsyncSession,
    claim: ControlActionClaim,
) -> None:
    """Commit the verified claim and all accepted effects before delivery."""
    if not claim.acquired or claim.claim_token is None:
        raise RuntimeError("cannot finalize an unowned control action acceptance")
    await commit_control_action_lease(
        db,
        claim.action_id,
        claim_token=claim.claim_token,
    )


async def _failure_action(
    db: AsyncSession, claim: ControlActionClaim, instant: datetime
) -> tuple[ControlActionModel, str, datetime] | DispatchFailureDisposition:
    action = await get_control_action(db, claim.action_id, lock=True)
    if action is None or action.dispatch_id != claim.dispatch_id:
        return DispatchFailureDisposition.AUTHORITY_LOST
    if action.applied_at is not None:
        return DispatchFailureDisposition.APPLICATION_WON
    deadline = action.recovery_deadline_at
    if deadline is None or deadline <= instant:
        return DispatchFailureDisposition.DEADLINE_EXPIRED
    token = claim.claim_token
    if token is None or action.claim_token != token:
        return DispatchFailureDisposition.AUTHORITY_LOST
    return action, token, deadline


async def _failure_thread_authority(
    db: AsyncSession, action: ControlActionModel
) -> RunWriteAuthority | DispatchFailureDisposition:
    thread = await lock_thread_row(db, action.thread_id)
    if thread is None or not thread.is_active:
        return DispatchFailureDisposition.AUTHORITY_LOST
    authority = thread_write_expectation(thread).authority
    if not authority.owned_by(action.action_type, action.dispatch_id):
        return DispatchFailureDisposition.AUTHORITY_LOST
    return authority


async def record_dispatch_failure(
    db: AsyncSession,
    claim: ControlActionClaim,
    failure_type: FailureType,
    *,
    detail: str | None,
    observed_at: datetime | None = None,
) -> DispatchFailureDisposition:
    """Persist the typed outcome and release only proven non-delivery leases."""
    instant = observed_at or datetime.now(UTC)
    resolved = await _failure_action(db, claim, instant)
    if isinstance(resolved, DispatchFailureDisposition):
        return resolved
    action, claim_token, deadline = resolved
    authority = await _failure_thread_authority(db, action)
    if isinstance(authority, DispatchFailureDisposition):
        return authority

    disposition = DispatchFailureDisposition.AMBIGUOUS_DELIVERY
    if failure_type in DEFINITE_NON_DELIVERY:
        if not await release_control_action_lease(
            db,
            claim.action_id,
            claim_token=claim_token,
        ):
            return DispatchFailureDisposition.AUTHORITY_LOST
        disposition = DispatchFailureDisposition.DEFINITE_NON_DELIVERY
    try:
        await record_recovery_failure(
            db,
            thread_id=action.thread_id,
            authority=authority,
            condition=RecoveryCondition(failure_type.value),
            observed_at=instant,
            next_eligible_at=min(
                instant + timedelta(seconds=2),
                deadline,
            ),
            deadline_at=deadline,
            detail=detail,
        )
    except RecoveryAuthorityLostError:
        # The authority checks above are not atomic with this write: a new
        # dispatch can be accepted for this thread in between. Every other
        # authority-loss branch in this function reports the typed
        # disposition instead of raising, and this one is reached only by a
        # race the prior checks cannot see coming.
        return DispatchFailureDisposition.AUTHORITY_LOST
    return disposition
