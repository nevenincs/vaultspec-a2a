"""FastAPI dependency injection providers for the A2A gateway.

Injected at lifespan startup via ``app.state``; these functions read from it.
Used by all route modules in ``api/routes/``.

``require_lifecycle_capability`` lives here too: the receipt-bound ownership gate
that discovery never references, required ON TOP OF the attach gate for lifecycle
operations such as administrative shutdown. The attach gate itself is
:func:`vaultspec_a2a.api.auth.authenticate_request` and routes mount it from there
directly. This module does not re-offer it under a second spelling - nothing here
overrides or adapts it, so an alias would only hide which module answers for the
credential. Both gates compare in constant time and never disclose the expected
credential in a failure.
"""

import hmac
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import Checkpointer, get_db
from ..desktop.credentials import MAX_CREDENTIAL_BYTES
from ..streaming import RelayHub

# The header carrying the receipt-bound lifecycle ownership capability. Distinct
# from the attach Authorization bearer so the two planes never alias; loopback-only
# exposure keeps the raw capability off any shared or logged transport.
LIFECYCLE_CAPABILITY_HEADER = "X-Vaultspec-Lifecycle-Capability"

__all__ = [
    "LIFECYCLE_CAPABILITY_HEADER",
    "get_checkpointer",
    "get_circuit_breaker",
    "get_relay_hub",
    "get_services",
    "get_worker_client",
    "get_worker_spawner",
    "require_lifecycle_capability",
]


async def require_lifecycle_capability(
    request: Request,
    capability: str | None = Header(
        default=None,
        alias=LIFECYCLE_CAPABILITY_HEADER,
        max_length=MAX_CREDENTIAL_BYTES,
    ),
) -> None:
    """Require the receipt-bound lifecycle ownership capability, in constant time.

    Layered on top of attach authentication for receipt-bound lifecycle operations
    (for example administrative shutdown): a valid attach credential proves the
    caller may talk to the gateway, this proves the caller owns the install receipt.
    The capability the gateway holds is loaded from the dashboard-created ownership
    file that discovery never references. A missing runtime capability is corrupted
    application state and fails closed; a mismatch is redacted so neither presence
    nor shape of the expected value leaks.
    """
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


def get_relay_hub(request: Request) -> RelayHub:
    """FastAPI dependency for the gateway's relay hub singleton."""
    relay_hub: RelayHub | None = getattr(request.app.state, "relay_hub", None)
    if relay_hub is None:
        raise RuntimeError("Relay hub not initialised in app state")
    return relay_hub


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
    relay_hub: RelayHub = Depends(get_relay_hub),
    checkpointer: Checkpointer = Depends(get_checkpointer),
    worker_client: httpx.AsyncClient = Depends(get_worker_client),
) -> tuple[AsyncSession, RelayHub, Checkpointer, httpx.AsyncClient]:
    """Dependency for bundling all required services into a single injection point.

    No longer includes GraphRegistry or TaskGroup -- the worker owns
    graph lifecycle, and the gateway does not run background agent tasks.
    """
    return db, relay_hub, checkpointer, worker_client
