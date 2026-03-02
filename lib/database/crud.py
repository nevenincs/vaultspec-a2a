"""Async CRUD operations for the database layer.

Provides typed create/read/update functions for all models.
All functions accept an ``AsyncSession`` for composability with
FastAPI's dependency injection.

For create operations, callers construct model instances directly and
pass them to the ``save_*`` functions. Convenience ``create_*`` functions
are provided for common cases with fewer parameters.

References:
    - ADR-007: SQLite persistence
    - ADR-009: Module hierarchy
    - ADR-011: Wire contract data models
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# M19/DB-M1: database → core is the normal dependency direction (not circular).
# NicknameConflictError is a domain exception that belongs in core; database
# raises it when detecting UNIQUE constraint violations on nickname.
# NOTE (DB-M1): This cross-module import (lib/database → lib/core) is intentional
# and follows the layered dependency direction prescribed by ADR-009. Moving this
# exception into lib/database would create an orphan with no semantic home.
from ..core.exceptions import NicknameConflictError
from .models import ArtifactModel, CostTrackingModel, PermissionLogModel, ThreadModel


class ThreadStatus(StrEnum):
    """M25: constrained thread status values to prevent invalid status strings."""

    SUBMITTED = "submitted"
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


__all__ = [
    "ThreadStatus",
    "append_cost_record",
    "append_permission_log",
    "create_artifact",
    "create_thread",
    "get_artifact",
    "get_artifacts_by_thread",
    "get_permission_logs_by_thread",
    "get_thread",
    "get_thread_metadata",
    "list_threads",
    "save_model",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
    "update_thread_metadata",
    "update_thread_status",
]


async def save_model[
    M: (ThreadModel, ArtifactModel, PermissionLogModel, CostTrackingModel)
](session: AsyncSession, model: M) -> M:
    """Persist any database model instance.

    Args:
        session: Active async session.
        model: The model instance to persist.

    Returns:
        The persisted model instance (same object, flushed).
    """
    session.add(model)
    await session.flush()
    return model


# ---------------------------------------------------------------------------
# Thread CRUD
# ---------------------------------------------------------------------------


def _coerce_status(status: "ThreadStatus | str") -> ThreadStatus:
    """Coerce a raw string to ``ThreadStatus``, raising ``ValueError`` if invalid."""
    if isinstance(status, ThreadStatus):
        return status
    try:
        return ThreadStatus(status)
    except ValueError:
        valid = ", ".join(s.value for s in ThreadStatus)
        msg = f"Invalid thread status: {status!r}. Must be one of: {valid}"
        raise ValueError(msg) from None


async def create_thread(
    session: AsyncSession,
    *,
    title: str | None = None,
    status: "ThreadStatus | str" = ThreadStatus.SUBMITTED,
    metadata: str | None = None,
    nickname: str | None = None,
    thread_id: str | None = None,
    team_preset: str | None = None,
) -> ThreadModel:
    """Create a new orchestration thread.

    Args:
        session: Active async session.
        title: Optional human-readable thread title.
        status: Initial status (default ``ThreadStatus.SUBMITTED``). Raw strings
            are accepted for backward compatibility but must be a valid
            ``ThreadStatus`` value — ``ValueError`` is raised otherwise
            (DB-HIGH-02).
        metadata: JSON-serialised ThreadMetadata (ADR-014).
        nickname: Optional human-friendly nickname (unique).
        thread_id: Optional explicit ID; auto-generated if omitted.

    Returns:
        The persisted ``ThreadModel`` instance.

    Raises:
        NicknameConflictError: If a thread with the given nickname already exists.
        ValueError: If *status* is not a valid ``ThreadStatus`` value.
    """
    coerced_status = _coerce_status(status)
    if nickname is not None:
        existing = (
            await session.execute(
                select(ThreadModel).where(ThreadModel.nickname == nickname)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise NicknameConflictError(nickname)

    thread = ThreadModel(
        id=thread_id or uuid4().hex,
        title=title,
        status=coerced_status,
        thread_metadata=metadata,
        nickname=nickname,
        team_preset=team_preset,
    )
    try:
        return await save_model(session, thread)
    except IntegrityError as exc:
        # Safety net for H12/H17 TOCTOU race: two concurrent requests may both
        # pass the SELECT pre-check above and then race on the INSERT.
        # The unique index on ThreadModel.nickname fires an IntegrityError
        # on the loser — convert it to NicknameConflictError so callers get a
        # consistent exception type regardless of which check caught the conflict.
        if nickname is not None and "nickname" in str(exc).lower():
            raise NicknameConflictError(nickname) from exc
        raise


async def get_thread(
    session: AsyncSession,
    thread_id: str,
) -> ThreadModel | None:
    """Fetch a thread by its ID.

    Args:
        session: Active async session.
        thread_id: The thread's primary key.

    Returns:
        The ``ThreadModel`` or ``None`` if not found.
    """
    return await session.get(ThreadModel, thread_id)


async def list_threads(
    session: AsyncSession,
    *,
    offset: int = 0,
    limit: int = 50,
) -> tuple[Sequence[ThreadModel], int]:
    """List threads with pagination.

    Args:
        session: Active async session.
        offset: Number of rows to skip.
        limit: Maximum number of rows to return.

    Returns:
        A tuple of ``(threads, total_count)``.
    """
    count_stmt = select(func.count()).select_from(ThreadModel)
    total = (await session.execute(count_stmt)).scalar_one()

    stmt = (
        select(ThreadModel)
        .order_by(ThreadModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all(), total


async def update_thread_status(
    session: AsyncSession,
    thread_id: str,
    status: ThreadStatus | str,
) -> ThreadModel | None:
    """Update a thread's status.

    Args:
        session: Active async session.
        thread_id: The thread's primary key.
        status: New status — ``ThreadStatus`` enum or equivalent string value.
            Invalid strings raise ``ValueError`` (DB-HIGH-02).

    Returns:
        The updated ``ThreadModel`` or ``None`` if not found.

    Raises:
        ValueError: If *status* is not a valid ``ThreadStatus`` value.
    """
    coerced_status = _coerce_status(status)
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    thread.status = coerced_status
    # DB-H2: onupdate=_utcnow only fires at the DB level; the in-memory object
    # has a stale updated_at after flush when expire_on_commit=False.  Set it
    # explicitly so callers always receive the current timestamp.
    thread.updated_at = datetime.now(UTC)
    await session.flush()
    return thread


async def update_thread_metadata(
    session: AsyncSession,
    thread_id: str,
    metadata: str | None,
) -> ThreadModel | None:
    """Update a thread's serialised metadata JSON.

    Args:
        session: Active async session.
        thread_id: The thread's primary key.
        metadata: New metadata JSON string (ADR-014), or ``None`` to clear.

    Returns:
        The updated ``ThreadModel`` or ``None`` if not found.
    """
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    thread.thread_metadata = metadata
    # DB-H2: keep updated_at consistent — set explicitly to avoid stale value.
    thread.updated_at = datetime.now(UTC)
    await session.flush()
    return thread


async def get_thread_metadata(
    session: AsyncSession,
    thread_id: str,
) -> str | None:
    """Fetch the serialised metadata JSON for a thread.

    Args:
        session: Active async session.
        thread_id: The thread's primary key.

    Returns:
        The metadata JSON string, or ``None`` if the thread is missing
        or has no metadata.
    """
    thread = await session.get(ThreadModel, thread_id)
    if thread is None:
        return None
    return thread.thread_metadata


# ---------------------------------------------------------------------------
# Artifact CRUD
# ---------------------------------------------------------------------------


async def create_artifact(
    session: AsyncSession,
    *,
    thread_id: str,
    artifact_type: str,
    path: str,
    artifact_id: str | None = None,
) -> ArtifactModel:
    """Create a new file artifact record.

    For additional fields (``content_hash``, ``agent_id``), construct an
    ``ArtifactModel`` directly and use ``save_model``.

    Args:
        session: Active async session.
        thread_id: Parent thread ID.
        artifact_type: Type classifier (e.g. ``"file"``, ``"diff"``).
        path: Filesystem path of the artifact.
        artifact_id: Optional explicit ID; auto-generated if omitted.

    Returns:
        The persisted ``ArtifactModel`` instance.
    """
    artifact = ArtifactModel(
        id=artifact_id or uuid4().hex,
        thread_id=thread_id,
        type=artifact_type,
        path=path,
    )
    return await save_model(session, artifact)


async def get_artifact(
    session: AsyncSession,
    artifact_id: str,
) -> ArtifactModel | None:
    """Fetch an artifact by its ID.

    Args:
        session: Active async session.
        artifact_id: The artifact's primary key.

    Returns:
        The ``ArtifactModel`` or ``None`` if not found.
    """
    return await session.get(ArtifactModel, artifact_id)


async def get_artifacts_by_thread(
    session: AsyncSession,
    thread_id: str,
) -> Sequence[ArtifactModel]:
    """Fetch all artifacts belonging to a thread.

    Args:
        session: Active async session.
        thread_id: The parent thread ID.

    Returns:
        A sequence of ``ArtifactModel`` instances.
    """
    stmt = (
        select(ArtifactModel)
        .where(ArtifactModel.thread_id == thread_id)
        .order_by(ArtifactModel.created_at)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Permission Log CRUD
# ---------------------------------------------------------------------------


async def append_permission_log(
    session: AsyncSession,
    *,
    thread_id: str,
    agent_id: str,
    tool_name: str,
    action: str,
) -> PermissionLogModel:
    """Append a permission decision to the audit log.

    For additional fields (``option_id``), construct a
    ``PermissionLogModel`` directly and use ``save_model``.

    Args:
        session: Active async session.
        thread_id: Parent thread ID.
        agent_id: ID of the agent that requested permission.
        tool_name: Name of the tool requiring permission.
        action: The action taken (e.g. ``"allow_once"``).

    Returns:
        The persisted ``PermissionLogModel`` instance.
    """
    log_entry = PermissionLogModel(
        id=uuid4().hex,
        thread_id=thread_id,
        agent_id=agent_id,
        tool_name=tool_name,
        action=action,
    )
    return await save_model(session, log_entry)


async def get_permission_logs_by_thread(
    session: AsyncSession,
    thread_id: str,
) -> Sequence[PermissionLogModel]:
    """Fetch all permission log entries for a thread.

    Args:
        session: Active async session.
        thread_id: The parent thread ID.

    Returns:
        A sequence of ``PermissionLogModel`` instances ordered by response time.
    """
    stmt = (
        select(PermissionLogModel)
        .where(PermissionLogModel.thread_id == thread_id)
        .order_by(PermissionLogModel.responded_at)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Cost Tracking CRUD
# ---------------------------------------------------------------------------


async def append_cost_record(
    session: AsyncSession,
    record: CostTrackingModel,
) -> CostTrackingModel:
    """Persist a cost tracking record for an LLM invocation.

    Callers construct a ``CostTrackingModel`` with all fields and pass
    it here for persistence.

    Args:
        session: Active async session.
        record: The cost tracking model instance to persist.

    Returns:
        The persisted ``CostTrackingModel`` instance.
    """
    return await save_model(session, record)


async def sum_cost_by_thread(
    session: AsyncSession,
    thread_id: str,
) -> dict[str, int | float]:
    """Sum token usage and cost for an entire thread.

    Args:
        session: Active async session.
        thread_id: The thread to aggregate.

    Returns:
        A dict with ``input_tokens``, ``output_tokens``, and
        ``estimated_cost`` totals.
    """
    stmt = select(
        func.coalesce(func.sum(CostTrackingModel.input_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.output_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.estimated_cost), 0.0),
    ).where(CostTrackingModel.thread_id == thread_id)

    row = (await session.execute(stmt)).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
        "estimated_cost": row[2],
    }


async def sum_cost_by_agent(
    session: AsyncSession,
    agent_id: str,
) -> dict[str, int | float]:
    """Sum token usage and cost for a specific agent across all threads.

    Args:
        session: Active async session.
        agent_id: The agent to aggregate.

    Returns:
        A dict with ``input_tokens``, ``output_tokens``, and
        ``estimated_cost`` totals.
    """
    stmt = select(
        func.coalesce(func.sum(CostTrackingModel.input_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.output_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.estimated_cost), 0.0),
    ).where(CostTrackingModel.agent_id == agent_id)

    row = (await session.execute(stmt)).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
        "estimated_cost": row[2],
    }
