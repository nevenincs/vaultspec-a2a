"""Configuration records for the supervised verdict subscriber."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..authoring import EngineEndpoint
    from ..database.checkpoints import Checkpointer
    from .circuit_breaker import WorkerCircuitBreaker
    from .worker_management import LazyWorkerSpawner

__all__ = ["VerdictSubscriberConfig"]


@dataclass(frozen=True, slots=True, kw_only=True)
class VerdictSubscriberConfig:
    """Public subscriber construction settings."""

    session_factory: async_sessionmaker[AsyncSession]
    checkpointer: Checkpointer
    worker_client: httpx.AsyncClient
    circuit_breaker: WorkerCircuitBreaker
    worker_spawner: LazyWorkerSpawner
    endpoint_provider: Callable[[], EngineEndpoint | None]
    trace_headers_fn: Callable[[], dict[str, str]] | None = None
    poll_interval_seconds: float = 3.0
    reconnect_base_seconds: float = 2.0
    reconnect_max_seconds: float = 30.0
    checkpoint_timeout_seconds: float = 10.0
    parked_thread_limit: int = 200
