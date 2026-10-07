"""Cost repository — the ``cost_tracking`` aggregate."""

from __future__ import annotations

from decimal import Decimal
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


async def _cost_totals(
    session: AsyncSession, criterion: ColumnElement[bool]
) -> dict[str, int | Decimal]:
    """Return the summed token counts and exact summed cost of the matching rows.

    ``estimated_cost`` is a ``Decimal``, never a float: the sum is aggregated
    in the database over an exact column type and returned without ever
    passing through IEEE-754.
    """
    row = (await session.execute(_cost_totals_select().where(criterion))).one()
    return {
        "input_tokens": row[0],
        "output_tokens": row[1],
        "estimated_cost": row[2],
    }


async def sum_cost_by_thread(
    session: AsyncSession, thread_id: str
) -> dict[str, int | Decimal]:
    """Return summed token counts and exact summed cost for one thread."""
    return await _cost_totals(session, CostTrackingModel.thread_id == thread_id)


async def sum_cost_by_agent(
    session: AsyncSession, agent_id: str
) -> dict[str, int | Decimal]:
    """Return summed token counts and exact summed cost for one agent."""
    return await _cost_totals(session, CostTrackingModel.agent_id == agent_id)
