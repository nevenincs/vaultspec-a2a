"""Cost repository — the ``cost_tracking`` aggregate.

The one accounting home. Every read here reports counts a provider lane
actually declared and nothing derived from them: a breakdown no summed row
reported stays ``None``, and a thread with no rows at all reads back as no
accounting rather than as a measured zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement, Select
    from sqlalchemy.ext.asyncio import AsyncSession

from ._helpers import save_model
from .models import CostTrackingModel

__all__ = [
    "TokenUsageTotals",
    "append_cost_record",
    "sum_cost_by_role",
    "sum_cost_by_thread",
]


@dataclass(frozen=True, kw_only=True, slots=True)
class TokenUsageTotals:
    """Provider-reported token counts summed over a set of accounting rows.

    ``input_tokens`` and ``output_tokens`` are the two counts every lane
    reports, so they are present whenever any row was summed. The other three
    are the breakdown a lane may or may not report, and they stay ``None`` when
    no summed row reported them - the same distinction the nullable columns
    behind them keep, carried through the aggregate instead of being flattened
    to a zero nobody measured.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    reasoning_tokens: int | None


async def append_cost_record(
    session: AsyncSession, record: CostTrackingModel
) -> CostTrackingModel:
    return await save_model(session, record)


def _summed_counts() -> tuple[
    ColumnElement[int | None],
    ColumnElement[int | None],
    ColumnElement[int | None],
    ColumnElement[int | None],
    ColumnElement[int | None],
]:
    """Return the five summed count columns every accounting read projects.

    Deliberately NOT coalesced. ``SUM`` over no rows is ``NULL``, and over rows
    that all left a breakdown unreported it is ``NULL`` too, which is exactly
    the fact the read must carry: coalescing here would turn both into a
    measured zero before any caller could tell the difference.
    """
    return (
        func.sum(CostTrackingModel.input_tokens),
        func.sum(CostTrackingModel.output_tokens),
        func.sum(CostTrackingModel.cache_read_tokens),
        func.sum(CostTrackingModel.cache_write_tokens),
        func.sum(CostTrackingModel.reasoning_tokens),
    )


def _totals_of(
    reported_input: int | None,
    reported_output: int | None,
    cache_read: int | None,
    cache_write: int | None,
    reasoning: int | None,
) -> TokenUsageTotals | None:
    """Read one aggregate row, or ``None`` when it summed no accounting rows.

    The two always-reported counts come off NOT NULL columns, so a ``NULL``
    there can only mean the aggregate found nothing to sum.
    """
    if reported_input is None or reported_output is None:
        return None
    return TokenUsageTotals(
        input_tokens=reported_input,
        output_tokens=reported_output,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=reasoning,
    )


def _thread_totals_select(
    thread_id: str,
) -> Select[tuple[int | None, int | None, int | None, int | None, int | None]]:
    """Project one thread's whole-run totals."""
    return select(*_summed_counts()).where(CostTrackingModel.thread_id == thread_id)


def _thread_role_totals_select(
    thread_id: str,
) -> Select[tuple[str, int | None, int | None, int | None, int | None, int | None]]:
    """Project one thread's totals split by the role that spent them.

    Scoped to the thread, never to the role alone. A role id is a seat in a team
    preset rather than a per-run identity, so ``coder-1`` names a different seat
    in every run that has one; an aggregate keyed on the role alone would answer
    a run's question with every other run's tokens folded in.
    """
    return (
        select(CostTrackingModel.agent_id, *_summed_counts())
        .where(CostTrackingModel.thread_id == thread_id)
        .group_by(CostTrackingModel.agent_id)
        .order_by(CostTrackingModel.agent_id)
    )


async def sum_cost_by_thread(
    session: AsyncSession, thread_id: str
) -> TokenUsageTotals | None:
    """Return one thread's summed counts, or ``None`` if it recorded none."""
    row = (await session.execute(_thread_totals_select(thread_id))).one()
    return _totals_of(row[0], row[1], row[2], row[3], row[4])


async def sum_cost_by_role(
    session: AsyncSession, thread_id: str
) -> dict[str, TokenUsageTotals]:
    """Return one thread's summed counts per role, ordered by role id.

    A role that recorded nothing is absent rather than present with zeros, so
    the mapping says which seats actually took a turn.
    """
    rows = (await session.execute(_thread_role_totals_select(thread_id))).all()
    per_role: dict[str, TokenUsageTotals] = {}
    for row in rows:
        totals = _totals_of(row[1], row[2], row[3], row[4], row[5])
        if totals is not None:
            per_role[row[0]] = totals
    return per_role
