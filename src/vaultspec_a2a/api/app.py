"""FastAPI application factory -- the gateway entry point.

Creates the ASGI application with:
- Lifespan management (init/close DB, EventAggregator, telemetry)
- CORS middleware (permissive in dev)
- REST router from per-resource route modules
- Internal router from ``internal.py`` (worker relay)
- WebSocket route via ``ConnectionManager``

The gateway NO LONGER runs agent execution locally.  All graph
compilation and ``aggregator.ingest()`` calls are dispatched to the
worker process via HTTP POST to ``/dispatch`` (service separation).
"""

import asyncio  # Gateway uses asyncio directly — no structured concurrency needed.
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import metrics, trace
from starlette.websockets import WebSocket

from ..authoring import resolve_engine
from ..control.circuit_breaker import WorkerCircuitBreaker
from ..control.config import settings
from ..control.dispatch import redispatch_reconciling_threads
from ..control.health import assemble_health_status, build_sqlite_fallback_diagnostics
from ..control.verdict_subscriber import VerdictSubscriber
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
from ..domain_config import domain_config
from ..lifecycle.discovery import (
    HEARTBEAT_REFRESH_SECONDS,
    another_resident_is_live,
    remove_service_json_if_owned,
    service_json_path,
    write_service_json,
)
from ..lifecycle.registration import (
    deregister_serve,
    refresh_registration,
    register_serve,
)
from ..streaming.aggregator import EventAggregator
from ..telemetry import TelemetryMiddleware, configure_telemetry
from ..telemetry.aggregator_hook import OTelAggregatorHook
from ..utils.asyncio_compat import configure_asyncio_runtime
from ._utils import trace_headers
from .internal import internal_router
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


async def _discovery_heartbeat(
    path: Any,
    port: int,
    pid: int,
    service_token: str | None,
    serve_record: Any = None,
) -> None:
    """Refresh the machine-global discovery heartbeat every cadence.

    Also advances the dev-process registry record (when this is a band-port dev
    instance) on the same cadence, so a live dev gateway never drifts to STALE and
    gets reaped out from under itself. Non-fatal: a transient write failure is
    logged and retried on the next tick so a full disk or race never crashes the
    gateway.
    """
    while True:
        try:
            write_service_json(path, port=port, pid=pid, service_token=service_token)
            refresh_registration(serve_record)
        except OSError:
            logger.warning(
                "Failed to refresh service discovery heartbeat at %s",
                path,
                exc_info=True,
            )
        await asyncio.sleep(HEARTBEAT_REFRESH_SECONDS)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown hooks.

    The gateway no longer runs agent execution.  All
    graph compilation and ingest calls are dispatched to the worker
    process.  The lifespan sets up:
    1. Database (SQLAlchemy)
    2. Read-only checkpointer (for snapshot queries -- safe under WAL mode)
    3. EventAggregator (lightweight -- for local event relay only)
    4. ConnectionManager
    5. Telemetry
    6. httpx.AsyncClient for worker dispatch
    """
    logger.info("Starting gateway lifespan")
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

        # Publish and heartbeat the machine-global discovery file so the
        # engine can attach-never-own. A crashed/stale prior record is reclaimed;
        # a live resident is only warned about (the OS port bind is the real
        # single-instance guard) so tests and intentional restarts are not broken.
        discovery_path = service_json_path(settings.a2a_home)
        discovery_pid = os.getpid()
        if another_resident_is_live(settings.a2a_home):
            logger.warning(
                "A live resident gateway already holds %s; starting anyway "
                "(the port bind is the authoritative single-instance guard)",
                discovery_path,
            )
        write_service_json(
            discovery_path,
            port=settings.port,
            pid=discovery_pid,
            service_token=settings.internal_token,
        )
        # A gateway booted on a band port (gateway-dev)
        # self-registers so `procs` can enumerate/attach/reap it; a resident
        # gateway on its fixed out-of-band port registers nothing (returns None).
        serve_record = register_serve(
            "gateway-dev",
            settings.port,
            workspace=str(settings.workspace_root),
            command=["vaultspec-a2a", "serve", "--port", str(settings.port)],
        )
        # Master-bug guard: a band gateway-dev whose dispatch target is outside the
        # worker-dev band while a live band worker exists is mis-paired - refuse to
        # boot rather than silently dispatch into the owner's resident worker. When
        # no band worker exists the mismatch is a plausible dev intent, so warn only.
        if serve_record is not None:
            from ..lifecycle.pairing import (
                DispatchPairingStatus,
                verify_dispatch_pairing,
            )

            pairing_status, pairing_message = verify_dispatch_pairing(
                settings.worker_url
            )
            if pairing_status is DispatchPairingStatus.MISPAIRED:
                raise RuntimeError(pairing_message)
            if pairing_status is DispatchPairingStatus.UNPAIRED:
                logger.warning("Dispatch pairing: %s", pairing_message)
                app.state.dispatch_pairing_warning = pairing_message
        discovery_task = asyncio.create_task(
            _discovery_heartbeat(
                discovery_path,
                settings.port,
                discovery_pid,
                settings.internal_token,
                serve_record,
            )
        )
        logger.info("Service discovery published at %s", discovery_path)

        verdict_subscriber_task: asyncio.Task[None] | None = None
        if settings.authoring_subscriber_enabled:
            verdict_subscriber = VerdictSubscriber(
                session_factory=get_session_factory(),
                checkpointer=checkpointer,
                worker_client=worker_client,
                circuit_breaker=circuit_breaker,
                worker_spawner=worker_spawner,
                endpoint_provider=resolve_engine,
                recursion_limit=domain_config.graph_recursion_limit,
                trace_headers_fn=trace_headers,
                poll_interval_seconds=(
                    settings.authoring_subscriber_poll_interval_seconds
                ),
                reconnect_base_seconds=(
                    settings.authoring_subscriber_reconnect_base_seconds
                ),
                reconnect_max_seconds=(
                    settings.authoring_subscriber_reconnect_max_seconds
                ),
            )
            verdict_subscriber_task = asyncio.create_task(verdict_subscriber.run())
            logger.info("Authoring verdict subscriber enabled")

        logger.info("Gateway startup complete")

        yield

        if verdict_subscriber_task is not None:
            verdict_subscriber_task.cancel()
            await asyncio.gather(verdict_subscriber_task, return_exceptions=True)

        reconcile_task.cancel()
        await asyncio.gather(reconcile_task, return_exceptions=True)

        # Stop heartbeating and drop our own discovery record so the next
        # start sees Absent, not a stale record it must treat as Crashed.
        discovery_task.cancel()
        await asyncio.gather(discovery_task, return_exceptions=True)
        try:
            remove_service_json_if_owned(discovery_path, discovery_pid)
        except OSError:
            logger.warning(
                "Failed to remove discovery file %s on shutdown",
                discovery_path,
                exc_info=True,
            )
        # Drop our own record so `procs list` shows the
        # gateway gone, not a stale orphan the next reap must collect.
        deregister_serve(serve_record)

        logger.info("Shutting down gateway")

        watchdog_task.cancel()
        await asyncio.gather(watchdog_task, return_exceptions=True)

        await worker_spawner.shutdown()
        await worker_client.aclose()
        await connection_manager.shutdown()
        await aggregator.shutdown()
        await close_db()

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            await asyncio.to_thread(provider.shutdown)  # ty: ignore[invalid-argument-type]
        meter_provider = metrics.get_meter_provider()
        if hasattr(meter_provider, "shutdown"):
            await asyncio.to_thread(meter_provider.shutdown)  # ty: ignore[invalid-argument-type]

        logger.info("Gateway shutdown complete")


def main() -> None:
    """Launch the vaultspec-a2a server.

    Entry point for the ``vaultspec`` CLI command defined in
    ``[project.scripts]``.
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


def create_app(
    lifespan: Any | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        lifespan: Optional lifespan override for testing. When ``None``
            the production ``_lifespan`` is used.

    Returns:
        A fully configured ``FastAPI`` instance ready for ``uvicorn.run()``.
    """
    app = FastAPI(
        title="Vaultspec A2A Orchestrator",
        version="0.1.0",
        lifespan=lifespan or _lifespan,
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
            # The ungated health endpoint reports the live pid so a
            # lifecycle caller can confirm the discovery record's owner is alive.
            "pid": os.getpid(),
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

    return app


if __name__ == "__main__":
    main()
