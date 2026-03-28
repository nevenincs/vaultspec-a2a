"""Artifact repository — artifacts, permission logs, and cost tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import func, select

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

from ._helpers import save_model
from .models import ArtifactModel, CostTrackingModel, PermissionLogModel

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
    artifact = ArtifactModel(
        id=artifact_id or uuid4().hex,
        thread_id=thread_id,
        type=artifact_type,
        path=path,
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
    agent_id: str,
    tool_name: str,
    action: str,
) -> PermissionLogModel:
    log_entry = PermissionLogModel(
        id=uuid4().hex,
        thread_id=thread_id,
        agent_id=agent_id,
        tool_name=tool_name,
        action=action,
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


async def sum_cost_by_thread(
    session: AsyncSession, thread_id: str
) -> dict[str, int | float]:
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
    session: AsyncSession, agent_id: str
) -> dict[str, int | float]:
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
