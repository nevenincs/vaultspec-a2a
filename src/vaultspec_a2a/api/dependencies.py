"""FastAPI dependency injection providers for the A2A gateway.

Injected at lifespan startup via ``app.state``; these functions read from it.
Used by all route modules in ``api/routes/``.

Authentication dependencies live here too. ``require_attach`` is the pre-existing
attach-control gate (re-exported from :mod:`vaultspec_a2a.api.auth` so route modules
have one import surface); it authenticates dashboard control and product traffic.
``require_lifecycle_capability`` is the additional receipt-bound ownership gate that
discovery never references, required on top of attach for lifecycle operations such
as administrative shutdown. Both compare in constant time and never disclose the
expected credential in a failure.
"""

import hmac
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.checkpoints import Checkpointer
from ..database.session import get_db
from ..streaming.aggregator import EventAggregator
from .auth import authenticate_request as require_attach

# The header carrying the receipt-bound lifecycle ownership capability. Distinct
# from the attach Authorization bearer so the two planes never alias; loopback-only
# exposure keeps the raw capability off any shared or logged transport.
LIFECYCLE_CAPABILITY_HEADER = "X-Vaultspec-Lifecycle-Capability"

__all__ = [
    "LIFECYCLE_CAPABILITY_HEADER",
    "get_aggregator",
    "get_checkpointer",
    "get_circuit_breaker",
    "get_db",
    "get_services",
    "get_worker_client",
    "get_worker_spawner",
    "require_attach",
    "require_lifecycle_capability",
]


async def require_lifecycle_capability(
    request: Request,
    capability: str | None = Header(default=None, alias=LIFECYCLE_CAPABILITY_HEADER),
) -> None:
    """Require the receipt-bound lifecycle ownership capability, in constant time.

    Layered on top of attach authentication for receipt-bound lifecycle operations
    (for example administrative shutdown): a valid attach credential proves the
    caller may talk to the gateway, this proves the caller owns the install receipt.
    The capability the gateway holds is loaded from the dashboard-created ownership
    file that discovery never references. A missing runtime capability is corrupted
    application state and fails closed; a mismatch is redacted so neither presence
    nor shape of the expected value leaks. Only an app created with the explicit
    test-only bypass may run without one.
    """
    if bool(getattr(request.app.state, "allow_unauthenticated_v1_for_testing", False)):
        return
    expected = getattr(request.app.state, "lifecycle_capability", None)
    if not isinstance(expected, str) or not expected:
        raise HTTPException(
            status_code=503,
            detail="Lifecycle ownership capability is not configured",
        )
    supplied = (capability or "").encode("utf-8")
    if not hmac.compare_digest(supplied, expected.encode("utf-8")):
        raise HTTPException(
            status_code=403,
            detail="Lifecycle ownership capability required",
        )


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
