"""Control action repository — the control journal, its leases and its queue.

Owns every read and write of ``control_actions``: the idempotent journal, the
renewable dispatch leases, the graph receipt persisted beside the accepted
input it identifies, and the queue of continuations waiting behind a run's
in-flight turn. What a lease means, when an action is recoverable and how a
queue promotes live in ``control/``; this module holds the queries,
conditional writes and row mapping they stand on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Select
    from sqlalchemy.sql.elements import ColumnElement

    from ..thread import RunWriteAuthority, ThreadWriteExpectation

from ..thread.action_receipts import GraphActionReceipt, canonical_json
from ..thread.enums import (
    RECOVERY_ACTION_TYPES,
    ControlActionResultStatus,
    ControlActionType,
)
from ._helpers import _coerce, _journal_row_for, affected_rows, save_model
from ._leases import CONTROL_ACTION_LEASE, clear_lease, require_lease_window
from .models import ControlActionModel, ThreadModel, utcnow
from .thread_repository import thread_owned_by

__all__ = [
    "ControlActionReservation",
    "acquire_control_action_lease",
    "commit_control_action_lease",
    "count_queued_continuations",
    "create_control_action",
    "enqueue_continuation",
    "get_control_action",
    "get_control_action_by_dispatch_id",
    "get_control_action_by_idempotency_key",
    "get_latest_control_action",
    "get_or_create_control_action",
    "get_writer_action",
    "has_live_queued_continuation_lease",
    "idempotency_key_admitted",
    "mark_control_action_applied",
    "mark_control_action_duplicate",
    "mark_control_action_superseded",
    "next_queue_position",
    "overdue_recovery_actions",
    "persist_graph_action_receipt",
    "read_next_queued_continuation",
    "reject_queued_continuations",
    "release_control_action_lease",
    "reserve_control_action",
    "select_recoverable_actions",
    "settle_control_action_lease",
]

_QUEUED = ControlActionResultStatus.QUEUED.value


@dataclass(frozen=True, slots=True)
class ControlActionReservation:
    """Result of reserving one idempotent control intention.

    ``payload_matches`` is false when the same idempotency key was already bound
    to a competing action body.  Callers must surface that as conflict and must
    never acquire or dispatch the returned row.
    """

    action: ControlActionModel
    created: bool
    payload_matches: bool


def _encode_payload(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    return canonical_json(payload)


def _payload_matches(stored: str | None, expected: dict[str, object] | None) -> bool:
    if stored is None:
        return expected is None
    try:
        return json.loads(stored) == expected
    except json.JSONDecodeError:
        return False


class _ControlActionOptional(TypedDict, total=False):
    request_id: str | None
    payload: dict[str, object] | None
    result_status: ControlActionResultStatus | str
    dispatch_id: str | None
    recovery_deadline_at: datetime | None


class _ControlActionArgs(_ControlActionOptional):
    thread_id: str
    action_type: ControlActionType | str
    idempotency_key: str


class _ReserveActionOptional(TypedDict, total=False):
    request_id: str | None
    payload: dict[str, object] | None
    dispatch_id: str | None
    recovery_deadline_at: datetime | None


class _ReserveActionArgs(_ReserveActionOptional):
    thread_id: str
    action_type: ControlActionType | str
    idempotency_key: str


async def create_control_action(
    session: AsyncSession, **kwargs: Unpack[_ControlActionArgs]
) -> ControlActionModel:
    """Append a durable control journal record."""
    thread_id = kwargs["thread_id"]
    resolved_type = _coerce(
        ControlActionType, kwargs["action_type"], label="control action type"
    )
    request_id = kwargs.get("request_id")
    payload = kwargs.get("payload")
    result_status = kwargs.get(
        "result_status", ControlActionResultStatus.ACCEPTED_NOT_APPLIED
    )
    dispatch_id = kwargs.get("dispatch_id")
    recovery_deadline_at = kwargs.get("recovery_deadline_at")
    requires_deadline = resolved_type in RECOVERY_ACTION_TYPES
    if requires_deadline != (recovery_deadline_at is not None):
        requirement = "requires" if requires_deadline else "cannot carry"
        raise ValueError(f"{resolved_type.value} {requirement} a recovery deadline")
    model = ControlActionModel(
        id=uuid4().hex,
        thread_id=thread_id,
        action_type=resolved_type.value,
        request_id=request_id,
        idempotency_key=kwargs["idempotency_key"],
        payload_json=_encode_payload(payload),
        result_status=_coerce(
            ControlActionResultStatus,
            result_status,
            label="control action result status",
        ).value,
        dispatch_id=dispatch_id or uuid4().hex,
        recovery_deadline_at=recovery_deadline_at,
    )
    return await save_model(session, model)


async def get_or_create_control_action(
    session: AsyncSession, **kwargs: Unpack[_ControlActionArgs]
) -> tuple[ControlActionModel, bool]:
    """Return the journal record for ``(thread_id, idempotency_key)``, inserting it
    only when absent.

    Idempotency-key inserts must replay as a no-op, never crash: a duplicate key is
    the SUCCESS signal of an already-applied action, so racing a UNIQUE violation on
    it contradicts the key's whole purpose. A retry or a restart re-derives the same
    key for an action already journaled, and the app must not die on the replay.
    Returns ``(action, created)`` where ``created`` is ``False`` for a replay.
    """
    thread_id = kwargs["thread_id"]
    idempotency_key = kwargs["idempotency_key"]
    existing = await get_control_action_by_idempotency_key(
        session,
        thread_id=thread_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        return existing, False
    # Atomic insert: wrap the INSERT in a SAVEPOINT so a concurrent boot that wins
    # the race raises IntegrityError on the UNIQUE key, rolls back only the nested
    # savepoint (leaving the outer transaction usable), and is then resolved by
    # re-reading the row the winner committed. This closes the lookup-then-insert
    # time-of-check/time-of-use window so the name matches the guarantee.
    try:
        async with session.begin_nested():
            created = await create_control_action(
                session,
                thread_id=thread_id,
                action_type=kwargs["action_type"],
                idempotency_key=idempotency_key,
                request_id=kwargs.get("request_id"),
                payload=kwargs.get("payload"),
                result_status=kwargs.get(
                    "result_status", ControlActionResultStatus.ACCEPTED_NOT_APPLIED
                ),
                dispatch_id=kwargs.get("dispatch_id"),
                recovery_deadline_at=kwargs.get("recovery_deadline_at"),
            )
    except IntegrityError:
        conflicting = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=idempotency_key,
        )
        if conflicting is None:
            raise
        return conflicting, False
    return created, True


async def reserve_control_action(
    session: AsyncSession, **kwargs: Unpack[_ReserveActionArgs]
) -> ControlActionReservation:
    """Reserve one durable intention and compare any replay with its winner."""
    resolved_type = _coerce(
        ControlActionType, kwargs["action_type"], label="control action type"
    ).value
    action, created = await get_or_create_control_action(
        session,
        thread_id=kwargs["thread_id"],
        action_type=resolved_type,
        idempotency_key=kwargs["idempotency_key"],
        request_id=kwargs.get("request_id"),
        payload=kwargs.get("payload"),
        dispatch_id=kwargs.get("dispatch_id"),
        recovery_deadline_at=kwargs.get("recovery_deadline_at"),
    )
    matches = (
        action.action_type == resolved_type
        and action.request_id == kwargs.get("request_id")
        and _payload_matches(action.payload_json, kwargs.get("payload"))
    )
    return ControlActionReservation(
        action=action, created=created, payload_matches=matches
    )


async def acquire_control_action_lease(
    session: AsyncSession,
    action_id: str,
    *,
    claim_token: str,
    claim_expires_at: datetime,
    now: datetime | None = None,
) -> bool:
    """Atomically acquire or renew one unapplied action lease."""
    if not claim_token:
        raise ValueError("claim_token must not be empty")
    acquired_at = now or utcnow()
    require_lease_window(acquired_at, claim_expires_at)
    stmt = (
        update(ControlActionModel)
        .where(
            ControlActionModel.id == action_id,
            ControlActionModel.applied_at.is_(None),
            CONTROL_ACTION_LEASE.acquirable_by(claim_token, acquired_at),
        )
        .values(**CONTROL_ACTION_LEASE.granted(claim_token, claim_expires_at))
    )
    return affected_rows(await session.execute(stmt)) == 1


async def commit_control_action_lease(
    session: AsyncSession,
    action_id: str,
    *,
    claim_token: str,
) -> ControlActionModel:
    """Commit verified lease ownership and its complete accepted projections."""
    await session.flush()
    action = await get_control_action(session, action_id, refresh=True)
    if (
        action is None
        or action.claim_token != claim_token
        or action.claim_expires_at is None
        or action.applied_at is not None
    ):
        raise RuntimeError("control action lease is not owned by this dispatcher")
    await session.commit()
    return action


def _held_unapplied(
    action_id: str, claim_token: str
) -> tuple[ColumnElement[bool], ...]:
    """Match the unapplied action that *claim_token* still owns."""
    return (
        ControlActionModel.id == action_id,
        ControlActionModel.applied_at.is_(None),
        CONTROL_ACTION_LEASE.held_by(claim_token),
    )


async def release_control_action_lease(
    session: AsyncSession,
    action_id: str,
    *,
    claim_token: str,
) -> bool:
    """Release ownership only for a dispatch proven not to have been delivered."""
    result = await session.execute(
        update(ControlActionModel)
        .where(*_held_unapplied(action_id, claim_token))
        .values(**CONTROL_ACTION_LEASE.released())
    )
    return affected_rows(result) == 1


async def settle_control_action_lease(
    session: AsyncSession,
    action_id: str,
    *,
    claim_token: str,
    applied_at: datetime | None = None,
    result_status: ControlActionResultStatus | str = ControlActionResultStatus.APPLIED,
) -> bool:
    """Settle application iff the caller still owns the durable lease."""
    result = await session.execute(
        update(ControlActionModel)
        .where(*_held_unapplied(action_id, claim_token))
        .values(
            applied_at=applied_at or utcnow(),
            result_status=_coerce(
                ControlActionResultStatus,
                result_status,
                label="control action result status",
            ).value,
            **CONTROL_ACTION_LEASE.released(),
        )
    )
    return affected_rows(result) == 1


async def _read_action(
    session: AsyncSession, *where: ColumnElement[bool], lock: bool
) -> ControlActionModel | None:
    stmt = select(ControlActionModel).where(*where)
    if lock:
        # The row is re-read rather than taken from the identity map: a copy
        # loaded before the lock was won is exactly what the lock exists to
        # keep a caller from deciding on.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_control_action(
    session: AsyncSession,
    action_id: str,
    *,
    refresh: bool = False,
    lock: bool = False,
) -> ControlActionModel | None:
    """Return one journal action by id.

    ``refresh`` re-reads the row from the database instead of the identity map,
    for a caller whose copy may predate a write another statement made. ``lock``
    takes the row's write lock and reads it afresh, for a caller that decides on
    the row and then writes it.
    """
    if lock:
        return await _read_action(
            session, ControlActionModel.id == action_id, lock=True
        )
    return await session.get(ControlActionModel, action_id, populate_existing=refresh)


async def get_control_action_by_idempotency_key(
    session: AsyncSession,
    *,
    thread_id: str,
    idempotency_key: str,
    lock: bool = False,
) -> ControlActionModel | None:
    """Return the run's action admitted under ``idempotency_key``.

    ``lock`` takes the row's write lock and reads it afresh, for a caller that
    decides on the row and then writes it.
    """
    return await _read_action(
        session,
        ControlActionModel.thread_id == thread_id,
        ControlActionModel.idempotency_key == idempotency_key,
        lock=lock,
    )


async def idempotency_key_admitted(
    session: AsyncSession, *, thread_id: str, idempotency_key: str
) -> bool:
    """Whether the run already holds an action admitted under ``idempotency_key``.

    Answered without loading the action, whose accepted payload can be large.
    """
    return (
        await session.scalar(
            select(ControlActionModel.id)
            .where(
                ControlActionModel.thread_id == thread_id,
                ControlActionModel.idempotency_key == idempotency_key,
            )
            .limit(1)
        )
    ) is not None


async def get_control_action_by_dispatch_id(
    session: AsyncSession,
    *,
    thread_id: str,
    dispatch_id: str,
    lock: bool = False,
) -> ControlActionModel | None:
    """Return the exact journal action named by a worker application receipt.

    ``lock`` takes the row's write lock and reads it afresh, for a caller that
    decides on the row and then writes it.
    """
    return await _read_action(
        session,
        ControlActionModel.thread_id == thread_id,
        ControlActionModel.dispatch_id == dispatch_id,
        lock=lock,
    )


async def get_latest_control_action(
    session: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str | None = None,
) -> ControlActionModel | None:
    stmt = (
        select(ControlActionModel)
        .where(ControlActionModel.thread_id == thread_id)
        .order_by(ControlActionModel.requested_at.desc())
    )
    if action_type is not None:
        stmt = stmt.where(
            ControlActionModel.action_type
            == _coerce(
                ControlActionType, action_type, label="control action type"
            ).value
        )
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


def select_recoverable_actions(
    *window: ColumnElement[bool],
) -> Select[tuple[ControlActionModel]]:
    """Select the unapplied recoverable actions that an active run still writes.

    Only an action its active run still names as the writer qualifies, since an
    action another writer has superseded has nothing left to settle. *window*
    bounds the recovery deadline; ordering and paging are the caller's.
    """
    return (
        select(ControlActionModel)
        .join(ThreadModel, ThreadModel.id == ControlActionModel.thread_id)
        .where(
            ControlActionModel.action_type.in_(
                action.value for action in RECOVERY_ACTION_TYPES
            ),
            ControlActionModel.applied_at.is_(None),
            ControlActionModel.recovery_deadline_at.is_not(None),
            ThreadModel.is_active.is_(True),
            thread_owned_by(
                ControlActionModel.action_type, ControlActionModel.dispatch_id
            ),
            *window,
        )
    )


async def overdue_recovery_actions(
    session: AsyncSession, *, observed_at: datetime, limit: int
) -> Sequence[ControlActionModel]:
    """Return unapplied recoverable actions whose deadline has passed.

    The longest overdue come first.
    """
    return (
        await session.scalars(
            select_recoverable_actions(
                ControlActionModel.recovery_deadline_at <= observed_at
            )
            .order_by(ControlActionModel.recovery_deadline_at)
            .limit(limit)
        )
    ).all()


async def get_writer_action(
    session: AsyncSession,
    *,
    thread_id: str,
    authority: RunWriteAuthority,
    deadline_at: datetime,
    unapplied_only: bool,
) -> ControlActionModel | None:
    """Return the journal row *authority* names as a run's writer.

    The row must carry *deadline_at*, the recovery deadline its acceptance was
    given. ``unapplied_only`` also requires it to be unapplied.
    """
    clauses = [
        _journal_row_for(thread_id, authority),
        ControlActionModel.recovery_deadline_at == deadline_at,
    ]
    if unapplied_only:
        clauses.append(ControlActionModel.applied_at.is_(None))
    return await session.scalar(select(ControlActionModel).where(*clauses))


def _settle_applied(
    action: ControlActionModel,
    *,
    applied_at: datetime,
    result_status: ControlActionResultStatus | str,
) -> None:
    action.applied_at = applied_at
    action.result_status = _coerce(
        ControlActionResultStatus, result_status, label="control action result status"
    ).value
    clear_lease(action)


def _settle_duplicate(action: ControlActionModel) -> None:
    action.result_status = ControlActionResultStatus.DUPLICATE.value


def _settle_superseded(action: ControlActionModel) -> None:
    action.result_status = ControlActionResultStatus.SUPERSEDED.value
    action.superseded_at = utcnow()


async def _mutate_action(
    session: AsyncSession,
    action_id: str,
    mutation: Callable[[ControlActionModel], None],
) -> ControlActionModel | None:
    """Apply *mutation* to the journal action and flush it, or return ``None``."""
    action = await get_control_action(session, action_id)
    if action is None:
        return None
    mutation(action)
    await session.flush()
    return action


async def mark_control_action_applied(
    session: AsyncSession,
    action_id: str,
    *,
    applied_at: datetime | None = None,
    result_status: ControlActionResultStatus | str = ControlActionResultStatus.APPLIED,
) -> ControlActionModel | None:
    return await _mutate_action(
        session,
        action_id,
        lambda action: _settle_applied(
            action, applied_at=applied_at or utcnow(), result_status=result_status
        ),
    )


async def mark_control_action_duplicate(
    session: AsyncSession,
    action_id: str,
) -> ControlActionModel | None:
    return await _mutate_action(session, action_id, _settle_duplicate)


async def mark_control_action_superseded(
    session: AsyncSession,
    action_id: str,
) -> ControlActionModel | None:
    return await _mutate_action(session, action_id, _settle_superseded)


async def count_queued_continuations(
    session: AsyncSession, *, thread_id: str | None = None
) -> int:
    """Return how many continuations are waiting, on one run or across every run."""
    stmt = (
        select(func.count())
        .select_from(ControlActionModel)
        .where(ControlActionModel.result_status == _QUEUED)
    )
    if thread_id is not None:
        stmt = stmt.where(ControlActionModel.thread_id == thread_id)
    return (await session.execute(stmt)).scalar_one()


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


async def enqueue_continuation(
    session: AsyncSession, action: ControlActionModel
) -> int:
    """Mark a reserved action as waiting and return the place it was given.

    The place is the next free one on the action's run. The caller holds the
    run's write lock, so two admissions cannot be given the same one.
    """
    position = await next_queue_position(session, thread_id=action.thread_id)
    action.result_status = _QUEUED
    action.queue_position = position
    await session.flush()
    return position


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


async def reject_queued_continuations(
    session: AsyncSession, *, thread_id: str, rejected_at: datetime
) -> int:
    """Settle every continuation still waiting on a run as an invalid-state refusal.

    The place each was given stays, so the record says what was refused and where
    it sat. Returns how many were settled.
    """
    waiting = (
        await session.scalars(
            select(ControlActionModel)
            .where(
                ControlActionModel.thread_id == thread_id,
                ControlActionModel.result_status == _QUEUED,
            )
            .with_for_update()
        )
    ).all()
    for action in waiting:
        # One statement moves the row out of "waiting" and into "settled":
        # the journal refuses a queued row that is already applied, so these
        # two cannot be written apart.
        _settle_applied(
            action,
            applied_at=rejected_at,
            result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
        )
    if waiting:
        await session.flush()
    return len(waiting)


async def has_live_queued_continuation_lease(
    session: AsyncSession, *, thread_id: str, observed_at: datetime
) -> bool:
    """Whether a continuation waiting on this run holds a lease that has not lapsed.

    A run between turns, whose waiting continuation has not been promoted yet, is
    live with no worker, which looks exactly like a writer that died. The lease
    on the waiting reservation tells them apart: while it is held a promoter
    answers for the run, and once it lapses nobody does.
    """
    return (
        await session.scalar(
            select(ControlActionModel.id)
            .where(
                ControlActionModel.thread_id == thread_id,
                ControlActionModel.result_status == _QUEUED,
                CONTROL_ACTION_LEASE.live(observed_at),
            )
            .limit(1)
        )
    ) is not None


async def persist_graph_action_receipt(
    session: AsyncSession,
    *,
    receipt: GraphActionReceipt,
    expectation: ThreadWriteExpectation,
) -> GraphActionReceipt | None:
    """Persist once under exact ownership; every retry returns the same receipt."""
    authority = expectation.authority
    if not authority.owned_by(
        receipt.action_type,
        receipt.dispatch_id,
        writer_generation=receipt.writer_generation,
        run_revision=receipt.run_revision,
    ):
        return None
    owns_thread = exists(
        select(ThreadModel.id).where(
            ThreadModel.id == receipt.thread_id,
            ThreadModel.status == expectation.status.value,
            thread_owned_by(
                authority.action_type,
                authority.action_receipt_id,
                writer_generation=authority.writer_generation,
                run_revision=authority.run_revision,
            ),
        )
    )
    identity = (
        ControlActionModel.id == receipt.action_id,
        ControlActionModel.thread_id == receipt.thread_id,
        ControlActionModel.dispatch_id == receipt.dispatch_id,
        ControlActionModel.action_type == receipt.action_type,
    )
    await session.execute(
        update(ControlActionModel)
        .where(
            *identity,
            ControlActionModel.graph_receipt_json.is_(None),
            owns_thread,
        )
        .values(graph_receipt_json=receipt.model_dump_json())
        .execution_options(synchronize_session=False)
    )
    encoded = await session.scalar(
        select(ControlActionModel.graph_receipt_json).where(*identity, owns_thread)
    )
    if encoded is None:
        return None
    try:
        stored = GraphActionReceipt.model_validate_json(encoded)
    except ValidationError:
        return None
    # State-only elections may advance revision while this action remains the
    # writer. They cannot change the original dispatch or its graph evidence.
    if not stored.matches(
        thread_id=receipt.thread_id,
        action_id=receipt.action_id,
        action_type=receipt.action_type,
        dispatch_id=receipt.dispatch_id,
        payload_fingerprint=receipt.payload_fingerprint,
        authority=authority,
    ):
        return None
    return stored
