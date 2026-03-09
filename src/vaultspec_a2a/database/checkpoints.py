"""LangGraph checkpointer factory helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast, runtime_checkable

from ..core.config import settings


@runtime_checkable
class Checkpointer(Protocol):
    """Minimal async checkpointer surface used by the runtime."""

    async def setup(self) -> None:
        """Initialise persistence tables if needed."""

    async def aget_tuple(self, config: Any) -> Any:  # noqa: ANN401
        """Read a checkpoint tuple for the provided runnable config."""


@asynccontextmanager
async def open_checkpointer() -> AsyncIterator[Checkpointer]:
    """Open the configured LangGraph checkpointer backend."""
    if settings.resolved_checkpoint_backend == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(
            settings.checkpoint_connection_string
        ) as checkpointer:
            await checkpointer.setup()
            yield cast(Checkpointer, checkpointer)
        return

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        msg = (
            "Postgres checkpoint backend selected but "
            "`langgraph-checkpoint-postgres` is not installed."
        )
        raise RuntimeError(msg) from exc

    async with AsyncPostgresSaver.from_conn_string(
        settings.checkpoint_connection_string
    ) as checkpointer:
        await checkpointer.setup()
        yield cast(Checkpointer, checkpointer)
