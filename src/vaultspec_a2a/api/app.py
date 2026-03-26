"""FastAPI application factory -- the gateway entry point (ADR-019).

Creates the ASGI application with:
- Lifespan management (init/close DB, EventAggregator, telemetry)
- CORS middleware (permissive in dev)
- REST router from per-resource route modules
- Internal router from ``internal.py`` (worker relay)
- WebSocket route via ``ConnectionManager``
- StaticFiles mount for React SPA build at ``src/ui/build/`` (ADR-007/018)

The gateway NO LONGER runs agent execution locally.  All graph
compilation and ``aggregator.ingest()`` calls are dispatched to the
worker process via HTTP POST to ``/dispatch`` (ADR-019 service separation).

See: ADR-007 (FastAPI serving, SPA)
     ADR-011 (Frontend-Backend Wire Contract)
     ADR-019 (Service Separation)
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocket

from ..control.circuit_breaker import WorkerCircuitBreaker
from ..control.config import settings
from ..control.dispatch import redispatch_reconciling_threads
from ..control.health import assemble_health_status, build_sqlite_fallback_diagnostics
from ..control.worker_management import (
    LazyWorkerSpawner,
    WorkerState,
    WorkerWatchdog,
)
from ..database.checkpoints import open_checkpointer
from ..database.migrations import backfill_teamstate_sdd_fields
from ..database.reconciliation import reconcile_threads_on_startup
from ..database.session import (
    close_db,
    get_session_factory,
    init_db,
)
from ..streaming.aggregator import EventAggregator
from ..telemetry import TelemetryMiddleware, configure_telemetry
from ..telemetry.aggregator_hook import OTelAggregatorHook
from ..utils.asyncio_compat import configure_asyncio_runtime
from ._utils import trace_headers
from .internal import internal_router
from .middleware import CacheControlMiddleware
from .routes import register_routes
from .websocket import ConnectionManager
from .ws_dispatch import (
    create_dispatch_control_handler,
    create_dispatch_message_handler,
)

__all__ = [
    "create_app",
    "main",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown hooks.

    ADR-019: The gateway no longer runs agent execution.  All
    graph compilation and ingest calls are dispatched to the worker
    process.  The lifespan sets up:
    1. Database (SQLAlchemy)
    2. Read-only checkpointer (for snapshot queries -- safe under WAL mode)
    3. EventAggregator (lightweight -- for local event relay only)
    4. ConnectionManager
    5. Telemetry
    6. httpx.AsyncClient for worker dispatch
    """
    logger.info("Starting gateway lifespan (ADR-019)")
    settings.validate_postgres_requirement()

    engine = await init_db(settings.database_url)
    logger.info(
        "Database initialised (%s, migrations applied)",
        settings.resolved_database_backend,
    )
    app.state.sqlite_fallback_diagnostics = build_sqlite_fallback_diagnostics()

    if settings.resolved_checkpoint_backend == "sqlite":
        backfill_teamstate_sdd_fields(settings.checkpoint_path)

    async with open_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer
        logger.info(
            "LangGraph checkpointer initialised (%s)",
            settings.resolved_checkpoint_backend,
        )

        if settings.repair_on_startup:
            session_factory = get_session_factory()
            async with session_factory() as db:
                app.state.repair_summary = await reconcile_threads_on_startup(
                    db, checkpointer, strategy=settings.repair_strategy
                )
                await db.commit()
        else:
            app.state.repair_summary = {
                "repair_backlog": 0,
                "paused_resumable": 0,
                "checkpoint_unavailable": 0,
            }

        aggregator = EventAggregator(telemetry=OTelAggregatorHook())
        app.state.aggregator = aggregator

        connection_manager = ConnectionManager(aggregator)
        app.state.connection_manager = connection_manager

        app.state.db_engine = engine

        configure_telemetry()
        logger.info("Telemetry configured")

        worker_client = httpx.AsyncClient(
            base_url=settings.worker_url,
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers=(
                {"Authorization": f"Bearer {settings.internal_token}"}
                if settings.internal_token is not None
                else None
            ),
        )
        app.state.worker_client = worker_client
        logger.info("Worker client configured: %s", settings.worker_url)

        worker_spawner = LazyWorkerSpawner(
            worker_url=settings.worker_url,
            worker_port=settings.worker_port,
            auto_spawn=settings.auto_spawn_worker,
        )
        app.state.worker_spawner = worker_spawner

        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=settings.cb_failure_threshold,
            recovery_timeout=settings.cb_recovery_timeout_seconds,
        )
        app.state.circuit_breaker = circuit_breaker

        worker_state = WorkerState()
        app.state.worker_state = worker_state
        watchdog = WorkerWatchdog(
            worker_spawner, circuit_breaker, worker_state, app.state
        )
        watchdog_task = asyncio.create_task(watchdog.run())

        msg_handler = create_dispatch_message_handler(
            worker_client,
            get_session_factory(),
            checkpointer,
            circuit_breaker,
            worker_spawner,
            connection_manager,
            app.state,
        )
        connection_manager.set_message_handler(msg_handler)

        ctrl_handler = create_dispatch_control_handler(
            worker_client,
            get_session_factory(),
            checkpointer,
            circuit_breaker,
            worker_spawner,
            app.state,
        )
        connection_manager.set_agent_control_handler(ctrl_handler)

        reconcile_task = asyncio.create_task(
            redispatch_reconciling_threads(
                worker_client,
                circuit_breaker,
                worker_spawner,
                app.state,
                trace_headers_fn=trace_headers,
            )
        )

        logger.info("Gateway startup complete")

        yield

        reconcile_task.cancel()
        await asyncio.gather(reconcile_task, return_exceptions=True)

        logger.info("Shutting down gateway")

        watchdog_task.cancel()
        await asyncio.gather(watchdog_task, return_exceptions=True)

        await worker_spawner.shutdown()
        await worker_client.aclose()
        await connection_manager.shutdown()
        await aggregator.shutdown()
        await close_db()

        logger.info("Gateway shutdown complete")


def main() -> None:
    """Launch the vaultspec-a2a server.

    Entry point for the ``vaultspec`` CLI command defined in
    ``[project.scripts]`` (ADR-015).
    """
    configure_asyncio_runtime()
    uvicorn.run(
        "vaultspec_a2a.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
        loop="auto",
    )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        A fully configured ``FastAPI`` instance ready for ``uvicorn.run()``.
    """
    app = FastAPI(
        title="Vaultspec A2A Orchestrator",
        version="0.1.0",
        lifespan=_lifespan,
    )

    cors_origins: list[str] = list(settings.cors_allowed_origins)
    app.add_middleware(
        cast("Any", CORSMiddleware),
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(cast("Any", TelemetryMiddleware))
    app.add_middleware(cast("Any", CacheControlMiddleware))

    register_routes(app)
    app.include_router(internal_router)

    @app.get("/health")
    async def health_endpoint() -> dict[str, object]:
        """Top-level liveness check for external probes.

        `/health` stays green when the gateway process is alive. Aggregate
        dependency readiness is exposed separately via `/api/health`.
        """
        shared = assemble_health_status(app_state=app.state)
        ready = not (
            shared["circuit_breaker"] == "open"
            or shared["worker_status"] in {"down", "restarting"}
            or (shared["worker_spawned"] and not shared["worker_connected"])
        )
        return {
            "status": "ok",
            "service": "gateway",
            "ready": ready,
            **shared,
            "production_certifying": (
                settings.resolved_database_backend == "postgres"
                and settings.resolved_checkpoint_backend == "postgres"
            ),
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for multiplexed real-time events."""
        cm: ConnectionManager = app.state.connection_manager
        client_id = await cm.connect(websocket)
        await cm.listen(client_id)

    if settings.ui_build_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(settings.ui_build_dir), html=True),
            name="ui",
        )
        logger.info("Mounted React SPA from %s", settings.ui_build_dir)
    else:
        logger.warning(
            "SPA build not found at %s -- UI will not be served",
            settings.ui_build_dir,
        )

    return app


if __name__ == "__main__":
    main()
