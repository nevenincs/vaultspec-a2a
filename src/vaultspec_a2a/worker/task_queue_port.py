"""Database-backed adapter for the graph task-queue port (ADR R5).

Composition-layer bridge: adapts the pure persistence functions in
``database.task_queue_repository`` to the graph layer's abstract
:class:`~vaultspec_a2a.graph.protocols.TaskQueuePort`.  The graph nodes depend
only on the port; this adapter is injected at graph-compile time so the
database layer never leaks into the domain graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..database.task_queue_repository import get_queue_view, mark_task_complete
from ..graph.protocols import MarkCompleteOutcome, QueueEntryView

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["SqlTaskQueuePort"]


class SqlTaskQueuePort:
    """Session-factory-backed adapter implementing ``TaskQueuePort``.

    Each call opens a short-lived session, so the port is safe to share across
    concurrent thread executions on the worker's event loop.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_queue_view(
        self,
        thread_id: str,
        current_task_id: str | None,
        horizon: int,
    ) -> list[QueueEntryView]:
        """Read the injectable queue view for a thread (read-only)."""
        async with self._session_factory() as session:
            models = await get_queue_view(session, thread_id, current_task_id, horizon)
            return [
                QueueEntryView(
                    task_key=model.task_key,
                    status=model.status,
                    description=model.description,
                )
                for model in models
            ]

    async def mark_complete(
        self,
        thread_id: str,
        task_key: str,
    ) -> MarkCompleteOutcome:
        """Apply an idempotent mark-complete transition and commit."""
        async with self._session_factory() as session:
            result = await mark_task_complete(session, thread_id, task_key)
            await session.commit()
            return MarkCompleteOutcome(
                found=result.found,
                did_complete=result.did_complete,
                next_task_key=result.next_task_key,
            )
