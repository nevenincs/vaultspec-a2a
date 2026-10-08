"""Cost repository — the ``cost_tracking`` aggregate."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

from ._helpers import save_model
from .models import CostTrackingModel

__all__ = [
    "append_cost_record",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
]


async def append_cost_record(
    session: AsyncSession, record: CostTrackingModel
) -> CostTrackingModel:
    return await save_model(session, record)


def _cost_totals_select() -> Select[tuple[int, int]]:
    """Build the shared token aggregate projection."""
    return select(
        func.coalesce(func.sum(CostTrackingModel.input_tokens), 0),
        func.coalesce(func.sum(CostTrackingModel.output_tokens), 0),
    )


async def _cost_totals(
    session: AsyncSession, criterion: ColumnElement[bool]
) -> dict[str, int]:
    """Return the summed token counts of the matching rows."""
    row = (await session.execute(_cost_totals_select().where(criterion))).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
    }


async def sum_cost_by_thread(session: AsyncSession, thread_id: str) -> dict[str, int]:
    """Return summed token counts for one thread."""
    return await _cost_totals(session, CostTrackingModel.thread_id == thread_id)


async def sum_cost_by_agent(session: AsyncSession, agent_id: str) -> dict[str, int]:
    """Return summed token counts for one agent, across every thread it ran in."""
    return await _cost_totals(session, CostTrackingModel.agent_id == agent_id)
