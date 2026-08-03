"""Artifact repository — artifacts, permission logs, and cost tracking."""

from __future__ import annotations

from decimal import Decimal
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession

from ._helpers import save_model
from .models import ArtifactModel, CostTrackingModel, PermissionLogModel


def _validate_artifact_path(path: str) -> str:
    """Ensure artifact path is relative and contains no traversal components."""
    if not path:
        raise ValueError("Artifact path must not be empty")
    cleaned = path.replace("\\", "/")
    normalized = PurePosixPath(cleaned)
    if normalized.is_absolute() or (len(cleaned) >= 2 and cleaned[1] == ":"):
        raise ValueError(f"Artifact path must be relative, got: {path!r}")
    if ".." in normalized.parts:
        raise ValueError(f"Artifact path must not contain '..', got: {path!r}")
    return str(normalized)


__all__ = [
    "append_cost_record",
    "append_permission_log",
    "create_artifact",
    "get_artifact",
    "get_artifacts_by_thread",
    "get_permission_logs_by_thread",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
]


async def create_artifact(
    session: AsyncSession,
    *,
    thread_id: str,
    artifact_type: str,
    path: str,
    artifact_id: str | None = None,
) -> ArtifactModel:
    safe_path = _validate_artifact_path(path)
    artifact = ArtifactModel(
        id=artifact_id or uuid4().hex,
        thread_id=thread_id,
        type=artifact_type,
        path=safe_path,
    )
    return await save_model(session, artifact)


async def get_artifact(session: AsyncSession, artifact_id: str) -> ArtifactModel | None:
    return await session.get(ArtifactModel, artifact_id)


async def get_artifacts_by_thread(
    session: AsyncSession, thread_id: str
) -> Sequence[ArtifactModel]:
    stmt = (
        select(ArtifactModel)
        .where(ArtifactModel.thread_id == thread_id)
        .order_by(ArtifactModel.created_at)
    )
    return (await session.execute(stmt)).scalars().all()


async def append_permission_log(
    session: AsyncSession,
    *,
    thread_id: str,
    agent_id: str | None,
    tool_name: str,
    action: str,
    option_id: str | None = None,
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
        thread_id=thread_id,
        agent_id=agent_id,
        tool_name=tool_name,
        action=action,
        option_id=option_id,
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


async def append_cost_record(
    session: AsyncSession, record: CostTrackingModel
) -> CostTrackingModel:
    return await save_model(session, record)


def _cost_totals_select() -> Select[tuple[int, int, Decimal]]:
    """Build the shared token/cost aggregate projection.

    ``estimated_cost`` coalesces to a ``Decimal`` zero rather than ``0.0``: the
    literal is bound through the column's own ``MoneyAmount`` type, and a float
    zero would reintroduce the very type the column exists to keep out.
    """
    return select(
        func.coalesce(func.sum(CostTrackingModel.input_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.output_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.estimated_cost), Decimal(0)),
    )


async def sum_cost_by_thread(
    session: AsyncSession, thread_id: str
) -> dict[str, int | Decimal]:
    """Return summed token counts and exact summed cost for one thread.

    ``estimated_cost`` is a ``Decimal``, never a float: the sum is aggregated
    in the database over an exact column type and returned without ever
    passing through IEEE-754.
    """
    stmt = _cost_totals_select().where(CostTrackingModel.thread_id == thread_id)
    row = (await session.execute(stmt)).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
        "estimated_cost": row[2],
    }


async def sum_cost_by_agent(
    session: AsyncSession, agent_id: str
) -> dict[str, int | Decimal]:
    """Return summed token counts and exact summed cost for one agent."""
    stmt = _cost_totals_select().where(CostTrackingModel.agent_id == agent_id)
    row = (await session.execute(stmt)).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
        "estimated_cost": row[2],
    }
