"""Worker task-queue repository — database-backed queue entries (ADR R5).

Replaces the bespoke ``.vault/plan`` markdown table with rows owned by a
thread.  ``position`` is the sole ordering authority; ``task_key`` is the
stable per-thread identity the mark-complete tool addresses.

These functions are pure persistence: they return models and primitives and
never import the graph layer.  The ``TaskQueuePort`` adapter that bridges them
into graph nodes lives in the worker composition layer.

Interim population is internal-only: ``seed_task_queue`` is used by tests and
future gateway/planner internals.  No agent-reachable population path exists,
preserving the R2 vault-write closure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple
from uuid import uuid4

from sqlalchemy import select

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

from ..thread.enums import TaskQueueStatus
from ._helpers import save_model
from .models import TaskQueueEntryModel

__all__ = [
    "MarkCompleteResult",
    "get_queue_view",
    "mark_task_complete",
    "seed_task_queue",
]


class MarkCompleteResult(NamedTuple):
    """Outcome of a mark-complete transition (persistence-layer primitive).

    ``found`` is False when no row for the thread matches ``task_key``.
    ``did_complete`` is True when the row is now completed — either it
    transitioned from ``in_progress`` or was already ``completed`` (idempotent
    replay).  ``next_task_key`` is the next pending row by ``position``.
    """

    found: bool
    did_complete: bool
    next_task_key: str | None


def _validate_feature_tag(feature_tag: str) -> str:
    """Reject traversal-shaped feature tags (merged traversal guard parity)."""
    if (
        not feature_tag
        or "/" in feature_tag
        or "\\" in feature_tag
        or ".." in feature_tag
    ):
        raise ValueError(f"Invalid feature_tag: {feature_tag!r}")
    return feature_tag


def _optional_str(value: object) -> str | None:
    """Coerce an optional reference value to ``str | None``."""
    if value is None:
        return None
    return str(value)


async def seed_task_queue(
    session: AsyncSession,
    *,
    thread_id: str,
    feature_tag: str,
    entries: Sequence[Mapping[str, object]],
) -> list[TaskQueueEntryModel]:
    """Insert task-queue rows for a thread (internal population path).

    Each mapping supplies ``task_key`` and ``description``; ``status``,
    ``position``, ``plan_changeset_id`` and ``plan_step_key`` are optional.
    When ``position`` is omitted, rows are ordered by their sequence in
    ``entries``.

    Args:
        session:      Active async session.
        thread_id:    Owning thread id.
        feature_tag:  Validated feature tag stored on every row.
        entries:      Ordered task specifications.

    Returns:
        The persisted models in insertion order.
    """
    _validate_feature_tag(feature_tag)
    created: list[TaskQueueEntryModel] = []
    for index, entry in enumerate(entries):
        task_key = entry.get("task_key")
        description = entry.get("description")
        if not isinstance(task_key, str) or not task_key:
            raise ValueError(f"Queue entry {index} requires a non-empty task_key")
        if not isinstance(description, str):
            raise ValueError(f"Queue entry {task_key!r} requires a description")
        raw_position = entry.get("position", index)
        position = int(raw_position) if isinstance(raw_position, int) else index
        model = TaskQueueEntryModel(
            id=uuid4().hex,
            thread_id=thread_id,
            feature_tag=feature_tag,
            position=position,
            task_key=task_key,
            description=description,
            status=str(entry.get("status", TaskQueueStatus.PENDING)),
            plan_changeset_id=_optional_str(entry.get("plan_changeset_id")),
            plan_step_key=_optional_str(entry.get("plan_step_key")),
        )
        created.append(await save_model(session, model))
    return created


async def _entries_by_position(
    session: AsyncSession, thread_id: str
) -> list[TaskQueueEntryModel]:
    """Return every queue row for a thread ordered by ``position`` ascending."""
    stmt = (
        select(TaskQueueEntryModel)
        .where(TaskQueueEntryModel.thread_id == thread_id)
        .order_by(TaskQueueEntryModel.position)
    )
    return list((await session.execute(stmt)).scalars().all())


def _first_pending_key(
    entries: Sequence[TaskQueueEntryModel],
    *,
    exclude_task_key: str | None = None,
) -> str | None:
    """Return the ``task_key`` of the first pending row by position."""
    for entry in entries:
        if entry.task_key == exclude_task_key:
            continue
        if entry.status == TaskQueueStatus.PENDING:
            return entry.task_key
    return None


async def get_queue_view(
    session: AsyncSession,
    thread_id: str,
    current_task_id: str | None,
    horizon: int,
) -> list[TaskQueueEntryModel]:
    """Return the current row plus up to ``horizon`` next pending rows.

    Mirrors the markdown filter exactly: the current row (matched by
    ``current_task_id``, any status) comes first when present, followed by up
    to ``horizon`` pending rows by ``position``, excluding the current row.
    """
    entries = await _entries_by_position(session, thread_id)

    selected: list[TaskQueueEntryModel] = []
    if current_task_id:
        current_entry = next(
            (e for e in entries if e.task_key == current_task_id), None
        )
        if current_entry is not None:
            selected.append(current_entry)

    pending_count = 0
    for entry in entries:
        if pending_count >= horizon:
            break
        if entry.task_key == current_task_id:
            continue
        if entry.status == TaskQueueStatus.PENDING:
            selected.append(entry)
            pending_count += 1

    return selected


async def mark_task_complete(
    session: AsyncSession,
    thread_id: str,
    task_key: str,
) -> MarkCompleteResult:
    """Idempotently complete ``task_key`` and report the next pending row.

    A row in ``in_progress`` transitions to ``completed``.  A row already
    ``completed`` is a no-op (idempotent replay).  A ``pending`` or ``failed``
    row, or a missing row, is reported as not completable.
    """
    entries = await _entries_by_position(session, thread_id)
    target = next((e for e in entries if e.task_key == task_key), None)

    if target is None:
        return MarkCompleteResult(found=False, did_complete=False, next_task_key=None)

    if target.status == TaskQueueStatus.IN_PROGRESS:
        target.status = TaskQueueStatus.COMPLETED
        await session.flush()
        return MarkCompleteResult(
            found=True,
            did_complete=True,
            next_task_key=_first_pending_key(entries, exclude_task_key=task_key),
        )

    if target.status == TaskQueueStatus.COMPLETED:
        # Idempotent replay: no state change, same reported next row.
        return MarkCompleteResult(
            found=True,
            did_complete=True,
            next_task_key=_first_pending_key(entries, exclude_task_key=task_key),
        )

    return MarkCompleteResult(found=True, did_complete=False, next_task_key=None)
