r"""Worker process -- standalone FastAPI application.

Exposes an internal HTTP dispatch endpoint that the gateway
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
import os
import signal
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from uuid import uuid4

import anyio  # anyio: structured task groups for heartbeat + dispatch.
import anyio.abc
import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from opentelemetry import metrics, trace

from ..control.config import settings
from ..database.checkpoints import open_checkpointer
from ..ipc.schemas import DispatchRequest, DispatchResponse
from ..lifecycle.registration import deregister_serve, register_serve
from ..telemetry import TelemetryMiddleware, configure_telemetry
from ..utils import BearerVerdict, verify_internal_bearer
from ..utils.asyncio_compat import configure_asyncio_runtime
from .executor import Executor
from .ipc import WorkerBridge

__all__ = ["WorkerApp", "create_worker_app", "main"]

logger = logging.getLogger(__name__)

# Re-export so the facade ``vaultspec_a2a.worker`` can expose ``WorkerApp``
# as the public type alias (matches the placeholder's API contract).
WorkerApp = FastAPI


async def _verify_dispatch_token(
    authorization: str | None = Header(None),
) -> None:
    """Verify bearer token for gateway->worker dispatch requests.

    Delegates the rule to the shared IPC bearer verifier; the worker keeps its
    ``WWW-Authenticate`` header on the 401.
    """
    verdict, detail = verify_internal_bearer(
        authorization,
        token=settings.internal_token,
        environment=settings.environment,
    )
    if verdict is BearerVerdict.MISCONFIGURED:
        raise HTTPException(status_code=500, detail=detail)
    if verdict is BearerVerdict.UNAUTHORIZED:
        raise HTTPException(
            status_code=401,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Worker lifespan: initialise checkpointer, bridge, executor, heartbeat.

    Startup sequence:
    1. Open the configured backend-selectable checkpointer (SQLite or Postgres) via
       ``open_checkpointer()``.
    2. Create the ``WorkerBridge`` HTTP client.
    3. Instantiate the ``Executor`` with checkpointer + bridge.
    4. Launch the heartbeat loop as a background task.

    On shutdown the heartbeat is cancelled and the bridge client closed.
    """
    worker_id = uuid4().hex[:8]
    logger.info("Worker %s starting", worker_id)
    settings.validate_postgres_requirement()

    # Configure OTel with the worker service name so spans are
    # attributed separately from the gateway in Jaeger/OTLP backends.
    configure_telemetry(service_name="vaultspec-worker")
    logger.info("Telemetry configured (service=vaultspec-worker)")

    async with open_checkpointer() as checkpointer:
        bridge = WorkerBridge(
            settings.gateway_url,
            worker_id,
            settings.internal_token,
        )

        # Non-fatal startup probe — verify the gateway is
        # reachable *before* we accept dispatches. Logs ERROR if the
        # gateway cannot be contacted so operators notice immediately.
        try:
            probe = await bridge._client.get("/health")
            if probe.status_code == 200:
                logger.info(
                    "Gateway reachable at %s",
                    settings.gateway_url,
                )
            else:
                logger.error(
                    "Gateway probe returned HTTP %d"
                    " (gateway_url=%s) — IPC events may"
                    " not be delivered",
                    probe.status_code,
                    settings.gateway_url,
                )
        except httpx.HTTPError:
            logger.error(
                "Gateway UNREACHABLE at startup"
                " (gateway_url=%s) — permission requests"
                " and status events will NOT be delivered"
                " until the gateway is available",
                settings.gateway_url,
                exc_info=True,
            )

        executor = Executor(checkpointer, bridge)

        app.state.executor = executor
        app.state.bridge = bridge

        # A worker booted on a band port (worker-dev)
        # self-registers so `procs` can enumerate/reap it; a resident worker on
        # its fixed out-of-band port registers nothing (returns None). worker-dev
        # is a non-heartbeat role, so pid-liveness alone governs its staleness.
        worker_record = register_serve(
            "worker-dev",
            settings.worker_port,
            workspace=str(settings.workspace_root),
            command=[
                "python",
                "-m",
                "vaultspec_a2a.worker",
                "--port",
                str(settings.worker_port),
            ],
        )

        async with anyio.create_task_group() as tg:
            app.state.task_group = tg

            # Start the periodic heartbeat loop as a background task.
            tg.start_soon(bridge.heartbeat_loop, 10.0)

            logger.info("Worker %s ready on port %d", worker_id, settings.worker_port)

            yield

            # Shutdown path
            logger.info("Worker %s shutting down", worker_id)
            deregister_serve(worker_record)
            tg.cancel_scope.cancel()

        await executor.shutdown()
        await bridge.close()

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            await anyio.to_thread.run_sync(provider.shutdown)  # ty: ignore[unresolved-attribute]
        meter_provider = metrics.get_meter_provider()
        if hasattr(meter_provider, "shutdown"):
            await anyio.to_thread.run_sync(meter_provider.shutdown)  # ty: ignore[unresolved-attribute]


def create_worker_app(lifespan: Any | None = None) -> FastAPI:
    """Create and return the worker FastAPI application.

    Args:
        lifespan: Optional lifespan override for testing. When ``None``
            the production ``_lifespan`` is used.

    Called as a factory by ``uvicorn`` (``--factory`` flag) or directly
    in tests.
    """
    app = FastAPI(
        title="Vaultspec Worker",
        version="0.1.0",
        lifespan=lifespan or _lifespan,
    )

    # Instrument incoming requests so the worker's spans participate
    # in distributed traces started by the gateway (W3C traceparent extraction).
    app.add_middleware(cast("Any", TelemetryMiddleware))

    @app.post(
        "/dispatch",
        response_model=DispatchResponse,
        dependencies=[Depends(_verify_dispatch_token)],
    )
    async def dispatch_endpoint(req: DispatchRequest) -> DispatchResponse:
        """Accept a work dispatch from the gateway.

        The actual graph execution is scheduled as a background task inside
        the lifespan task group so that this endpoint returns immediately.
        """
        executor: Executor = app.state.executor
        tg = app.state.task_group

        # Reject dispatch when concurrent thread cap is reached.
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
    async def health_endpoint() -> dict[str, object]:
        """Worker health check.

        Reports the worker's configured heartbeat target (``gateway_url``) so
        a spawning gateway can tell a worker that points at *this* gateway apart
        from a stale orphan still pointing at a dead dev-band gateway. Without
        this provenance the spawn path would blindly adopt the orphan and it
        would heartbeat a dead port forever.
        """
        return {
            "status": "ok",
            "service": "worker",
            "gateway_url": settings.gateway_url,
            "worker_port": settings.worker_port,
            "database_backend": settings.resolved_database_backend,
            "checkpoint_backend": settings.resolved_checkpoint_backend,
            "postgres_required": settings.postgres_required,
        }

    @app.post("/admin/shutdown", status_code=202)
    async def shutdown_endpoint() -> dict[str, str]:
        """Initiate graceful worker shutdown."""
        os.kill(os.getpid(), signal.SIGTERM)
        return {"detail": "shutdown initiated"}

    return app


def main() -> None:
    """Entry point for the ``vaultspec-worker`` console script."""
    configure_asyncio_runtime()
    logger.info(
        "Worker main config: gateway_port=%d worker_host=%s"
        " worker_port=%d worker_url=%s",
        settings.port,
        settings.worker_host,
        settings.worker_port,
        settings.worker_url,
    )
    uvicorn.run(
        "vaultspec_a2a.worker.app:create_worker_app",
        factory=True,
        host=settings.worker_host,
        port=settings.worker_port,
        log_level="info",
        loop="auto",
    )


if __name__ == "__main__":
    main()
