"""Permission repository — permission request lifecycle and control action journal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

from ..thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
)
from ._helpers import (
    _coerce_control_action_type,
    _coerce_control_result,
    _coerce_permission_request_status,
    save_model,
)
from .models import ControlActionModel, PermissionRequestModel, utcnow

__all__ = [
    "ControlActionReservation",
    "acquire_control_action_lease",
    "commit_control_action_lease",
    "create_control_action",
    "expire_pending_permission_requests",
    "get_control_action_by_dispatch_id",
    "get_control_action_by_idempotency_key",
    "get_control_actions_by_idempotency_keys",
    "get_latest_control_action",
    "get_or_create_control_action",
    "get_pending_permission_requests",
    "get_permission_request",
    "get_threads_with_pending_permission_requests",
    "mark_control_action_applied",
    "mark_control_action_duplicate",
    "mark_control_action_superseded",
    "mark_permission_request_applied",
    "record_permission_request",
    "record_permission_response_submission",
    "release_control_action_lease",
    "reserve_control_action",
    "reset_permission_response_submission",
    "settle_control_action_lease",
    "supersede_permission_requests",
]


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


_IN_CLAUSE_CHUNK = 500
"""Bound on identifiers per ``IN`` clause, under every backend's parameter cap."""


def _encode_payload(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _payload_matches(stored: str | None, expected: dict[str, object] | None) -> bool:
    if stored is None:
        return expected is None
    try:
        return json.loads(stored) == expected
    except json.JSONDecodeError:
        return False


async def record_permission_request(
    session: AsyncSession,
    *,
    request_id: str,
    thread_id: str,
    pause_reason_type: str,
    description: str,
    allowed_options: list[dict[str, object]],
    tool_call: str | None = None,
    worker_generation: int = 0,
) -> PermissionRequestModel:
    """Create or refresh a durable permission request."""
    existing = await session.get(PermissionRequestModel, request_id)
    allowed_options_json = json.dumps(allowed_options)
    if existing is not None:
        existing.pause_reason_type = pause_reason_type
        existing.description = description
        existing.allowed_options_json = allowed_options_json
        existing.tool_call = tool_call
        existing.worker_generation = worker_generation
        existing.request_status = PermissionRequestStatus.PENDING.value
        existing.response_option_id = None
        existing.idempotency_key = None
        existing.responded_at = None
        existing.applied_at = None
        await session.flush()
        return existing

    model = PermissionRequestModel(
        request_id=request_id,
        thread_id=thread_id,
        pause_reason_type=pause_reason_type,
        tool_call=tool_call,
        description=description,
        allowed_options_json=allowed_options_json,
        request_status=PermissionRequestStatus.PENDING.value,
        worker_generation=worker_generation,
    )
    return await save_model(session, model)


async def get_permission_request(
    session: AsyncSession, request_id: str
) -> PermissionRequestModel | None:
    return await session.get(PermissionRequestModel, request_id)


async def get_pending_permission_requests(
    session: AsyncSession,
    *,
    thread_id: str | None = None,
    include_answered_pending_apply: bool = True,
) -> Sequence[PermissionRequestModel]:
    statuses = [PermissionRequestStatus.PENDING.value]
    if include_answered_pending_apply:
        statuses.append(PermissionRequestStatus.ANSWERED_PENDING_APPLY.value)
    stmt = select(PermissionRequestModel).where(
        PermissionRequestModel.request_status.in_(statuses)
    )
    if thread_id is not None:
        stmt = stmt.where(PermissionRequestModel.thread_id == thread_id)
    stmt = stmt.order_by(PermissionRequestModel.created_at.asc())
    return (await session.execute(stmt)).scalars().all()


async def get_threads_with_pending_permission_requests(
    session: AsyncSession,
    thread_ids: Sequence[str],
    *,
    include_answered_pending_apply: bool = True,
) -> set[str]:
    """Return which of ``thread_ids`` hold at least one pending request.

    Startup reconciliation asked this one thread at a time, costing a round trip
    per non-terminal thread before the gateway could serve. The lookup is a
    membership test over the whole backlog, so it is issued as one query per
    chunk instead.
    """
    statuses = [PermissionRequestStatus.PENDING.value]
    if include_answered_pending_apply:
        statuses.append(PermissionRequestStatus.ANSWERED_PENDING_APPLY.value)

    unique_ids = list(dict.fromkeys(thread_ids))
    found: set[str] = set()
    # Chunked because the backlog size is unbounded and every supported backend
    # caps the number of bound parameters in a single statement.
    for start in range(0, len(unique_ids), _IN_CLAUSE_CHUNK):
        chunk = unique_ids[start : start + _IN_CLAUSE_CHUNK]
        stmt = (
            select(PermissionRequestModel.thread_id)
            .where(
                PermissionRequestModel.thread_id.in_(chunk),
                PermissionRequestModel.request_status.in_(statuses),
            )
            .distinct()
        )
        found.update((await session.execute(stmt)).scalars().all())
    return found


async def record_permission_response_submission(
    session: AsyncSession,
    *,
    request_id: str,
    option_id: str,
    idempotency_key: str,
) -> PermissionRequestModel | None:
    permission = await session.get(PermissionRequestModel, request_id)
    if permission is None:
        return None
    permission.response_option_id = option_id
    permission.idempotency_key = idempotency_key
    permission.request_status = PermissionRequestStatus.ANSWERED_PENDING_APPLY.value
    permission.responded_at = utcnow()
    await session.flush()
    return permission


async def mark_permission_request_applied(
    session: AsyncSession,
    *,
    request_id: str,
    status: PermissionRequestStatus | str = PermissionRequestStatus.APPLIED,
) -> PermissionRequestModel | None:
    permission = await session.get(PermissionRequestModel, request_id)
    if permission is None:
        return None
    permission.request_status = _coerce_permission_request_status(status).value
    permission.applied_at = utcnow()
    await session.flush()
    return permission


async def reset_permission_response_submission(
    session: AsyncSession,
    *,
    request_id: str,
) -> PermissionRequestModel | None:
    """Roll back a submitted response when resume dispatch never succeeded."""
    permission = await session.get(PermissionRequestModel, request_id)
    if permission is None:
        return None
    permission.request_status = PermissionRequestStatus.PENDING.value
    permission.response_option_id = None
    permission.idempotency_key = None
    permission.responded_at = None
    await session.flush()
    return permission


async def supersede_permission_requests(
    session: AsyncSession,
    *,
    thread_id: str,
    pause_reason_type: str | None = None,
    except_request_id: str | None = None,
) -> int:
    """Mark earlier pending permission requests as superseded."""
    stmt = select(PermissionRequestModel).where(
        PermissionRequestModel.thread_id == thread_id,
        PermissionRequestModel.request_status.in_(
            [
                PermissionRequestStatus.PENDING.value,
                PermissionRequestStatus.ANSWERED_PENDING_APPLY.value,
            ]
        ),
    )
    if pause_reason_type is not None:
        stmt = stmt.where(PermissionRequestModel.pause_reason_type == pause_reason_type)
    permissions = (await session.execute(stmt)).scalars().all()
    updated = 0
    for permission in permissions:
        if permission.request_id == except_request_id:
            continue
        permission.request_status = PermissionRequestStatus.SUPERSEDED.value
        permission.applied_at = permission.applied_at or utcnow()
        updated += 1
    await session.flush()
    return updated


async def expire_pending_permission_requests(
    session: AsyncSession,
    *,
    thread_id: str,
) -> int:
    stmt = select(PermissionRequestModel).where(
        PermissionRequestModel.thread_id == thread_id,
        PermissionRequestModel.request_status.in_(
            [
                PermissionRequestStatus.PENDING.value,
                PermissionRequestStatus.ANSWERED_PENDING_APPLY.value,
            ]
        ),
    )
    permissions = (await session.execute(stmt)).scalars().all()
    for permission in permissions:
        permission.request_status = (
            PermissionRequestStatus.EXPIRED_BY_TERMINAL_STATE.value
        )
        permission.applied_at = permission.applied_at or utcnow()
    await session.flush()
    return len(permissions)


async def create_control_action(
    session: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str,
    idempotency_key: str,
    request_id: str | None = None,
    payload: dict[str, object] | None = None,
    worker_generation: int = 0,
    result_status: ControlActionResultStatus | str = (
        ControlActionResultStatus.ACCEPTED_NOT_APPLIED
    ),
    dispatch_id: str | None = None,
) -> ControlActionModel:
    """Append a durable control journal record."""
    model = ControlActionModel(
        id=uuid4().hex,
        thread_id=thread_id,
        action_type=_coerce_control_action_type(action_type).value,
        request_id=request_id,
        idempotency_key=idempotency_key,
        payload_json=_encode_payload(payload),
        worker_generation=worker_generation,
        result_status=_coerce_control_result(result_status).value,
        dispatch_id=dispatch_id or uuid4().hex,
    )
    return await save_model(session, model)


async def get_or_create_control_action(
    session: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str,
    idempotency_key: str,
    request_id: str | None = None,
    payload: dict[str, object] | None = None,
    worker_generation: int = 0,
    result_status: ControlActionResultStatus | str = (
        ControlActionResultStatus.ACCEPTED_NOT_APPLIED
    ),
    dispatch_id: str | None = None,
    absence_already_resolved: bool = False,
) -> tuple[ControlActionModel, bool]:
    """Return the journal record for ``(thread_id, idempotency_key)``, inserting it
    only when absent.

    Idempotency-key inserts must replay as a no-op, never crash: a duplicate key is
    the SUCCESS signal of an already-applied action, so racing a UNIQUE violation on
    it contradicts the key's whole purpose. Startup reconciliation re-derives the
    same key across boots for a thread that has not advanced its epoch (e.g. rows
    written before the epoch-increment fix), and the app must not die on the second
    boot. Returns ``(action, created)`` where ``created`` is ``False`` for a replay.

    ``absence_already_resolved`` skips only the existence pre-read, for a caller
    that resolved the same absence for a whole batch in one query. It weakens no
    guarantee: the pre-read never was the authority - the SAVEPOINT-wrapped insert
    and its ``IntegrityError`` re-read are, precisely because a concurrent writer
    can land between any pre-read and the insert.
    """
    if not absence_already_resolved:
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
                action_type=action_type,
                idempotency_key=idempotency_key,
                request_id=request_id,
                payload=payload,
                worker_generation=worker_generation,
                result_status=result_status,
                dispatch_id=dispatch_id,
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
    session: AsyncSession,
    *,
    thread_id: str,
    action_type: ControlActionType | str,
    idempotency_key: str,
    request_id: str | None = None,
    payload: dict[str, object] | None = None,
    worker_generation: int = 0,
    dispatch_id: str | None = None,
) -> ControlActionReservation:
    """Reserve one durable intention and compare any replay with its winner."""
    resolved_type = _coerce_control_action_type(action_type).value
    action, created = await get_or_create_control_action(
        session,
        thread_id=thread_id,
        action_type=resolved_type,
        idempotency_key=idempotency_key,
        request_id=request_id,
        payload=payload,
        worker_generation=worker_generation,
        dispatch_id=dispatch_id,
    )
    matches = (
        action.action_type == resolved_type
        and action.request_id == request_id
        and _payload_matches(action.payload_json, payload)
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
    if claim_expires_at <= acquired_at:
        raise ValueError("claim_expires_at must be later than now")
    stmt = (
        update(ControlActionModel)
        .where(
            ControlActionModel.id == action_id,
            ControlActionModel.applied_at.is_(None),
            or_(
                ControlActionModel.claim_token.is_(None),
                ControlActionModel.claim_expires_at.is_(None),
                ControlActionModel.claim_expires_at <= acquired_at,
                ControlActionModel.claim_token == claim_token,
            ),
        )
        .values(claim_token=claim_token, claim_expires_at=claim_expires_at)
    )
    result = cast("CursorResult[Any]", await session.execute(stmt))
    return result.rowcount == 1


async def commit_control_action_lease(
    session: AsyncSession,
    action_id: str,
    *,
    claim_token: str,
) -> ControlActionModel:
    """Commit a verified lease before its owner performs network dispatch.

    This is the one repository function that commits, against the convention
    documented at :func:`vaultspec_a2a.control.permission_service` that the
    dispatch stage owns the commit. The commit is load-bearing and cannot move:
    durable ownership has to be visible to every other process *before* the
    network dispatch happens, and the lease ``UPDATE`` lives in this session's
    open transaction, so no other session could commit it.

    What the commit cannot see is anything else the caller staged on the same
    session, which it would publish as a side effect. The guard below refuses
    that composition instead of silently committing it: the transaction handed
    here must contain the claim election and nothing else.
    """
    _assert_no_foreign_pending_state(session)
    action = await session.get(ControlActionModel, action_id, populate_existing=True)
    if (
        action is None
        or action.claim_token != claim_token
        or action.claim_expires_at is None
        or action.applied_at is not None
    ):
        raise RuntimeError("control action lease is not owned by this dispatcher")
    await session.commit()
    return action


def _assert_no_foreign_pending_state(session: AsyncSession) -> None:
    """Refuse to commit a session carrying unflushed work that is not the lease.

    Detection is limited to ORM state the session has not yet flushed - inserts,
    deletes, and attribute mutations still held in the unit of work. Work the
    caller already flushed is indistinguishable at this seam from the claim's own
    flushed rows, so the contract stated above remains the caller's to honour;
    this closes the case the session can actually see.
    """
    sync_session = session.sync_session
    pending: list[object] = [
        *sync_session.new,
        *sync_session.deleted,
        *(obj for obj in sync_session.dirty if sync_session.is_modified(obj)),
    ]
    if pending:
        kinds = sorted({type(obj).__name__ for obj in pending})
        raise RuntimeError(
            "control action lease commit refused: the session carries unflushed "
            f"changes to {kinds}. Committing the lease would publish them as a "
            "side effect. Commit or discard that work before claiming the lease."
        )


async def release_control_action_lease(
    session: AsyncSession,
    action_id: str,
    *,
    claim_token: str,
) -> bool:
    """Release ownership only for a dispatch proven not to have been delivered."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(ControlActionModel)
            .where(
                ControlActionModel.id == action_id,
                ControlActionModel.applied_at.is_(None),
                ControlActionModel.claim_token == claim_token,
            )
            .values(claim_token=None, claim_expires_at=None)
        ),
    )
    return result.rowcount == 1


async def settle_control_action_lease(
    session: AsyncSession,
    action_id: str,
    *,
    claim_token: str,
    applied_at: datetime | None = None,
    result_status: ControlActionResultStatus | str = ControlActionResultStatus.APPLIED,
) -> bool:
    """Settle application iff the caller still owns the durable lease."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(ControlActionModel)
            .where(
                ControlActionModel.id == action_id,
                ControlActionModel.applied_at.is_(None),
                ControlActionModel.claim_token == claim_token,
            )
            .values(
                applied_at=applied_at or utcnow(),
                result_status=_coerce_control_result(result_status).value,
                claim_token=None,
                claim_expires_at=None,
            )
        ),
    )
    return result.rowcount == 1


async def get_control_action_by_idempotency_key(
    session: AsyncSession,
    *,
    thread_id: str,
    idempotency_key: str,
) -> ControlActionModel | None:
    stmt = select(ControlActionModel).where(
        ControlActionModel.thread_id == thread_id,
        ControlActionModel.idempotency_key == idempotency_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_control_actions_by_idempotency_keys(
    session: AsyncSession,
    keys: Sequence[tuple[str, str]],
) -> dict[tuple[str, str], ControlActionModel]:
    """Resolve many ``(thread_id, idempotency_key)`` journal rows in one sweep.

    Startup reconciliation derives every key it will need up front, so the
    existence lookup that :func:`get_or_create_control_action` performs per row
    can be answered for the whole batch before the loop starts. A rebooted
    backlog is the common case there, and every key in it already exists.
    """
    unique_keys = list(dict.fromkeys(keys))
    resolved: dict[tuple[str, str], ControlActionModel] = {}
    for start in range(0, len(unique_keys), _IN_CLAUSE_CHUNK):
        chunk = unique_keys[start : start + _IN_CLAUSE_CHUNK]
        stmt = select(ControlActionModel).where(
            ControlActionModel.thread_id.in_({thread_id for thread_id, _ in chunk}),
            ControlActionModel.idempotency_key.in_({key for _, key in chunk}),
        )
        wanted = set(chunk)
        for action in (await session.execute(stmt)).scalars().all():
            identity = (action.thread_id, action.idempotency_key)
            # The two ``IN`` sets form a cross product wider than the requested
            # pairs; keep only the pairs actually asked for.
            if identity in wanted:
                resolved[identity] = action
    return resolved


async def get_control_action_by_dispatch_id(
    session: AsyncSession,
    *,
    thread_id: str,
    dispatch_id: str,
) -> ControlActionModel | None:
    """Return the exact journal action named by a worker application receipt."""
    stmt = select(ControlActionModel).where(
        ControlActionModel.thread_id == thread_id,
        ControlActionModel.dispatch_id == dispatch_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


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
            == _coerce_control_action_type(action_type).value
        )
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def mark_control_action_applied(
    session: AsyncSession,
    action_id: str,
    *,
    applied_at: datetime | None = None,
    result_status: ControlActionResultStatus | str = ControlActionResultStatus.APPLIED,
) -> ControlActionModel | None:
    action = await session.get(ControlActionModel, action_id)
    if action is None:
        return None
    action.applied_at = applied_at or utcnow()
    action.result_status = _coerce_control_result(result_status).value
    action.claim_token = None
    action.claim_expires_at = None
    await session.flush()
    return action


async def mark_control_action_duplicate(
    session: AsyncSession,
    action_id: str,
) -> ControlActionModel | None:
    action = await session.get(ControlActionModel, action_id)
    if action is None:
        return None
    action.result_status = ControlActionResultStatus.DUPLICATE.value
    await session.flush()
    return action


async def mark_control_action_superseded(
    session: AsyncSession,
    action_id: str,
) -> ControlActionModel | None:
    action = await session.get(ControlActionModel, action_id)
    if action is None:
        return None
    action.result_status = ControlActionResultStatus.SUPERSEDED.value
    action.superseded_at = utcnow()
    await session.flush()
    return action
