"""Recovery attempt repository: the durable retry schedule of exact run writers.

One row per accepted run writer records why its dispatch is retried, when it is
next eligible and which dispatcher currently holds the claim to retry it. The
retry policy and recovery classification belong to ``control``; this module
holds the queries, the conditional writes and the row construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast
from uuid import uuid4

from sqlalchemy import exists, select, update

from ..thread.enums import RecoveryCondition
from ._helpers import save_model
from ._leases import RECOVERY_ATTEMPT_LEASE, clear_lease
from .control_action_repository import get_writer_action, select_recoverable_actions
from .models import ControlActionModel, RecoveryAttemptModel, ThreadModel
from .thread_repository import thread_owned_by

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import QueryableAttribute
    from sqlalchemy.sql.elements import ColumnElement

    from ..thread import RunWriteAuthority

__all__ = [
    "RecoveryFailureArgs",
    "RecoveryRescheduleArgs",
    "claim_recovery_attempt",
    "due_recovery_attempt_ids",
    "release_recovery_claim",
    "reschedule_recovery_claim",
    "schedule_recovery_attempt",
    "settle_expired_recovery_attempt",
    "settle_recovery_claim",
    "unscheduled_recovery_actions",
]

_MAX_DETAIL_CHARS = 2048
_DEADLINE_DETAIL = "accepted run deadline expired before application"


class RecoveryFailureArgs(TypedDict):
    """One classified dispatch failure of an exact accepted run writer."""

    thread_id: str
    authority: RunWriteAuthority
    condition: RecoveryCondition
    observed_at: datetime
    next_eligible_at: datetime
    deadline_at: datetime
    detail: str | None


class RecoveryRescheduleArgs(TypedDict):
    """The next classified failure of an already claimed retry."""

    condition: RecoveryCondition
    observed_at: datetime
    next_eligible_at: datetime
    detail: str | None


class _Reclassification(TypedDict, total=False):
    condition: RecoveryCondition | None
    detail: str | None


def _bounded_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    return detail.replace("\r", " ").replace("\n", " ")[:_MAX_DETAIL_CHARS]


def _attempt_of(
    thread_id: str | QueryableAttribute[str],
    run_revision: int | QueryableAttribute[int],
    writer_generation: int | QueryableAttribute[int],
    action_receipt_id: str | QueryableAttribute[str | None],
) -> tuple[ColumnElement[bool], ...]:
    """Match a run writer's one attempt row, by bound values or joined columns."""
    return (
        RecoveryAttemptModel.thread_id == thread_id,
        RecoveryAttemptModel.run_revision == run_revision,
        RecoveryAttemptModel.writer_generation == writer_generation,
        RecoveryAttemptModel.action_receipt_id == action_receipt_id,
    )


def _due_unclaimed(at: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        RecoveryAttemptModel.settled_at.is_(None),
        RecoveryAttemptModel.next_eligible_at <= at,
        RecoveryAttemptModel.deadline_at > at,
        RECOVERY_ATTEMPT_LEASE.unheld(at),
    )


async def _owned_accepted_action(
    session: AsyncSession,
    thread_id: str,
    authority: RunWriteAuthority,
    *,
    deadline_at: datetime,
    pending_only: bool,
) -> ControlActionModel | None:
    """Return the writer's journal row while the run still names that writer.

    The run row is locked first, so the schedule write that follows cannot race
    a new election. ``pending_only`` also requires an active run and an
    unapplied action, which scheduling a retry needs and closing an expired
    ledger does not.
    """
    run_clauses = [
        ThreadModel.id == thread_id,
        thread_owned_by(
            authority.action_type,
            authority.action_receipt_id,
            writer_generation=authority.writer_generation,
            run_revision=authority.run_revision,
        ),
    ]
    if pending_only:
        run_clauses.append(ThreadModel.is_active.is_(True))
    owns_run = await session.scalar(
        select(ThreadModel.id).where(*run_clauses).with_for_update()
    )
    if owns_run is None:
        return None
    return await get_writer_action(
        session,
        thread_id=thread_id,
        authority=authority,
        deadline_at=deadline_at,
        unapplied_only=pending_only,
    )


async def _locked_attempt_for(
    session: AsyncSession, thread_id: str, authority: RunWriteAuthority
) -> RecoveryAttemptModel | None:
    return await session.scalar(
        select(RecoveryAttemptModel)
        .where(
            *_attempt_of(
                thread_id,
                authority.run_revision,
                authority.writer_generation,
                authority.action_receipt_id,
            )
        )
        .with_for_update()
    )


def _new_attempt(
    thread_id: str, authority: RunWriteAuthority, **schedule: object
) -> RecoveryAttemptModel:
    return RecoveryAttemptModel(
        id=uuid4().hex,
        thread_id=thread_id,
        run_revision=authority.run_revision,
        writer_generation=authority.writer_generation,
        action_type=authority.action_type.value,
        action_receipt_id=authority.action_receipt_id,
        attempt_count=1,
        **schedule,
    )


async def schedule_recovery_attempt(
    session: AsyncSession, **kwargs: Unpack[RecoveryFailureArgs]
) -> RecoveryAttemptModel | None:
    """Create or advance the sole retry record for an exact run writer.

    Returns ``None``, writing nothing, when the active run or its unapplied
    journal row no longer names the writer.
    """
    thread_id = kwargs["thread_id"]
    authority = kwargs["authority"]
    observed_at = kwargs["observed_at"]
    deadline_at = kwargs["deadline_at"]
    owned = await _owned_accepted_action(
        session, thread_id, authority, deadline_at=deadline_at, pending_only=True
    )
    if owned is None:
        return None
    row = await _locked_attempt_for(session, thread_id, authority)
    if row is None:
        return await save_model(
            session,
            _new_attempt(
                thread_id,
                authority,
                condition=kwargs["condition"].value,
                next_eligible_at=kwargs["next_eligible_at"],
                deadline_at=deadline_at,
                detail=_bounded_detail(kwargs["detail"]),
                created_at=observed_at,
                updated_at=observed_at,
            ),
        )
    if row.settled_at is not None:
        raise ValueError("settled recovery attempt cannot be reopened")
    if row.action_type != authority.action_type.value:
        raise ValueError("recovery action type is immutable")
    if row.deadline_at != deadline_at:
        raise ValueError("recovery deadline is immutable")
    row.condition = kwargs["condition"].value
    row.attempt_count += 1
    row.next_eligible_at = kwargs["next_eligible_at"]
    row.detail = _bounded_detail(kwargs["detail"])
    clear_lease(row)
    row.updated_at = observed_at
    await session.flush()
    return row


async def settle_expired_recovery_attempt(
    session: AsyncSession,
    *,
    thread_id: str,
    authority: RunWriteAuthority,
    observed_at: datetime,
    deadline_at: datetime,
) -> RecoveryAttemptModel | None:
    """Close the exact writer's retry ledger as past its accepted deadline.

    Returns ``None``, writing nothing, when the run or its journal row no
    longer names the writer.
    """
    action = await _owned_accepted_action(
        session, thread_id, authority, deadline_at=deadline_at, pending_only=False
    )
    if action is None:
        return None
    row = await _locked_attempt_for(session, thread_id, authority)
    if row is None:
        return await save_model(
            session,
            _new_attempt(
                thread_id,
                authority,
                condition=RecoveryCondition.DEADLINE_EXCEEDED.value,
                next_eligible_at=deadline_at,
                deadline_at=deadline_at,
                detail=_DEADLINE_DETAIL,
                settled_at=observed_at,
                created_at=action.requested_at,
                updated_at=observed_at,
            ),
        )
    if row.settled_at is None:
        row.condition = RecoveryCondition.DEADLINE_EXCEEDED.value
        row.detail = _DEADLINE_DETAIL
        clear_lease(row)
        row.settled_at = observed_at
        row.updated_at = observed_at
    await session.flush()
    return row


async def unscheduled_recovery_actions(
    session: AsyncSession, *, observed_at: datetime, limit: int
) -> Sequence[tuple[ControlActionModel, ThreadModel]]:
    """Return current recoverable work whose exact writer has no retry record.

    Each pair is an unapplied, unexpired recoverable journal row and the active
    run it currently writes, oldest request first.
    """
    unscheduled = ~exists(
        select(RecoveryAttemptModel.id).where(
            *_attempt_of(
                ThreadModel.id,
                ThreadModel.run_revision,
                ThreadModel.writer_generation,
                ControlActionModel.dispatch_id,
            )
        )
    )
    result = await session.execute(
        select_recoverable_actions(
            ControlActionModel.recovery_deadline_at > observed_at,
            ThreadModel.run_revision >= 0,
            ThreadModel.writer_generation >= 1,
            unscheduled,
        )
        .add_columns(ThreadModel)
        .order_by(ControlActionModel.requested_at, ControlActionModel.id)
        .limit(limit)
    )
    return result.tuples().all()


async def due_recovery_attempt_ids(
    session: AsyncSession, *, at: datetime, limit: int
) -> Sequence[str]:
    """Return a bounded page of unsettled, eligible attempts nobody holds."""
    return (
        await session.scalars(
            select(RecoveryAttemptModel.id)
            .where(*_due_unclaimed(at))
            .order_by(
                RecoveryAttemptModel.next_eligible_at,
                RecoveryAttemptModel.created_at,
                RecoveryAttemptModel.id,
            )
            .limit(limit)
        )
    ).all()


async def claim_recovery_attempt(
    session: AsyncSession,
    attempt_id: str,
    *,
    claim_token: str,
    acquired_at: datetime,
    claim_expires_at: datetime,
) -> RecoveryAttemptModel | None:
    """Take one attempt by compare-and-set while it is still due and unheld."""
    won = cast(
        "CursorResult[Any]",
        await session.execute(
            update(RecoveryAttemptModel)
            .where(RecoveryAttemptModel.id == attempt_id, *_due_unclaimed(acquired_at))
            .values(
                **RECOVERY_ATTEMPT_LEASE.granted(claim_token, claim_expires_at),
                updated_at=acquired_at,
            )
        ),
    )
    if won.rowcount != 1:
        return None
    return await session.get(RecoveryAttemptModel, attempt_id, populate_existing=True)


async def _update_claimed(
    session: AsyncSession,
    attempt_id: str,
    claim_token: str,
    *where: ColumnElement[bool],
    **values: object,
) -> bool:
    """Write *values* and free the claim only while *claim_token* still holds it."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(RecoveryAttemptModel)
            .where(
                RecoveryAttemptModel.id == attempt_id,
                RECOVERY_ATTEMPT_LEASE.held_by(claim_token),
                RecoveryAttemptModel.settled_at.is_(None),
                *where,
            )
            .values(**RECOVERY_ATTEMPT_LEASE.released(), **values)
        ),
    )
    return result.rowcount == 1


async def release_recovery_claim(
    session: AsyncSession, attempt_id: str, *, claim_token: str, released_at: datetime
) -> bool:
    """Release an owned attempt without changing its schedule or count."""
    return await _update_claimed(
        session, attempt_id, claim_token, updated_at=released_at
    )


async def reschedule_recovery_claim(
    session: AsyncSession,
    attempt_id: str,
    *,
    claim_token: str,
    deadline_at: datetime,
    **kwargs: Unpack[RecoveryRescheduleArgs],
) -> bool:
    """Advance one claimed retry after another classified failure."""
    return await _update_claimed(
        session,
        attempt_id,
        claim_token,
        RecoveryAttemptModel.deadline_at == deadline_at,
        condition=kwargs["condition"].value,
        attempt_count=RecoveryAttemptModel.attempt_count + 1,
        next_eligible_at=kwargs["next_eligible_at"],
        detail=_bounded_detail(kwargs["detail"]),
        updated_at=kwargs["observed_at"],
    )


async def settle_recovery_claim(
    session: AsyncSession,
    attempt_id: str,
    *,
    claim_token: str,
    settled_at: datetime,
    **reclassified: Unpack[_Reclassification],
) -> bool:
    """Close an exact claimed schedule, reclassifying it when a condition is given."""
    values: dict[str, object] = {"settled_at": settled_at, "updated_at": settled_at}
    condition = reclassified.get("condition")
    if condition is not None:
        values["condition"] = condition.value
        values["detail"] = _bounded_detail(reclassified.get("detail"))
    return await _update_claimed(session, attempt_id, claim_token, **values)
