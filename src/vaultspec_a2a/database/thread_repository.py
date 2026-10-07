"""Thread repository — lifecycle, repair, approval, execution state, metadata."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, TypedDict, Unpack, cast
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import QueryableAttribute
    from sqlalchemy.sql import Select
    from sqlalchemy.sql.elements import ColumnElement

from ..thread import RunWriteAuthority, ThreadWriteExpectation
from ..thread.constants import (
    MAX_FEATURE_TAG_LENGTH,
    MAX_WORKSPACE_ROOT_LENGTH,
    RUN_ID_PATTERN,
)
from ..thread.enums import (
    ACTIVE_STATUSES,
    NON_ACTIVE_STATUSES,
    ApprovalStatus,
    ControlActionType,
    RepairStatus,
    ThreadStatus,
)
from ..thread.errors import NicknameConflictError
from ..thread.lifecycle_guards import can_delete
from ..thread.transitions import validate_transition
from ._helpers import (
    _UNSET,
    _coerce,
    _journal_row_for,
    _UnsetType,
    save_model,
)
from .models import (
    ControlActionModel,
    ThreadExecutionStateModel,
    ThreadModel,
)
from .models import (
    utcnow as _utcnow,
)
from .write_authority_schema import WRITE_AUTHORITY_VIOLATION_PREDICATE

__all__ = [
    "ActiveThreadProjection",
    "ThreadStatusElectionOutcome",
    "ThreadStatusElectionResult",
    "create_thread",
    "delete_thread",
    "elect_thread_deleting",
    "elect_thread_status",
    "get_thread",
    "get_thread_execution_state",
    "get_thread_metadata",
    "list_active_thread_page",
    "list_non_terminal_threads",
    "list_threads",
    "normalize_workspace_identity",
    "path_safe_run_id_clause",
    "record_thread_execution_state",
    "select_invalid_authority_thread",
    "select_orphaned_writer_thread",
    "set_thread_approval_state",
    "set_thread_repair_state",
    "thread_owned_by",
    "thread_write_expectation",
    "update_thread_status",
]


@dataclass(frozen=True, slots=True)
class ActiveThreadProjection:
    """Narrow durable fields needed by active-run discovery."""

    id: str
    status: str
    feature_tag: str | None
    created_at: datetime


class ThreadStatusElectionOutcome(StrEnum):
    """Durable disposition of one conditional lifecycle write."""

    WON = "won"
    LOST = "lost"
    NOT_FOUND = "not_found"
    RECEIPT_MISMATCH = "receipt_mismatch"


@dataclass(frozen=True, slots=True)
class ThreadStatusElectionResult:
    """Immutable result of a lifecycle ownership election."""

    outcome: ThreadStatusElectionOutcome


def thread_write_expectation(thread: ThreadModel) -> ThreadWriteExpectation:
    """Snapshot the complete current election witness from a durable row."""
    return ThreadWriteExpectation(
        status=_coerce(ThreadStatus, thread.status, label="thread status"),
        authority=RunWriteAuthority(
            run_revision=thread.run_revision,
            writer_generation=thread.writer_generation,
            action_type=_coerce(
                ControlActionType,
                thread.writer_action_type,
                label="control action type",
            ),
            action_receipt_id=thread.writer_action_receipt_id,
        ),
    )


def thread_owned_by(
    action_type: ControlActionType | QueryableAttribute[str],
    action_receipt_id: str | QueryableAttribute[str | None],
    *,
    writer_generation: int | None = None,
    run_revision: int | None = None,
) -> ColumnElement[bool]:
    """Return the SQL form of ``RunWriteAuthority.owned_by`` over ``threads``.

    The action identity is either bound values or a joined row's columns, so
    one predicate serves both an exact observed witness and a scan for runs
    whose current writer is the joined action. Generation and revision are
    pinned only when given.
    """
    writer_type = (
        action_type.value if isinstance(action_type, ControlActionType) else action_type
    )
    clauses = [
        ThreadModel.writer_action_type == writer_type,
        ThreadModel.writer_action_receipt_id == action_receipt_id,
    ]
    if writer_generation is not None:
        clauses.append(ThreadModel.writer_generation == writer_generation)
    if run_revision is not None:
        clauses.append(ThreadModel.run_revision == run_revision)
    return and_(*clauses)


def select_invalid_authority_thread() -> Select[tuple[str]]:
    """Select one thread whose stored write authority breaks a current CHECK."""
    return (
        select(ThreadModel.id).where(text(WRITE_AUTHORITY_VIOLATION_PREDICATE)).limit(1)
    )


def select_orphaned_writer_thread() -> Select[tuple[str]]:
    """Select one thread whose current writer names no journal row of its own."""
    return (
        select(ThreadModel.id)
        .outerjoin(
            ControlActionModel,
            and_(
                ControlActionModel.thread_id == ThreadModel.id,
                thread_owned_by(
                    ControlActionModel.action_type, ControlActionModel.dispatch_id
                ),
            ),
        )
        .where(ControlActionModel.id.is_(None))
        .limit(1)
    )


def path_safe_run_id_clause() -> ColumnElement[bool]:
    """Return the persisted run-id grammar predicate.

    The one canonical predicate for "is this durable id the shape the gateway's
    ``PathSafeRunId`` type admits" - public so a query outside this module can
    apply it rather than re-deriving the regex.
    """
    return ThreadModel.id.regexp_match(RUN_ID_PATTERN)


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
    value_obj = cast("dict[str, object]", value)
    workspace = value_obj.get("workspace_root")
    feature = value_obj.get("feature_tag")
    if (
        not isinstance(workspace, str)
        or not os.path.isabs(workspace)
        or not 1 <= len(workspace) <= MAX_WORKSPACE_ROOT_LENGTH
    ):
        workspace = None
    else:
        workspace = normalize_workspace_identity(workspace)
    if not isinstance(feature, str) or not 1 <= len(feature) <= MAX_FEATURE_TAG_LENGTH:
        feature = None
    return workspace, feature


def _workspace_key(workspace_root: str | None) -> str | None:
    """Return an index-safe identity for an already-canonical workspace path."""
    if workspace_root is None:
        return None
    return hashlib.sha256(workspace_root.encode("utf-8")).hexdigest()


class _CreateThreadOptional(TypedDict, total=False):
    title: str | None
    status: ThreadStatus | str
    metadata: str | None
    nickname: str | None
    thread_id: str | None
    team_preset: str | None
    repair_status: RepairStatus | str
    repair_reason: str | None


class _CreateThreadArgs(_CreateThreadOptional):
    write_authority: RunWriteAuthority


async def create_thread(
    session: AsyncSession, **options: Unpack[_CreateThreadArgs]
) -> ThreadModel:
    """Create a new orchestration thread."""
    write_authority = options["write_authority"]
    metadata = options.get("metadata")
    nickname = options.get("nickname")
    thread_id = options.get("thread_id")
    coerced_status = _coerce(
        ThreadStatus,
        options.get("status", ThreadStatus.SUBMITTED),
        label="thread status",
    )
    coerced_repair_status = _coerce(
        RepairStatus,
        options.get("repair_status", RepairStatus.HEALTHY),
        label="repair status",
    )

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
        run_revision=write_authority.run_revision,
        writer_generation=write_authority.writer_generation,
        writer_action_type=write_authority.action_type.value,
        writer_action_receipt_id=write_authority.action_receipt_id,
        title=options.get("title"),
        status=coerced_status.value,
        is_active=coerced_status in ACTIVE_STATUSES,
        repair_status=coerced_repair_status.value,
        repair_reason=options.get("repair_reason"),
        execution_readiness=coerced_repair_status.value,
        thread_metadata=metadata,
        workspace_root=workspace_root,
        workspace_key=_workspace_key(workspace_root),
        feature_tag=feature_tag,
        nickname=nickname,
        team_preset=options.get("team_preset"),
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

    Also excludes legacy invalid identifiers, the same predicate
    ``list_active_thread_page`` already applies before its ``LIMIT``: this is the
    ``state=all`` history reading behind ``RunSummaryRecord``, which the gateway
    schema types as ``PathSafeRunId``. Unlike discovery's capped page, this
    listing has no size ceiling protecting it - one non-conforming row reaching
    response serialization fails the whole page for every caller, not just the
    one row - so the exclusion is unconditional rather than opt-in.
    """
    filters = [path_safe_run_id_clause()]
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


class _ActivePageOptional(TypedDict, total=False):
    workspace_root: str | None
    feature_tag: str | None
    after_created_at: datetime | None
    after_id: str | None


class _ActivePageArgs(_ActivePageOptional):
    limit: int


async def list_active_thread_page(
    session: AsyncSession, **kwargs: Unpack[_ActivePageArgs]
) -> Sequence[ActiveThreadProjection]:
    """Return one narrow, keyset-paginated page of durable active threads."""
    limit = kwargs["limit"]
    workspace_root = kwargs.get("workspace_root")
    feature_tag = kwargs.get("feature_tag")
    after_created_at = kwargs.get("after_created_at")
    after_id = kwargs.get("after_id")
    if not 1 <= limit <= 101:
        msg = "active-thread page limit must be between 1 and 101"
        raise ValueError(msg)
    if (
        workspace_root is not None
        and not 1 <= len(workspace_root) <= MAX_WORKSPACE_ROOT_LENGTH
    ):
        msg = (
            "active-thread workspace selector must be between 1 and "
            f"{MAX_WORKSPACE_ROOT_LENGTH} characters"
        )
        raise ValueError(msg)
    if feature_tag is not None and not 1 <= len(feature_tag) <= MAX_FEATURE_TAG_LENGTH:
        msg = (
            "active-thread feature selector must be between 1 and "
            f"{MAX_FEATURE_TAG_LENGTH} characters"
        )
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
            # SQLAlchemy renders this operator as ``REGEXP``, which the SQLite
            # dialect backs with a Python regexp function. Keep legacy invalid
            # identifiers out of the bounded page in the database, before LIMIT
            # is applied.
            path_safe_run_id_clause(),
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


def _validate_expectation(expectation: ThreadWriteExpectation) -> None:
    if not isinstance(cast("object", expectation), ThreadWriteExpectation):
        raise TypeError("expectation must be a ThreadWriteExpectation")


class _ElectionOptional(TypedDict, total=False):
    failure_reason: str | None
    provider_condition: str | None


class _ElectionArgs(_ElectionOptional):
    expectation: ThreadWriteExpectation
    status: ThreadStatus
    action_type: ControlActionType
    action_receipt_id: str


async def elect_thread_status(
    session: AsyncSession, thread_id: str, **kwargs: Unpack[_ElectionArgs]
) -> ThreadStatusElectionResult:
    """Atomically elect one lifecycle writer from an exact durable witness.

    The update predicate contains the observed state and every authority field.
    Database lock rechecks therefore choose one winner even when two sessions
    carry the same stale snapshot. The elected action's successor authority is
    derived from the witness here, and its receipt must already identify a
    same-thread, same-action journal row; absence is a typed refusal and never
    causes authority to be invented.
    """
    expectation = kwargs["expectation"]
    status = kwargs["status"]
    failure_reason = kwargs.get("failure_reason")
    provider_condition = kwargs.get("provider_condition")
    _validate_expectation(expectation)
    successor = expectation.authority.successor(
        action_type=kwargs["action_type"],
        action_receipt_id=kwargs["action_receipt_id"],
    )
    if not isinstance(cast("object", status), ThreadStatus):
        raise TypeError("status must be a ThreadStatus")
    validate_transition(expectation.status, status, thread_id=thread_id)
    if status is expectation.status and expectation.authority.owned_by(
        successor.action_type, successor.action_receipt_id
    ):
        raise ValueError(
            "an election must advance state or install a new action identity"
        )

    values: dict[str, object] = {
        "status": status.value,
        "is_active": status in ACTIVE_STATUSES,
        "updated_at": _utcnow(),
    }
    if failure_reason:
        values["failure_reason"] = _capped_single_line(failure_reason)
    if provider_condition:
        values["provider_condition"] = provider_condition
    return await _compare_and_set_thread(
        session,
        thread_id,
        expectation=expectation,
        successor=successor,
        values=values,
    )


async def elect_thread_deleting(
    session: AsyncSession,
    thread_id: str,
    *,
    expectation: ThreadWriteExpectation,
) -> ThreadStatusElectionResult:
    """Atomically enter the out-of-band deletion sink from an exact witness.

    Deletion retains the current action identity because it has no control-action
    receipt of its own.  This narrow operation cannot target any other state and
    ordinary lifecycle elections still cannot enter or leave ``DELETING``.
    """
    _validate_expectation(expectation)
    eligibility = can_delete(expectation.status.value)
    if not eligibility.allowed:
        raise ValueError(eligibility.reason)
    current = expectation.authority
    return await _compare_and_set_thread(
        session,
        thread_id,
        expectation=expectation,
        successor=current.successor(
            action_type=current.action_type,
            action_receipt_id=current.action_receipt_id,
        ),
        values={
            "status": ThreadStatus.DELETING.value,
            "is_active": False,
            "updated_at": _utcnow(),
        },
    )


async def _compare_and_set_thread(
    session: AsyncSession,
    thread_id: str,
    *,
    expectation: ThreadWriteExpectation,
    successor: RunWriteAuthority,
    values: dict[str, object],
) -> ThreadStatusElectionResult:
    """Install *successor* with *values* only while *expectation* still holds.

    The successor's receipt must name a journal row of this thread and action;
    a write that misses resolves to the typed reason it missed.
    """
    current = expectation.authority
    receipt_exists = exists(
        select(ControlActionModel.id).where(_journal_row_for(thread_id, successor))
    )
    statement = (
        update(ThreadModel)
        .where(
            ThreadModel.id == thread_id,
            ThreadModel.status == expectation.status.value,
            thread_owned_by(
                current.action_type,
                current.action_receipt_id,
                writer_generation=current.writer_generation,
                run_revision=current.run_revision,
            ),
            receipt_exists,
        )
        .values(
            **values,
            run_revision=successor.run_revision,
            writer_generation=successor.writer_generation,
            writer_action_type=successor.action_type.value,
            writer_action_receipt_id=successor.action_receipt_id,
        )
        .execution_options(synchronize_session=False)
    )
    result = cast("CursorResult[object]", await session.execute(statement))
    if result.rowcount == 1:
        # Callers apply repair, approval and journal side effects in this same
        # transaction. Refresh an already identity-mapped row before returning
        # so those steps observe the elected status and authority rather than
        # the witness that just lost ownership.
        await session.scalar(
            select(ThreadModel)
            .where(ThreadModel.id == thread_id)
            .execution_options(populate_existing=True)
        )
        return ThreadStatusElectionResult(ThreadStatusElectionOutcome.WON)

    row_exists = await session.scalar(
        select(ThreadModel.id).where(ThreadModel.id == thread_id)
    )
    if row_exists is None:
        return ThreadStatusElectionResult(ThreadStatusElectionOutcome.NOT_FOUND)

    matching_receipt = await session.scalar(select(receipt_exists))
    if not matching_receipt:
        return ThreadStatusElectionResult(ThreadStatusElectionOutcome.RECEIPT_MISMATCH)
    return ThreadStatusElectionResult(ThreadStatusElectionOutcome.LOST)


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
    coerced_status = _coerce(ThreadStatus, status, label="thread status")
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    current = _coerce(ThreadStatus, thread.status, label="thread status")
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


class _RepairOptional(TypedDict, total=False):
    repair_reason: str | None
    last_requested_action: ControlActionType | str | None
    last_applied_action: ControlActionType | str | None


class _RepairArgs(_RepairOptional):
    repair_status: RepairStatus | str


async def set_thread_repair_state(
    session: AsyncSession, thread_id: str, **kwargs: Unpack[_RepairArgs]
) -> ThreadModel | None:
    """Persist thread repair metadata used by restart reconciliation.

    The readiness column is written from the repair status every time: a run is
    as fit to resume as its repair posture says, so the column carries no
    judgement of its own and only keeps step with the posture it mirrors.
    """
    repair_status = kwargs["repair_status"]
    repair_reason = kwargs.get("repair_reason")
    last_requested_action = kwargs.get("last_requested_action")
    last_applied_action = kwargs.get("last_applied_action")
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None

    thread.repair_status = _coerce(
        RepairStatus, repair_status, label="repair status"
    ).value
    thread.execution_readiness = thread.repair_status
    thread.repair_reason = repair_reason
    if last_requested_action is not None:
        thread.last_requested_action = _coerce(
            ControlActionType, last_requested_action, label="control action type"
        ).value
    if last_applied_action is not None:
        thread.last_applied_action = _coerce(
            ControlActionType, last_applied_action, label="control action type"
        ).value
    thread.updated_at = _utcnow()
    await session.flush()
    return thread


class _ApprovalStateOptions(TypedDict, total=False):
    approval_status: ApprovalStatus | str | _UnsetType | None
    approval_request_id: str | _UnsetType | None
    approval_reason: str | _UnsetType | None
    approval_response_action_id: str | _UnsetType | None
    approval_updated_at: datetime | None


async def set_thread_approval_state(
    session: AsyncSession, thread_id: str, **kwargs: Unpack[_ApprovalStateOptions]
) -> ThreadModel | None:
    """Persist durable plan-approval state on the thread row."""
    approval_status = kwargs.get("approval_status", _UNSET)
    approval_request_id = kwargs.get("approval_request_id", _UNSET)
    approval_reason = kwargs.get("approval_reason", _UNSET)
    approval_response_action_id = kwargs.get("approval_response_action_id", _UNSET)
    approval_updated_at = kwargs.get("approval_updated_at")
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    if not isinstance(approval_status, _UnsetType):
        thread.approval_status = (
            _coerce(ApprovalStatus, approval_status, label="approval status").value
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


def _is_degraded_only_execution_state(
    checkpoint_fields: tuple[str | None, str | None, datetime | None],
    activity_fields: tuple[int, int, list[str], list[str], list[dict[str, object]]],
    degraded_reasons: list[str],
) -> bool:
    checkpoint_id, parent_checkpoint_id, snapshot_created_at = checkpoint_fields
    task_count, interrupt_count, next_nodes, interrupt_types, tasks = activity_fields
    return (
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


class _ExecutionStateArgs(TypedDict):
    thread_id: str
    checkpoint_id: str | None
    parent_checkpoint_id: str | None
    snapshot_created_at: datetime | None
    task_count: int
    interrupt_count: int
    next_nodes: list[str]
    interrupt_types: list[str]
    tasks: list[dict[str, object]]
    degraded_reasons: list[str]


async def record_thread_execution_state(
    session: AsyncSession, **kwargs: Unpack[_ExecutionStateArgs]
) -> ThreadExecutionStateModel | None:
    """Create or refresh the latest execution-state projection for a thread."""
    thread = await session.get(ThreadModel, kwargs["thread_id"])
    if thread is None:
        return None

    existing = await session.get(ThreadExecutionStateModel, kwargs["thread_id"])
    degraded_only = _is_degraded_only_execution_state(
        (
            kwargs["checkpoint_id"],
            kwargs["parent_checkpoint_id"],
            kwargs["snapshot_created_at"],
        ),
        (
            kwargs["task_count"],
            kwargs["interrupt_count"],
            kwargs["next_nodes"],
            kwargs["interrupt_types"],
            kwargs["tasks"],
        ),
        kwargs["degraded_reasons"],
    )
    next_nodes_json = json.dumps(kwargs["next_nodes"])
    interrupt_types_json = json.dumps(kwargs["interrupt_types"])
    tasks_json = json.dumps(kwargs["tasks"])
    degraded_reasons_json = json.dumps(kwargs["degraded_reasons"])

    if existing is not None:
        if not degraded_only:
            existing.checkpoint_id = kwargs["checkpoint_id"]
            existing.parent_checkpoint_id = kwargs["parent_checkpoint_id"]
            existing.snapshot_created_at = kwargs["snapshot_created_at"]
            existing.task_count = kwargs["task_count"]
            existing.interrupt_count = kwargs["interrupt_count"]
            existing.next_nodes_json = next_nodes_json
            existing.interrupt_types_json = interrupt_types_json
            existing.tasks_json = tasks_json
        existing.recorded_at = _utcnow()
        existing.degraded_reasons_json = degraded_reasons_json
        await session.flush()
        return existing

    model = ThreadExecutionStateModel(
        thread_id=kwargs["thread_id"],
        checkpoint_id=kwargs["checkpoint_id"],
        parent_checkpoint_id=kwargs["parent_checkpoint_id"],
        snapshot_created_at=kwargs["snapshot_created_at"],
        recorded_at=_utcnow(),
        task_count=kwargs["task_count"],
        interrupt_count=kwargs["interrupt_count"],
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
