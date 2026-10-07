"""Permission repository — permission requests and the permission decision log."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack, cast
from uuid import uuid4

from sqlalchemy import select

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

from ..thread.enums import (
    TERMINAL_STATUS_VALUES,
    InterruptType,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
)
from ._helpers import _coerce, save_model
from .models import PermissionLogModel, PermissionRequestModel, ThreadModel, utcnow
from .thread_repository import path_safe_run_id_clause

__all__ = [
    "PendingPermission",
    "actionable_pending_permissions",
    "append_permission_log",
    "decode_allowed_options",
    "expire_pending_permission_requests",
    "get_pending_permission_requests",
    "get_permission_logs_by_thread",
    "get_permission_request",
    "mark_permission_request_applied",
    "outstanding_permission_pause",
    "pending_document_approval_thread",
    "record_permission_request",
    "record_permission_response_submission",
    "reset_permission_response_submission",
    "supersede_permission_requests",
]


@dataclass(frozen=True, slots=True)
class PendingPermission:
    """One unanswered permission request on a live run, its options read once.

    ``offered`` is the decoded option list, or ``None`` when the stored column
    cannot be read, which a caller that must fail closed tells apart from a row
    that offered nothing. ``checkpoint_unavailable`` is the run's recorded
    checkpoint posture, carried here so a query across many runs needs no second
    read of their threads.
    """

    request: PermissionRequestModel
    offered: list[object] | None
    checkpoint_unavailable: bool


_OUTSTANDING_PERMISSION_STATUSES: tuple[str, str] = (
    PermissionRequestStatus.PENDING.value,
    PermissionRequestStatus.ANSWERED_PENDING_APPLY.value,
)
"""Every status a permission request holds before it is settled.

Declared once so the four functions below that ask "which requests still need
attention" cannot drift apart on what "outstanding" means. Two of them
(``supersede_permission_requests``, ``expire_pending_permission_requests``)
always mean both members; the other two toggle ``ANSWERED_PENDING_APPLY`` in
or out via ``include_answered_pending_apply``, so the toggle stays an explicit
argument at those call sites rather than being folded into this constant.
"""


class _PermissionRequestOptional(TypedDict, total=False):
    tool_call: str | None


class _PermissionRequestArgs(_PermissionRequestOptional):
    request_id: str
    thread_id: str
    pause_reason_type: str
    description: str
    allowed_options: list[dict[str, object]]


async def record_permission_request(
    session: AsyncSession,
    **kwargs: Unpack[_PermissionRequestArgs],
) -> PermissionRequestModel:
    """Create or refresh a durable permission request."""
    request_id = kwargs["request_id"]
    thread_id = kwargs["thread_id"]
    pause_reason_type = kwargs["pause_reason_type"]
    description = kwargs["description"]
    allowed_options = kwargs["allowed_options"]
    tool_call = kwargs.get("tool_call")
    existing = await session.get(PermissionRequestModel, request_id)
    allowed_options_json = json.dumps(allowed_options)
    if existing is not None:
        existing.pause_reason_type = pause_reason_type
        existing.description = description
        existing.allowed_options_json = allowed_options_json
        existing.tool_call = tool_call
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
    )
    return await save_model(session, model)


def decode_allowed_options(raw_options_json: str | None) -> list[object] | None:
    """Decode the offered options of a durable permission row.

    An absent column offered nothing, so it decodes to an empty list. A column
    that is present but empty, malformed JSON, or not a JSON list is unreadable
    and decodes to ``None``, so a caller that must fail closed on a broken row
    can tell it apart from a row that offered nothing.
    """
    if raw_options_json is None:
        return []
    try:
        decoded: object = json.loads(raw_options_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return cast("list[object]", decoded) if isinstance(decoded, list) else None


async def get_permission_request(
    session: AsyncSession, request_id: str
) -> PermissionRequestModel | None:
    return await session.get(PermissionRequestModel, request_id)


async def get_pending_permission_requests(
    session: AsyncSession,
    *,
    thread_id: str | None = None,
    pause_reason_type: str | Collection[str] | None = None,
    include_answered_pending_apply: bool = True,
) -> Sequence[PermissionRequestModel]:
    """Return unsettled permission requests, oldest first.

    ``thread_id`` and ``pause_reason_type`` narrow the rows in the query itself,
    so a caller that wants some kinds of pause never loads and filters the rest.
    ``pause_reason_type`` names one cause or any collection of them.
    """
    statuses = (
        _OUTSTANDING_PERMISSION_STATUSES
        if include_answered_pending_apply
        else (PermissionRequestStatus.PENDING.value,)
    )
    stmt = select(PermissionRequestModel).where(
        PermissionRequestModel.request_status.in_(statuses)
    )
    if thread_id is not None:
        stmt = stmt.where(PermissionRequestModel.thread_id == thread_id)
    if pause_reason_type is not None:
        causes = (
            (pause_reason_type,)
            if isinstance(pause_reason_type, str)
            else tuple(pause_reason_type)
        )
        stmt = stmt.where(PermissionRequestModel.pause_reason_type.in_(causes))
    stmt = stmt.order_by(PermissionRequestModel.created_at.asc())
    return (await session.execute(stmt)).scalars().all()


async def actionable_pending_permissions(
    session: AsyncSession,
    *,
    thread_id: str | None = None,
) -> list[PendingPermission]:
    """Return the unanswered permission requests on live runs, oldest first.

    The one reading of "which permissions still wait on someone" shared by the
    team status, the run status and the run listing. A run is live when its row
    exists under a path-safe id and has not settled, so a request orphaned from
    its run, left open on a settled run, or filed under an id the respond route
    cannot address is never offered. The last matters beyond the route: one such
    id handed to the status serializer would fail the whole response and hide
    every other run's live question. ``thread_id`` narrows the query to one run.

    Every live request is returned with its options already read, and the
    surfaces keep their own stance on the ones that are not actionable: the team
    status offers only requests that offer a usable option on a run with
    checkpoint truth, while the run status degrades on an unreadable one and the
    listing reads plan approvals alone. The run's recorded checkpoint posture is
    judged by the team status only, because the run status and the listing read
    their checkpoint afresh.
    """
    stmt = (
        select(PermissionRequestModel, ThreadModel.repair_status)
        .select_from(PermissionRequestModel)
        .join(ThreadModel, ThreadModel.id == PermissionRequestModel.thread_id)
        .where(
            PermissionRequestModel.request_status
            == PermissionRequestStatus.PENDING.value,
            ThreadModel.status.not_in(TERMINAL_STATUS_VALUES),
            path_safe_run_id_clause(),
        )
        .order_by(PermissionRequestModel.created_at.asc())
    )
    if thread_id is not None:
        stmt = stmt.where(PermissionRequestModel.thread_id == thread_id)
    return [
        PendingPermission(
            request=request,
            offered=decode_allowed_options(request.allowed_options_json),
            checkpoint_unavailable=(
                repair_status == RepairStatus.CHECKPOINT_UNAVAILABLE.value
            ),
        )
        for request, repair_status in (await session.execute(stmt)).all()
    ]


async def outstanding_permission_pause(
    session: AsyncSession, *, thread_id: str
) -> tuple[str, str] | None:
    """Return the request id and status of the pause a run is holding.

    The oldest request that is not settled, which is the one a parked run is
    actually waiting on. Returned as a pair rather than a bare id because the
    two outstanding statuses call for different advice: one still needs an
    answer, the other already has one and is being applied. ``None`` says the
    journal holds no permission pause for this run at all - for a parked run,
    that means the pause is an interrupt rather than a permission request.
    """
    row = (
        await session.execute(
            select(
                PermissionRequestModel.request_id,
                PermissionRequestModel.request_status,
            )
            .where(
                PermissionRequestModel.thread_id == thread_id,
                PermissionRequestModel.request_status.in_(
                    _OUTSTANDING_PERMISSION_STATUSES
                ),
            )
            .order_by(PermissionRequestModel.created_at.asc())
            .limit(1)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def pending_document_approval_thread(
    session: AsyncSession,
    *,
    request_ids: Collection[str],
) -> str | None:
    """Return the parked run whose pending document approval is in ``request_ids``.

    A document gate records its pause with the proposal it parked on as the
    request id, so an engine verdict naming that proposal reaches its run through
    this row alone, by primary key, however many runs are parked. Only a run
    still ``INPUT_REQUIRED`` qualifies: an applied verdict resume settles the row
    and moves the run on, so a replayed verdict finds nothing and is a no-op.
    """
    candidates = [request_id for request_id in dict.fromkeys(request_ids) if request_id]
    if not candidates:
        return None
    stmt = (
        select(PermissionRequestModel.thread_id)
        .join(ThreadModel, ThreadModel.id == PermissionRequestModel.thread_id)
        .where(
            PermissionRequestModel.request_id.in_(candidates),
            PermissionRequestModel.pause_reason_type
            == InterruptType.DOCUMENT_APPROVAL_REQUEST.value,
            PermissionRequestModel.request_status
            == PermissionRequestStatus.PENDING.value,
            ThreadModel.status == ThreadStatus.INPUT_REQUIRED.value,
        )
        .order_by(PermissionRequestModel.created_at.asc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


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
    permission.request_status = _coerce(
        PermissionRequestStatus, status, label="permission request status"
    ).value
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
        PermissionRequestModel.request_status.in_(_OUTSTANDING_PERMISSION_STATUSES),
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
        PermissionRequestModel.request_status.in_(_OUTSTANDING_PERMISSION_STATUSES),
    )
    permissions = (await session.execute(stmt)).scalars().all()
    for permission in permissions:
        permission.request_status = (
            PermissionRequestStatus.EXPIRED_BY_TERMINAL_STATE.value
        )
        permission.applied_at = permission.applied_at or utcnow()
    await session.flush()
    return len(permissions)


class _PermissionLogOptional(TypedDict, total=False):
    option_id: str | None


class _PermissionLogArgs(_PermissionLogOptional):
    thread_id: str
    agent_id: str | None
    tool_name: str
    action: str


async def append_permission_log(
    session: AsyncSession,
    **kwargs: Unpack[_PermissionLogArgs],
) -> PermissionLogModel:
    """Append one permission decision to the durable audit log.

    ``action`` is the verdict (approved or rejected) and ``option_id`` the
    concrete option that produced it. The two are recorded together because the
    verdict alone cannot distinguish which of several rejecting options a
    reviewer chose, and the option id alone is only interpretable against the
    request's option list, which this row does not carry.

    ``agent_id`` is keyword-required despite being nullable: a caller that has no
    attribution must say so, rather than inherit an absence it never considered.
    """
    log_entry = PermissionLogModel(
        id=uuid4().hex,
        thread_id=kwargs["thread_id"],
        agent_id=kwargs["agent_id"],
        tool_name=kwargs["tool_name"],
        action=kwargs["action"],
        option_id=kwargs.get("option_id"),
    )
    return await save_model(session, log_entry)


async def get_permission_logs_by_thread(
    session: AsyncSession, thread_id: str
) -> Sequence[PermissionLogModel]:
    stmt = (
        select(PermissionLogModel)
        .where(PermissionLogModel.thread_id == thread_id)
        .order_by(PermissionLogModel.responded_at)
    )
    return (await session.execute(stmt)).scalars().all()
