"""Durable scheduling authority for recovery work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Unpack

from ..database import (
    claim_recovery_attempt,
    due_recovery_attempt_ids,
    lease_free_from,
    new_claim_token,
    release_recovery_claim,
    require_lease_window,
    reschedule_recovery_claim,
    schedule_recovery_attempt,
    settle_expired_recovery_attempt,
    settle_recovery_claim,
    thread_write_expectation,
    unscheduled_recovery_actions,
)
from ..thread import RunWriteAuthority
from ..thread.enums import RECOVERY_ACTION_TYPES, ControlActionType, RecoveryCondition

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import (
        RecoveryAttemptModel,
        RecoveryFailureArgs,
        RecoveryRescheduleArgs,
    )

__all__ = [
    "RecoveryAttemptClaim",
    "RecoveryAuthorityLostError",
    "acquire_due_recovery_attempts",
    "record_recovery_deadline",
    "record_recovery_failure",
    "release_recovery_attempt",
    "reschedule_recovery_attempt",
    "seed_recovery_attempts",
    "settle_recovery_attempt",
]


class RecoveryAuthorityLostError(ValueError):
    """The failed dispatch no longer owns the accepted run action."""


@dataclass(frozen=True, slots=True)
class RecoveryAttemptClaim:
    """Exact renewable ownership of one due recovery record."""

    attempt_id: str
    claim_token: str
    thread_id: str
    authority: RunWriteAuthority
    condition: RecoveryCondition
    attempt_count: int
    deadline_at: datetime


def _validate_page_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be positive")


def _validate_recovery_window(
    observed_at: datetime,
    next_eligible_at: datetime,
    deadline_at: datetime,
    action_type: ControlActionType,
) -> None:
    if next_eligible_at < observed_at:
        raise ValueError("next_eligible_at cannot precede observed_at")
    if deadline_at <= observed_at:
        raise ValueError("deadline_at must be later than observed_at")
    if next_eligible_at > deadline_at:
        raise ValueError("next_eligible_at cannot exceed deadline_at")
    if action_type not in RECOVERY_ACTION_TYPES:
        raise ValueError("action type is not recoverable")


async def record_recovery_failure(
    session: AsyncSession,
    **kwargs: Unpack[RecoveryFailureArgs],
) -> RecoveryAttemptModel:
    """Create or advance the sole retry record for an exact run writer."""
    _validate_recovery_window(
        kwargs["observed_at"],
        kwargs["next_eligible_at"],
        kwargs["deadline_at"],
        kwargs["authority"].action_type,
    )
    row = await schedule_recovery_attempt(session, **kwargs)
    if row is None:
        raise RecoveryAuthorityLostError(
            "recovery failure does not own the current accepted action"
        )
    return row


async def record_recovery_deadline(
    session: AsyncSession,
    *,
    thread_id: str,
    authority: RunWriteAuthority,
    observed_at: datetime,
    deadline_at: datetime,
) -> RecoveryAttemptModel:
    """Close the exact retry ledger when its accepted run budget expires."""
    if deadline_at > observed_at:
        raise ValueError("recovery deadline has not expired")
    row = await settle_expired_recovery_attempt(
        session,
        thread_id=thread_id,
        authority=authority,
        observed_at=observed_at,
        deadline_at=deadline_at,
    )
    if row is None:
        raise ValueError("expired recovery does not own the current accepted action")
    return row


async def seed_recovery_attempts(
    session: AsyncSession,
    *,
    observed_at: datetime,
    limit: int,
) -> int:
    """Create the missing durable schedule for current accepted work."""
    _validate_page_limit(limit)
    seeded = 0
    for action, thread in await unscheduled_recovery_actions(
        session, observed_at=observed_at, limit=limit
    ):
        if action.recovery_deadline_at is None:
            continue
        await record_recovery_failure(
            session,
            thread_id=thread.id,
            authority=thread_write_expectation(thread).authority,
            condition=RecoveryCondition.DISPATCH_PENDING,
            observed_at=observed_at,
            next_eligible_at=min(
                lease_free_from(action.claim_expires_at, observed_at),
                action.recovery_deadline_at,
            ),
            deadline_at=action.recovery_deadline_at,
            detail="accepted dispatch has no durable application receipt",
        )
        seeded += 1
    return seeded


async def acquire_due_recovery_attempts(
    session: AsyncSession,
    *,
    acquired_at: datetime,
    claim_expires_at: datetime,
    limit: int,
) -> tuple[RecoveryAttemptClaim, ...]:
    """Claim a bounded due page using an exact compare-and-set per row."""
    _validate_page_limit(limit)
    require_lease_window(acquired_at, claim_expires_at)

    claims: list[RecoveryAttemptClaim] = []
    for attempt_id in await due_recovery_attempt_ids(
        session, at=acquired_at, limit=limit
    ):
        claim_token = new_claim_token()
        row = await claim_recovery_attempt(
            session,
            attempt_id,
            claim_token=claim_token,
            acquired_at=acquired_at,
            claim_expires_at=claim_expires_at,
        )
        if row is None:
            continue
        claims.append(
            RecoveryAttemptClaim(
                attempt_id=row.id,
                claim_token=claim_token,
                thread_id=row.thread_id,
                authority=RunWriteAuthority(
                    row.run_revision,
                    row.writer_generation,
                    action_type=ControlActionType(row.action_type),
                    action_receipt_id=row.action_receipt_id,
                ),
                condition=RecoveryCondition(row.condition),
                attempt_count=row.attempt_count,
                deadline_at=row.deadline_at,
            )
        )
    return tuple(claims)


async def release_recovery_attempt(
    session: AsyncSession,
    claim: RecoveryAttemptClaim,
    *,
    released_at: datetime,
) -> bool:
    """Release an owned attempt without changing its schedule or count."""
    return await release_recovery_claim(
        session,
        claim.attempt_id,
        claim_token=claim.claim_token,
        released_at=released_at,
    )


async def reschedule_recovery_attempt(
    session: AsyncSession,
    claim: RecoveryAttemptClaim,
    **kwargs: Unpack[RecoveryRescheduleArgs],
) -> bool:
    """Advance one claimed retry after another classified failure."""
    next_eligible_at = kwargs["next_eligible_at"]
    if next_eligible_at < kwargs["observed_at"] or next_eligible_at > claim.deadline_at:
        raise ValueError("next eligibility must fall between observation and deadline")
    return await reschedule_recovery_claim(
        session,
        claim.attempt_id,
        claim_token=claim.claim_token,
        deadline_at=claim.deadline_at,
        **kwargs,
    )


async def settle_recovery_attempt(
    session: AsyncSession,
    claim: RecoveryAttemptClaim,
    *,
    settled_at: datetime,
    condition: RecoveryCondition | None = None,
    detail: str | None = None,
) -> bool:
    """Close an exact claimed schedule after dispatch or terminal reconciliation."""
    return await settle_recovery_claim(
        session,
        claim.attempt_id,
        claim_token=claim.claim_token,
        settled_at=settled_at,
        condition=condition,
        detail=detail,
    )
