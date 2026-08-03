"""Database-backed adapter for the graph token-accounting port.

Composition-layer bridge, the sibling of :mod:`.task_queue_port`: adapts the
pure persistence function in ``database.artifact_repository`` to the graph
layer's abstract :class:`~vaultspec_a2a.graph.protocols.CostPort`. The graph
nodes depend only on the port; this adapter is injected at graph-compile time
so the database layer never leaks into the domain graph.

``estimated_cost`` is deliberately NOT written here. Both real provider lanes
are subscription-authenticated CLI agents rather than metered per-token APIs,
and the project holds no rate table for any model, so there is no price to
apply. The column keeps its exact zero default until a priced lane exists;
recording a fabricated or perpetually-zero cost as if it were measured would be
worse than leaving it plainly unset. Token counts, by contrast, are real
provider-reported facts and are persisted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from ..database.artifact_repository import append_cost_record
from ..database.models import CostTrackingModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["SqlCostPort"]


class SqlCostPort:
    """Session-factory-backed adapter implementing ``CostPort``.

    Each call opens a short-lived session, so the port is safe to share across
    concurrent thread executions on the worker's event loop.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_usage(
        self,
        *,
        thread_id: str,
        agent_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Persist one invocation's token accounting and commit."""
        async with self._session_factory() as session:
            await append_cost_record(
                session,
                CostTrackingModel(
                    id=uuid4().hex,
                    thread_id=thread_id,
                    agent_id=agent_id,
                    provider=provider,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ),
            )
            await session.commit()
