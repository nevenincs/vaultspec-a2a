"""Shared durable ownership for gateway-to-worker control dispatches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from ..database import (
    ControlActionModel,
    ThreadModel,
    acquire_control_action_lease,
    commit_control_action_lease,
    release_control_action_lease,
    reserve_control_action,
    thread_write_expectation,
)
from ..thread.dispatch_policy import FailureType
from ..thread.enums import RECOVERY_ACTION_TYPES, ControlActionType, RecoveryCondition
from .dispatch_receipts import prepare_graph_action_receipt
from .recovery import record_recovery_failure

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.thread_repository import ThreadWriteExpectation

__all__ = [
    "CONTROL_ACTION_LEASE_TTL",
    "ControlActionClaim",
    "DispatchFailureDisposition",
    "finalize_control_action_acceptance",
    "prepare_control_action_claim",
    "record_dispatch_failure",
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
    authority_matches: bool
    applied: bool
    result_status: str
    claim_token: str | None


class DispatchFailureDisposition(StrEnum):
    """Exact durable result of settling one failed dispatch attempt."""

    DEFINITE_NON_DELIVERY = "definite_non_delivery"
    AMBIGUOUS_DELIVERY = "ambiguous_delivery"
    AUTHORITY_LOST = "authority_lost"
    DEADLINE_EXPIRED = "deadline_expired"
    APPLICATION_WON = "application_won"


async def prepare_control_action_claim(
    db: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str,
    idempotency_key: str,
    payload: dict[str, object] | None,
    dispatch_id: str,
    request_id: str | None = None,
    worker_generation: int = 0,
    now: datetime | None = None,
    lease_ttl: timedelta = CONTROL_ACTION_LEASE_TTL,
    write_expectation: ThreadWriteExpectation | None = None,
    recovery_timeout_seconds: int | None = None,
    recovery_deadline_at: datetime | None = None,
) -> ControlActionClaim:
    """Prepare one accepted action inside the caller's acceptance transaction.

    The winner remains uncommitted so requested projections join the receipt,
    writer and lease. The caller must finalize acceptance before any network
    delivery. Losing claims roll back their attempted acceptance.
    """
    instant = now or datetime.now(UTC)
    resolved_type = ControlActionType(action_type)
    if resolved_type in RECOVERY_ACTION_TYPES:
        if (recovery_timeout_seconds is None) == (recovery_deadline_at is None):
            raise ValueError(
                "recoverable action requires exactly one run timeout or deadline"
            )
        if recovery_timeout_seconds is not None:
            if recovery_timeout_seconds < 1:
                raise ValueError("recovery_timeout_seconds must be positive")
            recovery_deadline_at = instant + timedelta(seconds=recovery_timeout_seconds)
        if recovery_deadline_at is None or recovery_deadline_at <= instant:
            raise ValueError("recovery deadline must be later than acceptance")
    elif recovery_timeout_seconds is not None or recovery_deadline_at is not None:
        raise ValueError("non-recoverable action cannot carry a recovery deadline")
    reservation = await reserve_control_action(
        db,
        thread_id=thread_id,
        action_type=action_type,
        idempotency_key=idempotency_key,
        request_id=request_id,
        payload=payload,
        dispatch_id=dispatch_id,
        worker_generation=worker_generation,
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

    claim_token: str | None = None
    acquired = False
    authority_matches = resolved_type not in RECOVERY_ACTION_TYPES or (
        action.recovery_deadline_at is not None
        and action.recovery_deadline_at > instant
    )
    if authority_matches and reservation.payload_matches and action.applied_at is None:
        claim_token = uuid4().hex
        acquired = await acquire_control_action_lease(
            db,
            action_id,
            claim_token=claim_token,
            claim_expires_at=instant + lease_ttl,
            now=instant,
        )

    if acquired and action_type != ControlActionType.CANCEL:
        receipt = await prepare_graph_action_receipt(
            db,
            thread_id=thread_id,
            dispatch_id=dispatch_id,
            install_from=write_expectation if reservation.created else None,
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
    action = await db.get(ControlActionModel, claim.action_id, with_for_update=True)
    if action is None or action.dispatch_id != claim.dispatch_id:
        return DispatchFailureDisposition.AUTHORITY_LOST
    if action.applied_at is not None:
        return DispatchFailureDisposition.APPLICATION_WON
    if action.recovery_deadline_at is None or action.recovery_deadline_at <= instant:
        return DispatchFailureDisposition.DEADLINE_EXPIRED
    if claim.claim_token is None or action.claim_token != claim.claim_token:
        return DispatchFailureDisposition.AUTHORITY_LOST
    thread = await db.get(ThreadModel, action.thread_id, with_for_update=True)
    if thread is None:
        return DispatchFailureDisposition.AUTHORITY_LOST
    authority = thread_write_expectation(thread).authority
    if (
        authority.action_type.value != action.action_type
        or authority.action_receipt_id != action.dispatch_id
    ):
        return DispatchFailureDisposition.AUTHORITY_LOST

    disposition = DispatchFailureDisposition.AMBIGUOUS_DELIVERY
    if failure_type in _DEFINITE_NON_DELIVERY:
        if not await release_control_action_lease(
            db,
            claim.action_id,
            claim_token=claim.claim_token,
        ):
            return DispatchFailureDisposition.AUTHORITY_LOST
        disposition = DispatchFailureDisposition.DEFINITE_NON_DELIVERY
    await record_recovery_failure(
        db,
        thread_id=action.thread_id,
        authority=authority,
        condition=RecoveryCondition(failure_type.value),
        observed_at=instant,
        next_eligible_at=min(
            instant + timedelta(seconds=2),
            action.recovery_deadline_at,
        ),
        deadline_at=action.recovery_deadline_at,
        detail=detail,
    )
    return disposition
