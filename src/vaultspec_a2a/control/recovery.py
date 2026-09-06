"""Durable scheduling authority for recovery work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from sqlalchemy import exists, or_, select, update

from ..database.models import (
    ControlActionModel,
    RecoveryAttemptModel,
    RunWriteAuthority,
    ThreadModel,
)
from ..thread.enums import RECOVERY_ACTION_TYPES, ControlActionType, RecoveryCondition

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

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

_MAX_DETAIL_CHARS = 2048


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


def _bounded_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    return detail.replace("\r", " ").replace("\n", " ")[:_MAX_DETAIL_CHARS]


async def record_recovery_failure(
    session: AsyncSession,
    *,
    thread_id: str,
    authority: RunWriteAuthority,
    condition: RecoveryCondition,
    observed_at: datetime,
    next_eligible_at: datetime,
    deadline_at: datetime,
    detail: str | None,
) -> RecoveryAttemptModel:
    """Create or advance the sole retry record for an exact run writer."""
    if next_eligible_at < observed_at:
        raise ValueError("next_eligible_at cannot precede observed_at")
    if deadline_at <= observed_at:
        raise ValueError("deadline_at must be later than observed_at")
    if next_eligible_at > deadline_at:
        raise ValueError("next_eligible_at cannot exceed deadline_at")
    if authority.action_type not in RECOVERY_ACTION_TYPES:
        raise ValueError("action type is not recoverable")

    owns_thread = await session.scalar(
        select(ThreadModel.id)
        .where(
            ThreadModel.id == thread_id,
            ThreadModel.is_active.is_(True),
            ThreadModel.run_revision == authority.run_revision,
            ThreadModel.writer_generation == authority.writer_generation,
            ThreadModel.writer_action_type == authority.action_type.value,
            ThreadModel.writer_action_receipt_id == authority.action_receipt_id,
        )
        .with_for_update()
    )
    owns_action = await session.scalar(
        select(ControlActionModel.id).where(
            ControlActionModel.thread_id == thread_id,
            ControlActionModel.action_type == authority.action_type.value,
            ControlActionModel.dispatch_id == authority.action_receipt_id,
            ControlActionModel.applied_at.is_(None),
            ControlActionModel.recovery_deadline_at == deadline_at,
        )
    )
    if owns_thread is None or owns_action is None:
        raise RecoveryAuthorityLostError(
            "recovery failure does not own the current accepted action"
        )

    identity = (
        RecoveryAttemptModel.thread_id == thread_id,
        RecoveryAttemptModel.run_revision == authority.run_revision,
        RecoveryAttemptModel.writer_generation == authority.writer_generation,
        RecoveryAttemptModel.action_receipt_id == authority.action_receipt_id,
    )
    row = await session.scalar(
        select(RecoveryAttemptModel).where(*identity).with_for_update()
    )
    if row is None:
        row = RecoveryAttemptModel(
            id=uuid4().hex,
            thread_id=thread_id,
            run_revision=authority.run_revision,
            writer_generation=authority.writer_generation,
            action_type=authority.action_type.value,
            action_receipt_id=authority.action_receipt_id,
            condition=condition.value,
            attempt_count=1,
            next_eligible_at=next_eligible_at,
            deadline_at=deadline_at,
            detail=_bounded_detail(detail),
            created_at=observed_at,
            updated_at=observed_at,
        )
        session.add(row)
    else:
        if row.settled_at is not None:
            raise ValueError("settled recovery attempt cannot be reopened")
        if row.action_type != authority.action_type.value:
            raise ValueError("recovery action type is immutable")
        if row.deadline_at != deadline_at:
            raise ValueError("recovery deadline is immutable")
        row.condition = condition.value
        row.attempt_count += 1
        row.next_eligible_at = next_eligible_at
        row.detail = _bounded_detail(detail)
        row.claim_token = None
        row.claim_expires_at = None
        row.updated_at = observed_at
    await session.flush()
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
    action = await session.scalar(
        select(ControlActionModel).where(
            ControlActionModel.thread_id == thread_id,
            ControlActionModel.action_type == authority.action_type.value,
            ControlActionModel.dispatch_id == authority.action_receipt_id,
            ControlActionModel.recovery_deadline_at == deadline_at,
        )
    )
    thread = await session.scalar(
        select(ThreadModel)
        .where(
            ThreadModel.id == thread_id,
            ThreadModel.run_revision == authority.run_revision,
            ThreadModel.writer_generation == authority.writer_generation,
            ThreadModel.writer_action_type == authority.action_type.value,
            ThreadModel.writer_action_receipt_id == authority.action_receipt_id,
        )
        .with_for_update()
    )
    if action is None or thread is None:
        raise ValueError("expired recovery does not own the current accepted action")
    identity = (
        RecoveryAttemptModel.thread_id == thread_id,
        RecoveryAttemptModel.run_revision == authority.run_revision,
        RecoveryAttemptModel.writer_generation == authority.writer_generation,
        RecoveryAttemptModel.action_receipt_id == authority.action_receipt_id,
    )
    row = await session.scalar(
        select(RecoveryAttemptModel).where(*identity).with_for_update()
    )
    if row is None:
        row = RecoveryAttemptModel(
            id=uuid4().hex,
            thread_id=thread_id,
            run_revision=authority.run_revision,
            writer_generation=authority.writer_generation,
            action_type=authority.action_type.value,
            action_receipt_id=authority.action_receipt_id,
            condition=RecoveryCondition.DEADLINE_EXCEEDED.value,
            attempt_count=1,
            next_eligible_at=deadline_at,
            deadline_at=deadline_at,
            detail="accepted run deadline expired before application",
            settled_at=observed_at,
            created_at=action.requested_at,
            updated_at=observed_at,
        )
        session.add(row)
    elif row.settled_at is None:
        row.condition = RecoveryCondition.DEADLINE_EXCEEDED.value
        row.detail = "accepted run deadline expired before application"
        row.claim_token = None
        row.claim_expires_at = None
        row.settled_at = observed_at
        row.updated_at = observed_at
    await session.flush()
    return row


async def seed_recovery_attempts(
    session: AsyncSession,
    *,
    observed_at: datetime,
    limit: int,
) -> int:
    """Create the missing durable schedule for current accepted work."""
    if limit < 1:
        raise ValueError("limit must be positive")
    rows = (
        await session.execute(
            select(ControlActionModel, ThreadModel)
            .join(ThreadModel, ThreadModel.id == ControlActionModel.thread_id)
            .where(
                ControlActionModel.action_type.in_(
                    action.value for action in RECOVERY_ACTION_TYPES
                ),
                ControlActionModel.applied_at.is_(None),
                ControlActionModel.recovery_deadline_at.is_not(None),
                ControlActionModel.recovery_deadline_at > observed_at,
                ThreadModel.is_active.is_(True),
                ThreadModel.run_revision >= 0,
                ThreadModel.writer_generation >= 1,
                ThreadModel.writer_action_type == ControlActionModel.action_type,
                ThreadModel.writer_action_receipt_id == ControlActionModel.dispatch_id,
                ~exists(
                    select(RecoveryAttemptModel.id).where(
                        RecoveryAttemptModel.thread_id == ThreadModel.id,
                        RecoveryAttemptModel.run_revision == ThreadModel.run_revision,
                        RecoveryAttemptModel.writer_generation
                        == ThreadModel.writer_generation,
                        RecoveryAttemptModel.action_receipt_id
                        == ControlActionModel.dispatch_id,
                    )
                ),
            )
            .order_by(ControlActionModel.requested_at, ControlActionModel.id)
            .limit(limit)
        )
    ).all()
    seeded = 0
    for action, thread in rows:
        if action.dispatch_id is None or action.recovery_deadline_at is None:
            continue
        next_eligible_at = max(
            observed_at,
            action.claim_expires_at or observed_at,
        )
        if next_eligible_at > action.recovery_deadline_at:
            next_eligible_at = action.recovery_deadline_at
        await record_recovery_failure(
            session,
            thread_id=thread.id,
            authority=RunWriteAuthority(
                thread.run_revision,
                thread.writer_generation,
                ControlActionType(thread.writer_action_type),
                thread.writer_action_receipt_id,
            ),
            condition=RecoveryCondition.DISPATCH_PENDING,
            observed_at=observed_at,
            next_eligible_at=next_eligible_at,
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
    if limit < 1:
        raise ValueError("limit must be positive")
    if claim_expires_at <= acquired_at:
        raise ValueError("claim_expires_at must be later than acquired_at")

    candidates = (
        await session.scalars(
            select(RecoveryAttemptModel.id)
            .where(
                RecoveryAttemptModel.settled_at.is_(None),
                RecoveryAttemptModel.next_eligible_at <= acquired_at,
                RecoveryAttemptModel.deadline_at > acquired_at,
                or_(
                    RecoveryAttemptModel.claim_token.is_(None),
                    RecoveryAttemptModel.claim_expires_at.is_(None),
                    RecoveryAttemptModel.claim_expires_at <= acquired_at,
                ),
            )
            .order_by(
                RecoveryAttemptModel.next_eligible_at,
                RecoveryAttemptModel.created_at,
                RecoveryAttemptModel.id,
            )
            .limit(limit)
        )
    ).all()
    claims: list[RecoveryAttemptClaim] = []
    for attempt_id in candidates:
        claim_token = uuid4().hex
        won = cast(
            "CursorResult[Any]",
            await session.execute(
                update(RecoveryAttemptModel)
                .where(
                    RecoveryAttemptModel.id == attempt_id,
                    RecoveryAttemptModel.settled_at.is_(None),
                    RecoveryAttemptModel.next_eligible_at <= acquired_at,
                    RecoveryAttemptModel.deadline_at > acquired_at,
                    or_(
                        RecoveryAttemptModel.claim_token.is_(None),
                        RecoveryAttemptModel.claim_expires_at.is_(None),
                        RecoveryAttemptModel.claim_expires_at <= acquired_at,
                    ),
                )
                .values(
                    claim_token=claim_token,
                    claim_expires_at=claim_expires_at,
                    updated_at=acquired_at,
                )
            ),
        )
        if won.rowcount != 1:
            continue
        row = await session.get(
            RecoveryAttemptModel, attempt_id, populate_existing=True
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
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(RecoveryAttemptModel)
            .where(
                RecoveryAttemptModel.id == claim.attempt_id,
                RecoveryAttemptModel.claim_token == claim.claim_token,
                RecoveryAttemptModel.settled_at.is_(None),
            )
            .values(claim_token=None, claim_expires_at=None, updated_at=released_at)
        ),
    )
    return result.rowcount == 1


async def reschedule_recovery_attempt(
    session: AsyncSession,
    claim: RecoveryAttemptClaim,
    *,
    condition: RecoveryCondition,
    observed_at: datetime,
    next_eligible_at: datetime,
    detail: str | None,
) -> bool:
    """Advance one claimed retry after another classified failure."""
    if next_eligible_at < observed_at or next_eligible_at > claim.deadline_at:
        raise ValueError("next eligibility must fall between observation and deadline")
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(RecoveryAttemptModel)
            .where(
                RecoveryAttemptModel.id == claim.attempt_id,
                RecoveryAttemptModel.claim_token == claim.claim_token,
                RecoveryAttemptModel.settled_at.is_(None),
                RecoveryAttemptModel.deadline_at == claim.deadline_at,
            )
            .values(
                condition=condition.value,
                attempt_count=RecoveryAttemptModel.attempt_count + 1,
                next_eligible_at=next_eligible_at,
                detail=_bounded_detail(detail),
                claim_token=None,
                claim_expires_at=None,
                updated_at=observed_at,
            )
        ),
    )
    return result.rowcount == 1


async def settle_recovery_attempt(
    session: AsyncSession,
    claim: RecoveryAttemptClaim,
    *,
    settled_at: datetime,
    condition: RecoveryCondition | None = None,
    detail: str | None = None,
) -> bool:
    """Close an exact claimed schedule after dispatch or terminal reconciliation."""
    values: dict[str, object | None] = {
        "settled_at": settled_at,
        "claim_token": None,
        "claim_expires_at": None,
        "updated_at": settled_at,
    }
    if condition is not None:
        values["condition"] = condition.value
        values["detail"] = _bounded_detail(detail)
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(RecoveryAttemptModel)
            .where(
                RecoveryAttemptModel.id == claim.attempt_id,
                RecoveryAttemptModel.claim_token == claim.claim_token,
                RecoveryAttemptModel.settled_at.is_(None),
            )
            .values(**values)
        ),
    )
    return result.rowcount == 1
