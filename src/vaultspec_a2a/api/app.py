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
import hmac
import logging
import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import metrics, trace
from starlette.websockets import WebSocket

from ..authoring import resolve_engine
from ..control.circuit_breaker import WorkerCircuitBreaker
from ..control.config import settings
from ..control.dispatch import redispatch_reconciling_threads
from ..control.health import (
    assemble_desktop_readiness,
    assemble_health_status,
    build_sqlite_fallback_diagnostics,
)
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
    write_desktop_discovery,
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
from ..utils import configure_logging, package_version, reconfigure_console_utf8
from ..utils.asyncio_compat import configure_asyncio_runtime
from ._utils import trace_headers
from .internal import internal_router
from .routes import register_routes
from .schemas.gateway import LivenessResponse
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
            # Both writes are synchronous filesystem I/O (write_text + os.replace,
            # plus registry read/write); on a contended disk a single one can stall
            # the event loop long enough to drop an in-flight HTTP response. Offload
            # them so the heartbeat never blocks the gateway's request handling.
            await asyncio.to_thread(
                write_service_json,
                path,
                port=port,
                pid=pid,
                service_token=service_token,
            )
            await asyncio.to_thread(refresh_registration, serve_record)
        except OSError:
            logger.warning(
                "Failed to refresh service discovery heartbeat at %s",
                path,
                exc_info=True,
            )
        await asyncio.sleep(HEARTBEAT_REFRESH_SECONDS)


async def _desktop_discovery_heartbeat(
    path: Any,
    *,
    generation: str,
    port: int,
    owner: str,
    credential_reference: str | None,
    pid: int,
) -> None:
    """Refresh the versioned desktop discovery record every cadence.

    The desktop profile publishes the versioned, secret-free record rather than
    the Compose ``ServiceInfo`` record; this keeps its heartbeat fresh so a
    contender never reads a live gateway as stale. Non-fatal: a transient write
    failure is logged and retried on the next tick.
    """
    while True:
        try:
            await asyncio.to_thread(
                write_desktop_discovery,
                path,
                generation=generation,
                port=port,
                owner=owner,
                credential_reference=credential_reference,
                pid=pid,
            )
        except OSError:
            logger.warning(
                "Failed to refresh desktop discovery heartbeat at %s",
                path,
                exc_info=True,
            )
        await asyncio.sleep(HEARTBEAT_REFRESH_SECONDS)


def _load_desktop_credentials(app: FastAPI) -> None:
    """Load the armed desktop credential planes into the application state.

    The attach-control credential and the receipt-bound ownership capability are
    read from their dashboard-created owner-restricted files; the worker
    interprocess-communication secret is minted per boot and seated on the shared
    internal-token setting so gateway-worker traffic authenticates with it. A
    missing or malformed dashboard file fails the gateway closed rather than
    booting an unauthenticated desktop surface.
    """
    from ..desktop.credentials import (
        create_worker_ipc_credential,
        load_attach_credential,
        load_ownership_capability,
    )

    references = settings.desktop_credential_paths
    if references is None:
        return
    credentials_dir = references.credentials_dir
    app.state.v1_service_token = load_attach_credential(credentials_dir)
    app.state.lifecycle_capability = load_ownership_capability(credentials_dir)
    settings.internal_token = create_worker_ipc_credential(credentials_dir)


def _http_attach_authorized(request: Request, app: FastAPI) -> bool:
    """Return whether an HTTP request presents a valid attach credential.

    The liveness surface answers every caller, but only a caller that proves the
    attach credential in constant time is disclosed the readiness projection. This
    mirrors the WebSocket attach check exactly, so the liveness boundary cannot
    weaken the P08 attach gate: the explicit test-only bypass short-circuits for
    route-behaviour tests, and corrupted runtime state with no token discloses
    nothing.
    """
    if bool(getattr(app.state, "allow_unauthenticated_v1_for_testing", False)):
        return True
    expected = getattr(app.state, "v1_service_token", None)
    if not isinstance(expected, str) or not expected:
        return False
    supplied = request.headers.get("authorization", "").encode("utf-8")
    return hmac.compare_digest(supplied, f"Bearer {expected}".encode())


def _websocket_attach_authorized(websocket: WebSocket, app: FastAPI) -> bool:
    """Return whether a desktop event WebSocket presents a valid attach credential.

    Constant-time comparison against the loaded attach credential; the explicit
    test-only bypass short-circuits for route-behaviour tests. A missing runtime
    credential is corrupted state and refuses the connection.
    """
    if bool(getattr(app.state, "allow_unauthenticated_v1_for_testing", False)):
        return True
    expected = getattr(app.state, "v1_service_token", None)
    if not isinstance(expected, str) or not expected:
        return False
    supplied = websocket.headers.get("authorization", "").encode("utf-8")
    return hmac.compare_digest(supplied, f"Bearer {expected}".encode())


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

    armed = settings.desktop_profile_armed
    engine = await init_db(settings.database_url, apply_migrations=not armed)
    if armed:
        # Desktop profile: ordinary boot mutates no schema. Validate that the
        # seated stores are already compatible and fail loud otherwise; the
        # staged-generation migration entrypoint owns every mutation.
        from ..database.compatibility import validate_desktop_schema

        await validate_desktop_schema(
            database_url=settings.database_url,
            checkpoint_path=settings.checkpoint_path,
        )
        logger.info(
            "Desktop database schema validated (no migration performed, %s)",
            settings.resolved_database_backend,
        )
    else:
        logger.info(
            "Database initialised (%s, migrations applied)",
            settings.resolved_database_backend,
        )
    app.state.sqlite_fallback_diagnostics = build_sqlite_fallback_diagnostics()

    if not armed and settings.resolved_checkpoint_backend == "sqlite":
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

        # Deferred-reconciliation gate: ordinary armed desktop boot must not start
        # the worker. The worker starts only on the first authenticated execution
        # demand, which fires this event once its single-flight start reaches
        # readiness (see the dispatch demand path). Reconciliation of RECONCILING
        # threads then runs against the already-started worker. The Compose and
        # development profiles keep eager boot reconciliation: their worker is
        # either standalone (no auto-spawn) or foreground-spawned at boot.
        worker_demand_ready = asyncio.Event()
        app.state.worker_demand_ready = worker_demand_ready

        async def _deferred_reconcile() -> None:
            await worker_demand_ready.wait()
            await redispatch_reconciling_threads(
                worker_client,
                circuit_breaker,
                worker_spawner,
                app.state,
                trace_headers_fn=trace_headers,
            )

        if armed:
            # Hand the spawner the event it fires once the first demand-driven
            # single-flight worker start reaches readiness; the parked
            # reconciliation above then wakes.
            worker_spawner.demand_ready_event = worker_demand_ready
            reconcile_task = asyncio.create_task(_deferred_reconcile())
        else:
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
        armed = settings.desktop_profile_armed
        desktop_generation: str | None = None
        desktop_owner: str | None = None
        desktop_credential_reference: str | None = None
        if armed:
            # Desktop profile: publish the versioned, secret-free record keyed to
            # the runtime singleton this process already holds. The record names
            # only the ACL-protected attach-credential reference, never a bearer.
            from ..lifecycle.singleton import active_singleton, default_owner

            singleton = active_singleton()
            desktop_owner = (
                singleton.owner if singleton is not None else default_owner()
            )
            desktop_generation = package_version()
            references = settings.desktop_credential_paths
            desktop_credential_reference = (
                str(references.attach_path) if references is not None else None
            )
            write_desktop_discovery(
                discovery_path,
                generation=desktop_generation,
                port=settings.port,
                owner=desktop_owner,
                credential_reference=desktop_credential_reference,
                pid=discovery_pid,
            )
        else:
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
                service_token=app.state.v1_service_token,
            )
        # Master-bug guard (BEFORE registration so a refusal leaves zero residue): a
        # band gateway-dev whose dispatch target is outside the worker-dev band while
        # a live band worker exists is mis-paired - refuse to boot rather than
        # silently dispatch into the owner's resident worker. When no band worker
        # exists the mismatch is a plausible dev intent, so warn only.
        from ..lifecycle.pairing import (
            DispatchPairingStatus,
            verify_dispatch_pairing,
        )

        pairing_status, pairing_message = verify_dispatch_pairing(
            settings.worker_url, settings.port
        )
        if pairing_status is DispatchPairingStatus.MISPAIRED:
            raise RuntimeError(pairing_message)
        if pairing_status is DispatchPairingStatus.UNPAIRED:
            logger.warning("Dispatch pairing: %s", pairing_message)
            app.state.dispatch_pairing_warning = pairing_message

        # A gateway booted on a band port (gateway-dev)
        # self-registers so `procs` can enumerate/attach/reap it; a resident
        # gateway on its fixed out-of-band port registers nothing (returns None).
        serve_record = register_serve(
            "gateway-dev",
            settings.port,
            workspace=str(settings.workspace_root),
            command=["vaultspec-a2a", "serve", "--port", str(settings.port)],
        )
        if armed:
            discovery_task = asyncio.create_task(
                _desktop_discovery_heartbeat(
                    discovery_path,
                    generation=cast("str", desktop_generation),
                    port=settings.port,
                    owner=cast("str", desktop_owner),
                    credential_reference=desktop_credential_reference,
                    pid=discovery_pid,
                )
            )
        else:
            discovery_task = asyncio.create_task(
                _discovery_heartbeat(
                    discovery_path,
                    settings.port,
                    discovery_pid,
                    app.state.v1_service_token,
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

        # Close run admission first so the gateway admits no new run while it
        # drains and reaps its owned worker and run descendants below. Closing
        # does not wait for quiescence (that composes with terminal settlement);
        # it just refuses new admissions from this point on.
        from .routes.gateway import admission_gate

        await admission_gate(app).close_admission()

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
    reconfigure_console_utf8()
    configure_logging("service", service_name="gateway")
    configure_asyncio_runtime()
    uvicorn.run(
        "vaultspec_a2a.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.value,
        access_log=settings.access_log,
        loop="auto",
    )


def create_app(
    lifespan: Any | None = None,
    *,
    allow_unauthenticated_v1_for_testing: bool = False,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        lifespan: Optional lifespan override for testing. When ``None``
            the production ``_lifespan`` is used.
        allow_unauthenticated_v1_for_testing: Explicit test-only escape hatch
            for legacy route-behaviour tests. Production callers must leave it
            false. Production snapshots a configured gateway token or generates
            a per-process token; corrupted runtime state with no token fails
            closed on every ``/v1`` request while ``/health`` remains available.

    Returns:
        A fully configured ``FastAPI`` instance ready for ``uvicorn.run()``.
    """
    app = FastAPI(
        title="Vaultspec A2A Orchestrator",
        version=package_version(),
        lifespan=lifespan or _lifespan,
    )
    # The engine-facing credential is distinct from worker IPC by default. It is
    # immutable for this app generation, published only through the owner-restricted
    # handoff file, and never logged.
    app.state.v1_service_token = settings.gateway_service_token or secrets.token_hex(32)
    app.state.allow_unauthenticated_v1_for_testing = (
        allow_unauthenticated_v1_for_testing
    )
    # The receipt-bound lifecycle ownership capability is only present under the
    # armed desktop profile; unarmed profiles never carry one.
    app.state.lifecycle_capability = None
    if settings.desktop_profile_armed and not allow_unauthenticated_v1_for_testing:
        # Armed desktop: replace the generated attach token with the
        # dashboard-created attach credential, load the ownership capability, and
        # mint the worker IPC secret. Fails closed if a dashboard file is absent.
        _load_desktop_credentials(app)

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
    async def health_endpoint(request: Request) -> dict[str, object]:
        """Top-level liveness check for external probes.

        Under the armed desktop profile the unauthenticated boundary discloses
        only the minimal liveness fact - no process identity, product identity, or
        product state - while an attach-authenticated caller additionally receives
        the readiness projection from the single readiness authority. The Compose
        and development profiles retain the legacy aggregate liveness body their
        probes already consume; readiness there stays on `/api/health`.
        """
        if settings.desktop_profile_armed:
            if _http_attach_authorized(request, app):
                readiness = assemble_desktop_readiness(app_state=app.state)
                return readiness.model_dump(mode="json")
            return LivenessResponse().model_dump(mode="json")
        shared = assemble_health_status(app_state=app.state)
        # The heartbeat-push freshness gate (worker_connected) is authoritative only
        # for a worker this gateway OWNS (holds the process handle). An adopted /
        # externally-managed worker (spawned but no owned pid) legitimately may not
        # push heartbeats this gateway accepts; its liveness is the probe-driven
        # worker_status, which the watchdog reconciles every tick. Gating readiness on
        # worker_connected for it would report a healthy adopted worker as not-ready.
        worker_owned = shared["worker_spawned"] and shared["worker_pid"] is not None
        ready = not (
            shared["circuit_breaker"] == "open"
            or shared["worker_status"] in {"down", "restarting"}
            or (worker_owned and not shared["worker_connected"])
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
        """WebSocket endpoint for multiplexed real-time events.

        Desktop event streams carry product state, so the attach credential is
        required before the connection is accepted; an unauthenticated or
        unverifiable client is closed with a policy-violation code.
        """
        if not _websocket_attach_authorized(websocket, app):
            await websocket.close(code=1008, reason="Unauthorized")
            return
        cm: ConnectionManager = app.state.connection_manager
        client_id = await cm.connect(websocket)
        await cm.listen(client_id)

    return app


if __name__ == "__main__":
    main()
