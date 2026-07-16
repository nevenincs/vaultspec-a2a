"""FastAPI dependency injection providers for the A2A gateway.

Injected at lifespan startup via ``app.state``; these functions read from it.
Used by all route modules in ``api/routes/``.
"""

from typing import Any

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.checkpoints import Checkpointer
from ..database.session import get_db
from ..streaming.aggregator import EventAggregator

__all__ = [
    "get_aggregator",
    "get_checkpointer",
    "get_circuit_breaker",
    "get_db",
    "get_services",
    "get_worker_client",
    "get_worker_spawner",
]


def get_aggregator(request: Request) -> EventAggregator:
    """FastAPI dependency for the EventAggregator singleton."""
    aggregator: EventAggregator | None = getattr(request.app.state, "aggregator", None)
    if aggregator is None:
        raise RuntimeError("EventAggregator not initialised in app state")
    return aggregator


def get_checkpointer(request: Request) -> Checkpointer:
    """FastAPI dependency for the LangGraph checkpointer (read-only)."""
    checkpointer: Checkpointer | None = getattr(request.app.state, "checkpointer", None)
    if checkpointer is None:
        raise RuntimeError("LangGraph checkpointer not initialised in app state")
    return checkpointer


def get_worker_client(request: Request) -> httpx.AsyncClient:
    """FastAPI dependency for the httpx client pointing at the worker."""
    client: httpx.AsyncClient | None = getattr(request.app.state, "worker_client", None)
    if client is None:
        raise RuntimeError("Worker httpx client not initialised in app state")
    return client


def get_circuit_breaker(request: Request) -> Any:
    """FastAPI dependency for the WorkerCircuitBreaker."""
    cb = getattr(request.app.state, "circuit_breaker", None)
    if cb is None:
        raise RuntimeError("WorkerCircuitBreaker not initialised in app state")
    return cb


def get_worker_spawner(request: Request) -> Any:
    """FastAPI dependency for the LazyWorkerSpawner (PHASE-1a)."""
    spawner = getattr(request.app.state, "worker_spawner", None)
    if spawner is None:
        raise RuntimeError("LazyWorkerSpawner not initialised in app state")
    return spawner


async def get_services(
    db: AsyncSession = Depends(get_db),
    aggregator: EventAggregator = Depends(get_aggregator),
    checkpointer: Checkpointer = Depends(get_checkpointer),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
) -> tuple[AsyncSession, EventAggregator, Checkpointer, httpx.AsyncClient]:
    """Dependency for bundling all required services into a single injection point.

    No longer includes GraphRegistry or TaskGroup -- the worker owns
    graph lifecycle, and the gateway does not run background agent tasks.
    """
    return db, aggregator, checkpointer, worker_client
