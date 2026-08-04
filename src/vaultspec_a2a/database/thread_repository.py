"""Thread repository — lifecycle, repair, approval, execution state, metadata."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import Select
    from sqlalchemy.sql.elements import ColumnElement

from ..thread.enums import (
    ACTIVE_STATUSES,
    NON_ACTIVE_STATUSES,
    ApprovalStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
)
from ..thread.errors import NicknameConflictError
from ..thread.transitions import validate_transition
from ._helpers import (
    _UNSET,
    _coerce_approval_status,
    _coerce_control_action_type,
    _coerce_repair_status,
    _coerce_status,
    _UnsetType,
    save_model,
)
from .models import ThreadExecutionStateModel, ThreadModel, _utcnow

__all__ = [
    "ActiveThreadProjection",
    "create_thread",
    "delete_thread",
    "get_thread",
    "get_thread_execution_state",
    "get_thread_metadata",
    "list_active_thread_page",
    "list_non_terminal_threads",
    "list_threads",
    "mark_thread_deleting",
    "normalize_workspace_identity",
    "record_thread_execution_state",
    "set_thread_approval_state",
    "set_thread_repair_state",
    "update_thread_status",
]


@dataclass(frozen=True, slots=True)
class ActiveThreadProjection:
    """Narrow durable fields needed by active-run discovery."""

    id: str
    status: str
    feature_tag: str | None
    created_at: datetime


_MAX_DISCOVERY_WORKSPACE_ROOT_LENGTH = 4096
_MAX_DISCOVERY_FEATURE_TAG_LENGTH = 128


def _path_safe_run_id_clause() -> ColumnElement[bool]:
    """Return the cross-dialect persisted run-id grammar predicate."""
    return ThreadModel.id.regexp_match(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$")


def normalize_workspace_identity(value: str | os.PathLike[str]) -> str:
    """Return an OS-canonical workspace identity without requiring existence.

    The single formula behind workspace-scoped run discovery. The write seam
    projects it into the durable selector and the read seam applies it to an
    incoming query; both then hash the result through ``_workspace_key``, so one
    shared definition is what guarantees the write-time and read-time hashes
    agree. Two hand-copied formulas would desynchronise silently on any edit -
    discovery would simply return nothing, with no error to notice.

    The ``0008`` migration carries its own frozen copy on purpose; see the note
    there. It is pinned to the formula as it ran and must not be routed here.
    """
    return os.path.normcase(os.path.realpath(os.fspath(value)))


def _discovery_selectors(metadata: str | None) -> tuple[str | None, str | None]:
    """Project bounded discovery selectors once at the metadata write seam."""
    if not metadata:
        return None, None
    try:
        value = json.loads(metadata)
    except (json.JSONDecodeError, RecursionError, TypeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    workspace = value.get("workspace_root")
    feature = value.get("feature_tag")
    if (
        not isinstance(workspace, str)
        or not os.path.isabs(workspace)
        or not 1 <= len(workspace) <= _MAX_DISCOVERY_WORKSPACE_ROOT_LENGTH
    ):
        workspace = None
    else:
        workspace = normalize_workspace_identity(workspace)
    if (
        not isinstance(feature, str)
        or not 1 <= len(feature) <= _MAX_DISCOVERY_FEATURE_TAG_LENGTH
    ):
        feature = None
    return workspace, feature


def _workspace_key(workspace_root: str | None) -> str | None:
    """Return an index-safe identity for an already-canonical workspace path."""
    if workspace_root is None:
        return None
    return hashlib.sha256(workspace_root.encode("utf-8")).hexdigest()


async def create_thread(
    session: AsyncSession,
    *,
    title: str | None = None,
    status: ThreadStatus | str = ThreadStatus.SUBMITTED,
    metadata: str | None = None,
    nickname: str | None = None,
    thread_id: str | None = None,
    team_preset: str | None = None,
    repair_status: RepairStatus | str = RepairStatus.HEALTHY,
    repair_reason: str | None = None,
    execution_readiness: RepairStatus | str = RepairStatus.HEALTHY,
) -> ThreadModel:
    """Create a new orchestration thread."""
    coerced_status = _coerce_status(status)
    coerced_repair_status = _coerce_repair_status(repair_status)

    if nickname is not None:
        existing = (
            await session.execute(
                select(ThreadModel).where(ThreadModel.nickname == nickname)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise NicknameConflictError(nickname)

    workspace_root, feature_tag = _discovery_selectors(metadata)
    thread = ThreadModel(
        id=thread_id or uuid4().hex,
        title=title,
        status=coerced_status.value,
        is_active=coerced_status in ACTIVE_STATUSES,
        repair_status=coerced_repair_status.value,
        repair_reason=repair_reason,
        execution_readiness=execution_readiness,
        thread_metadata=metadata,
        workspace_root=workspace_root,
        workspace_key=_workspace_key(workspace_root),
        feature_tag=feature_tag,
        nickname=nickname,
        team_preset=team_preset,
    )
    try:
        return await save_model(session, thread)
    except IntegrityError as exc:
        # With a caller-owned id, a simultaneous same-id insert can be reported
        # by SQLite as the generated nickname constraint instead of the primary
        # key. Let the gateway roll back and reconcile that durable id first;
        # it translates a genuine different-id nickname collision afterwards.
        if (
            nickname is not None
            and thread_id is None
            and "nickname" in str(exc).lower()
        ):
            raise NicknameConflictError(nickname) from exc
        raise


async def get_thread(session: AsyncSession, thread_id: str) -> ThreadModel | None:
    return await session.get(ThreadModel, thread_id)


async def list_threads(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 50,
    status: ThreadStatus | None = None,
    include_deleting: bool = False,
) -> tuple[Sequence[ThreadModel], int]:
    """List threads with pagination, hiding threads under deletion by default.

    A thread in the ``deleting`` teardown state is a cross-store cleanup subject,
    not a run: it is excluded from both the page and the total unless a caller
    opts in with ``include_deleting`` for a cleanup or administrative view. The
    filter runs in the query so the total and pagination stay consistent with
    the page.
    """
    filters = []
    if status is not None:
        filters.append(ThreadModel.status == status.value)
    if not include_deleting:
        filters.append(ThreadModel.status != ThreadStatus.DELETING.value)

    count_stmt = select(func.count()).select_from(ThreadModel)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = (
        select(ThreadModel)
        .order_by(ThreadModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if filters:
        stmt = stmt.where(*filters)
    result = await session.execute(stmt)
    return result.scalars().all(), total


async def list_non_terminal_threads(session: AsyncSession) -> Sequence[ThreadModel]:
    """Return all threads that still require orchestration attention.

    Excludes every member of ``NON_ACTIVE_STATUSES`` - the terminal outcomes
    plus ``ARCHIVED`` and ``DELETING`` - rather than a hand-typed subset. A
    thread mid-teardown is a lifecycle sink with no valid outbound transition
    (see ``thread.transitions``), so it must stay invisible to this sweep the
    same way it is invisible to discovery; scoring it for repair alongside a
    genuinely in-flight run risked a startup reconciliation pass raising
    ``InvalidTransitionError`` against a row the deletion saga owns.
    """
    stmt = (
        select(ThreadModel)
        .where(
            ThreadModel.status.not_in(
                sorted(status.value for status in NON_ACTIVE_STATUSES)
            )
        )
        .order_by(ThreadModel.created_at.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_active_thread_page(
    session: AsyncSession,
    *,
    limit: int,
    workspace_root: str | None = None,
    feature_tag: str | None = None,
    after_created_at: datetime | None = None,
    after_id: str | None = None,
) -> Sequence[ActiveThreadProjection]:
    """Return one narrow, keyset-paginated page of durable active threads."""
    if not 1 <= limit <= 101:
        msg = "active-thread page limit must be between 1 and 101"
        raise ValueError(msg)
    if workspace_root is not None and not 1 <= len(workspace_root) <= 4096:
        msg = "active-thread workspace selector must be between 1 and 4096 characters"
        raise ValueError(msg)
    if feature_tag is not None and not 1 <= len(feature_tag) <= 128:
        msg = "active-thread feature selector must be between 1 and 128 characters"
        raise ValueError(msg)
    if (after_created_at is None) != (after_id is None):
        msg = "active-thread keyset cursor requires both created_at and id"
        raise ValueError(msg)

    stmt = _active_thread_page_statement(
        limit=limit,
        workspace_root=workspace_root,
        feature_tag=feature_tag,
        after_created_at=after_created_at,
        after_id=after_id,
    )
    result = await session.execute(stmt)
    return [
        ActiveThreadProjection(
            id=row.id,
            status=row.status,
            feature_tag=row.feature_tag,
            created_at=row.created_at,
        )
        for row in result.all()
    ]


def _active_thread_page_statement(
    *,
    limit: int,
    workspace_root: str | None,
    feature_tag: str | None,
    after_created_at: datetime | None,
    after_id: str | None,
) -> Select[tuple[str, str, str | None, datetime]]:
    """Build the production discovery query for execution and plan inspection."""
    stmt = (
        select(
            ThreadModel.id,
            ThreadModel.status,
            ThreadModel.feature_tag,
            ThreadModel.created_at,
        )
        .where(
            ThreadModel.is_active.is_(True),
            ThreadModel.status.in_(sorted(status.value for status in ACTIVE_STATUSES)),
            # SQLAlchemy renders this portable operator as ``REGEXP`` on
            # SQLite (whose dialect installs a Python regexp function) and
            # ``~`` on PostgreSQL. Keep legacy invalid identifiers out of the
            # bounded page in the database, before LIMIT is applied.
            _path_safe_run_id_clause(),
        )
        .order_by(ThreadModel.created_at.desc(), ThreadModel.id.desc())
        .limit(limit)
    )
    if workspace_root is not None:
        stmt = stmt.where(ThreadModel.workspace_key == _workspace_key(workspace_root))
    if feature_tag is not None:
        stmt = stmt.where(ThreadModel.feature_tag == feature_tag)
    if after_created_at is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                ThreadModel.created_at < after_created_at,
                and_(
                    ThreadModel.created_at == after_created_at,
                    ThreadModel.id < after_id,
                ),
            )
        )
    return stmt


async def delete_thread(session: AsyncSession, thread_id: str) -> bool:
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return False
    await session.delete(thread)
    await session.flush()
    return True


async def mark_thread_deleting(
    session: AsyncSession,
    thread_id: str,
) -> ThreadModel | None:
    """Mark a thread as ``deleting`` for cross-store teardown.

    Deletion is not a lifecycle transition: it is an out-of-band teardown that
    begins from a settled (terminal or archived) thread and ends in row
    removal. Routing it through :func:`update_thread_status` would require
    adding ``deleting`` as a target of the terminal states and so break the
    invariant that a settled thread only ever advances to ``archived``. This
    setter therefore writes the sink state directly and clears ``is_active`` so
    discovery and product reads immediately stop surfacing the thread. The
    deletion saga is the sole caller and only after eligibility is confirmed.
    """
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    thread.status = ThreadStatus.DELETING.value
    thread.is_active = False
    thread.updated_at = _utcnow()
    await session.flush()
    return thread


# Bounds threads.failure_reason so a pathological exception message (or one
# wrapping a large response body) can never blow up the durable row or the
# RunStatusResponse it is served through. This is the last-line durable-write
# boundary: every producer (ingest's classified reasons, a compile-time
# refusal's exception text, the ingest-stall watchdog) should already be capped
# and single-line by the time it reaches here, but this makes that an enforced
# invariant of the column, not a convention callers must each remember.
#
# The bound is in BYTES, not characters, because the consumer that decides
# whether this reason is acceptable measures bytes. A character cap of the same
# number silently admits any non-ASCII reason near the limit - a provider
# message with a curly quote or a non-Latin script - which the consumer then
# rejects OUTRIGHT, so the run reports nothing at all rather than a shortened
# something. Capping where the reader caps is what keeps a long reason merely
# truncated instead of discarded.
_MAX_FAILURE_REASON_BYTES = 500

# Marks a reason as shortened rather than merely ending abruptly. Counted
# against the budget in its own encoded length, since appending it after
# measuring is how a cap comes to be exceeded by the mark that announces it.
_TRUNCATION_MARK = "…"


def _capped_single_line(text: str) -> str:
    """Collapse embedded newlines and cap *text* to the failure-reason bound.

    Truncation cuts on a CHARACTER boundary even though the budget is counted
    in bytes: slicing an encoded string mid-sequence yields bytes that are not
    valid UTF-8, and a column holding those is worse than one holding a slightly
    shorter reason. Decoding the truncated prefix leniently drops exactly the
    trailing partial character and nothing else, because the input it re-decodes
    was produced by encoding a Python string and so is well-formed everywhere
    before that cut.
    """
    collapsed = " ".join(text.split())
    encoded = collapsed.encode("utf-8")
    if len(encoded) <= _MAX_FAILURE_REASON_BYTES:
        return collapsed
    budget = _MAX_FAILURE_REASON_BYTES - len(_TRUNCATION_MARK.encode("utf-8"))
    return encoded[:budget].decode("utf-8", errors="ignore") + _TRUNCATION_MARK


async def update_thread_status(
    session: AsyncSession,
    thread_id: str,
    status: ThreadStatus | str,
    *,
    failure_reason: str | None = None,
    provider_condition: str | None = None,
) -> ThreadModel | None:
    """Update a thread's status with transition validation.

    ``failure_reason`` is additive and leaves the column UNCHANGED when
    falsy (``None`` or empty), so every existing caller — completed,
    cancelled, and every already-shipped failed-status write that doesn't
    pass it — is untouched; there is deliberately no explicit-clear path,
    since a thread's failure reason is write-once per terminal transition.
    Pass a non-empty value only on a FAILED transition that has a reason to
    durably record; the text is capped and flattened to a single line here,
    the one write boundary every producer passes through, regardless of
    whether the caller already capped it.

    ``provider_condition`` is the machine-readable counterpart and follows the
    same additive, falsy-leaves-unchanged rule. It is written INDEPENDENTLY of
    the reason rather than only alongside it: the two answer different questions
    (what happened versus what the reader should do), and a caller that knows one
    but not the other must be able to record what it knows. A caller that knows
    neither leaves both untouched, which is why a failure carrying no
    classification reads as NULL here rather than as a fabricated floor.
    """
    coerced_status = _coerce_status(status)
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    current = _coerce_status(thread.status)
    if current == coerced_status:
        # Idempotent writes also repair a stale denormalized selector (for
        # example after an interrupted migration or legacy direct write).
        thread.is_active = coerced_status in ACTIVE_STATUSES
        thread.updated_at = _utcnow()
        if failure_reason:
            thread.failure_reason = _capped_single_line(failure_reason)
        if provider_condition:
            thread.provider_condition = provider_condition
        await session.flush()
        return thread

    validate_transition(current, coerced_status, thread_id=thread_id)

    thread.status = coerced_status.value
    thread.is_active = coerced_status in ACTIVE_STATUSES
    thread.updated_at = _utcnow()
    if failure_reason:
        thread.failure_reason = _capped_single_line(failure_reason)
    if provider_condition:
        thread.provider_condition = provider_condition
    await session.flush()
    return thread


async def set_thread_repair_state(
    session: AsyncSession,
    thread_id: str,
    *,
    repair_status: RepairStatus | str,
    repair_reason: str | None = None,
    execution_readiness: RepairStatus | str | None = None,
    last_requested_action: ControlActionType | str | None = None,
    last_applied_action: ControlActionType | str | None = None,
    increment_generation: bool = False,
    increment_recovery_epoch: bool = False,
) -> ThreadModel | None:
    """Persist thread repair metadata used by restart reconciliation."""
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    thread.repair_status = _coerce_repair_status(repair_status).value
    thread.repair_reason = repair_reason
    if execution_readiness is not None:
        thread.execution_readiness = execution_readiness
    if last_requested_action is not None:
        thread.last_requested_action = _coerce_control_action_type(
            last_requested_action
        ).value
    if last_applied_action is not None:
        thread.last_applied_action = _coerce_control_action_type(
            last_applied_action
        ).value
    if increment_generation:
        thread.repair_generation += 1
    if increment_recovery_epoch:
        thread.recovery_epoch += 1
    thread.updated_at = _utcnow()
    await session.flush()
    return thread


async def set_thread_approval_state(
    session: AsyncSession,
    thread_id: str,
    *,
    approval_status: ApprovalStatus | str | _UnsetType | None = _UNSET,
    approval_request_id: str | _UnsetType | None = _UNSET,
    approval_reason: str | _UnsetType | None = _UNSET,
    approval_response_action_id: str | _UnsetType | None = _UNSET,
    approval_updated_at: datetime | None = None,
) -> ThreadModel | None:
    """Persist durable plan-approval state on the thread row."""
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    if not isinstance(approval_status, _UnsetType):
        thread.approval_status = (
            _coerce_approval_status(approval_status).value
            if approval_status is not None
            else None
        )
    if not isinstance(approval_request_id, _UnsetType):
        thread.approval_request_id = approval_request_id
    if not isinstance(approval_reason, _UnsetType):
        thread.approval_reason = approval_reason
    if not isinstance(approval_response_action_id, _UnsetType):
        thread.approval_response_action_id = approval_response_action_id
    thread.approval_updated_at = approval_updated_at or _utcnow()
    await session.flush()
    return thread


async def record_thread_execution_state(
    session: AsyncSession,
    *,
    thread_id: str,
    checkpoint_id: str | None,
    parent_checkpoint_id: str | None,
    snapshot_created_at: datetime | None,
    task_count: int,
    interrupt_count: int,
    next_nodes: list[str],
    interrupt_types: list[str],
    tasks: list[dict[str, object]],
    degraded_reasons: list[str],
) -> ThreadExecutionStateModel | None:
    """Create or refresh the latest execution-state projection for a thread."""
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    existing = await session.get(ThreadExecutionStateModel, thread_id)
    degraded_only = (
        checkpoint_id is None
        and parent_checkpoint_id is None
        and snapshot_created_at is None
        and task_count == 0
        and interrupt_count == 0
        and not next_nodes
        and not interrupt_types
        and not tasks
        and bool(degraded_reasons)
    )
    next_nodes_json = json.dumps(next_nodes)
    interrupt_types_json = json.dumps(interrupt_types)
    tasks_json = json.dumps(tasks)
    degraded_reasons_json = json.dumps(degraded_reasons)

    if existing is not None:
        if not degraded_only:
            existing.checkpoint_id = checkpoint_id
            existing.parent_checkpoint_id = parent_checkpoint_id
            existing.snapshot_created_at = snapshot_created_at
            existing.task_count = task_count
            existing.interrupt_count = interrupt_count
            existing.next_nodes_json = next_nodes_json
            existing.interrupt_types_json = interrupt_types_json
            existing.tasks_json = tasks_json
            existing.recovery_epoch = thread.recovery_epoch
        existing.recorded_at = _utcnow()
        existing.degraded_reasons_json = degraded_reasons_json
        await session.flush()
        return existing

    model = ThreadExecutionStateModel(
        thread_id=thread_id,
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=parent_checkpoint_id,
        snapshot_created_at=snapshot_created_at,
        recorded_at=_utcnow(),
        recovery_epoch=thread.recovery_epoch,
        task_count=task_count,
        interrupt_count=interrupt_count,
        next_nodes_json=next_nodes_json,
        interrupt_types_json=interrupt_types_json,
        tasks_json=tasks_json,
        degraded_reasons_json=degraded_reasons_json,
    )
    return await save_model(session, model)


async def get_thread_execution_state(
    session: AsyncSession,
    thread_id: str,
) -> ThreadExecutionStateModel | None:
    """Return the latest execution-state projection for a thread."""
    return await session.get(ThreadExecutionStateModel, thread_id)


async def get_thread_metadata(session: AsyncSession, thread_id: str) -> str | None:
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    return thread.thread_metadata
