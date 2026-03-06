r"""Worker process -- standalone FastAPI application (ADR-019).

Exposes an internal HTTP dispatch endpoint that the control surface
calls to schedule graph execution.  Manages the ``Executor`` lifecycle
and heartbeat loop.

Run standalone::

    python -m uvicorn vaultspec_a2a.worker.app:create_worker_app \
        --factory --host 127.0.0.1 --port 8001

Or via the ``vaultspec-worker`` console script (once registered in
``pyproject.toml``).
"""

from __future__ import annotations

import logging

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

import anyio
import uvicorn

from fastapi import FastAPI, HTTPException

from ..api.schemas.internal import DispatchRequest, DispatchResponse
from ..core.config import settings
from .executor import Executor
from .ipc import WorkerBridge


__all__ = ["WorkerApp", "create_worker_app", "main"]

logger = logging.getLogger(__name__)

# Re-export so the facade ``lib.worker`` can expose ``WorkerApp``
# as the public type alias (matches the placeholder's API contract).
WorkerApp = FastAPI


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Worker lifespan: initialise checkpointer, bridge, executor, heartbeat.

    Startup sequence:
    1. Open the shared SQLite checkpointer (WAL mode, same path as the
       control surface).
    2. Create the ``WorkerBridge`` HTTP client.
    3. Instantiate the ``Executor`` with checkpointer + bridge.
    4. Launch the heartbeat loop as a background task.

    On shutdown the heartbeat is cancelled and the bridge client closed.
    """
    worker_id = uuid4().hex[:8]
    logger.info("Worker %s starting", worker_id)

    # Database -- shared SQLite via WAL (same file as control surface).
    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Import here to keep the top-level import footprint small and avoid
    # circular dependency chains through the langgraph checkpoint package.
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        await checkpointer.setup()

        bridge = WorkerBridge(
            settings.mcp_api_base_url,
            worker_id,
            settings.internal_token,
        )
        executor = Executor(checkpointer, bridge)

        app.state.executor = executor
        app.state.bridge = bridge

        async with anyio.create_task_group() as tg:
            app.state.task_group = tg

            # Start the periodic heartbeat loop as a background task.
            tg.start_soon(bridge.heartbeat_loop, 10.0)

            logger.info("Worker %s ready on port %d", worker_id, settings.worker_port)

            yield

            # Shutdown path
            logger.info("Worker %s shutting down", worker_id)
            await executor.shutdown()
            await bridge.close()
            tg.cancel_scope.cancel()


def create_worker_app() -> FastAPI:
    """Create and return the worker FastAPI application.

    Called as a factory by ``uvicorn`` (``--factory`` flag) or directly
    in tests.
    """
    app = FastAPI(
        title="Vaultspec Worker",
        version="0.1.0",
        lifespan=_lifespan,
    )

    @app.post("/dispatch", response_model=DispatchResponse)
    async def dispatch_endpoint(req: DispatchRequest) -> DispatchResponse:
        """Accept a work dispatch from the control surface.

        The actual graph execution is scheduled as a background task inside
        the lifespan task group so that this endpoint returns immediately.
        """
        executor: Executor = app.state.executor
        tg: anyio.abc.TaskGroup = app.state.task_group  # type: ignore[assignment]

        # WPA-001: Reject dispatch when concurrent thread cap is reached.
        if executor.at_capacity():
            raise HTTPException(
                status_code=429,
                detail="Worker at capacity — too many concurrent threads",
            )

        # Fire-and-forget: the task group keeps the task alive even after
        # this endpoint handler returns.
        tg.start_soon(executor.handle_dispatch, req)

        return DispatchResponse(
            status="dispatched",
            thread_id=req.thread_id,
        )

    @app.get("/health")
    async def health_endpoint() -> dict[str, str]:
        """Worker health check."""
        return {"status": "ok", "service": "worker"}

    return app


def main() -> None:
    """Entry point for the ``vaultspec-worker`` console script."""
    uvicorn.run(
        "vaultspec_a2a.worker.app:create_worker_app",
        factory=True,
        host="127.0.0.1",
        port=settings.worker_port,
        log_level="info",
    )
