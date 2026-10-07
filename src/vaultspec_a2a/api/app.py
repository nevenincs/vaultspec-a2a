"""FastAPI application factory -- the gateway entry point.

Creates the ASGI application with:
- Lifespan management (init/close DB, EventAggregator, telemetry)
- REST router from per-resource route modules
- Internal router from ``internal.py`` (worker relay)

The gateway NO LONGER runs agent execution locally.  All graph
compilation and ``aggregator.ingest()`` calls are dispatched to the
worker process via HTTP POST to ``/dispatch`` (service separation).
"""

import asyncio  # Gateway uses asyncio directly — no structured concurrency needed.
import logging
import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
from opentelemetry.sdk.trace import TracerProvider as SdkTracerProvider
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ..authoring import resolve_engine
from ..control._verdict_subscriber_config import VerdictSubscriberConfig
from ..control._worker_health import (
    WorkerLiveness,
    WorkerState,
    _internal_auth_headers,
)
from ..control.circuit_breaker import WorkerCircuitBreaker
from ..control.clarification_service import (
    ClarificationRuntime,
    redrive_clarification_actions,
)
from ..control.config import settings
from ..control.direct_control_recovery import redrive_direct_control_actions
from ..control.dispatch import redispatch_reconciling_threads
from ..control.event_handlers import CheckpointPruneRegistry
from ..control.health import (
    assemble_health_status,
    build_full_health,
    build_sqlite_fallback_diagnostics,
    probe_desktop_readiness,
)
from ..control.leased_dispatch import DispatchTransport
from ..control.settings_base import build_now
from ..control.verdict_subscriber import VerdictSubscriber
from ..control.worker_management import LazyWorkerSpawner, WorkerWatchdog
from ..database import (
    close_db,
    get_db,
    get_session_factory,
    init_db,
    seat_sqlite_posture,
)
from ..database.checkpoints import Checkpointer, open_checkpointer
from ..database.reconciliation import reconcile_threads_on_startup
from ..database.run_event_retention import sweep_replay_log_periodically
from ..domain_config import domain_config
from ..ipc.body_limit import BoundedHttpBodyMiddleware, gateway_body_limit
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
from ..lifecycle.registry import ProcRecord
from ..lifecycle.shutdown import ShutdownDeadline, ShutdownServer, finish_before
from ..providers.in_process_catalog import in_process_lanes
from ..streaming.aggregator import EventAggregator
from ..telemetry import TelemetryMiddleware, configure_telemetry, trace_headers
from ..telemetry.aggregator_hook import OTelAggregatorHook
from ..utils import (
    BearerVerdict,
    configure_logging,
    package_version,
    reconfigure_console_utf8,
)
from .auth import verify_attach_bearer
from .internal import internal_router
from .routes import register_routes
from .schemas.gateway_readiness import LivenessResponse

_RECOVERY_POLL_SECONDS = 2.0

__all__ = [
    "create_app",
    "main",
]

logger = logging.getLogger(__name__)

# Bound on the shutdown drain: how long the gateway waits, after closing
# admission, for in-flight runs to reach a terminal outcome and release their
# admission. Bounded rather than open-ended because a run whose worker died
# emitting nothing never releases itself; the teardown that follows cancels and
# reaps what is left.
_DRAIN_QUIESCENCE_TIMEOUT_SECONDS = 5.0

# Floor on the prune phase, kept even when the shared shutdown budget is
# already spent. Skipping the wait does not stop an in-flight prune: it leaves
# it deleting through a checkpointer the lines below then close under it. The
# prunes themselves are each bounded by the checkpoint read budget, so the
# floor is a short wait for work that is already ending.
_PRUNE_SETTLE_MINIMUM_SECONDS = 2.0

# The health probe's database dependency, bound once at module scope. The
# session is created lazily per request and opens no connection unless the
# readiness probe actually queries, so the armed profile's liveness answer
# still costs nothing.
_HEALTH_DB: Any = Depends(get_db)

# The runtime singletons the readiness probe needs in order to probe at all.
_HEALTH_PROBE_SINGLETONS = ("worker_client", "circuit_breaker", "worker_spawner")


async def _bounded_request_validation_error(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Return typed validation locations without reflecting rejected values."""
    if not isinstance(exc, RequestValidationError):
        raise exc
    errors = [
        {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


async def _unarmed_health_aggregate(app: FastAPI, db: AsyncSession) -> dict[str, Any]:
    """Return the probing readiness aggregate, or a degraded body if it cannot probe.

    A health surface must keep answering precisely when the process is unwell.
    The probe needs the worker client, circuit breaker and spawner, and any of
    them can be absent - before the lifespan has seated them, or after a
    lifespan that failed partway. Reaching for them unguarded would turn the one
    endpoint an external prober relies on into a 500, which reads to that prober
    as "unreachable" rather than "unhealthy" and hides the very condition it
    exists to report. So a missing singleton degrades the body and names itself.
    """
    missing = [
        name
        for name in _HEALTH_PROBE_SINGLETONS
        if getattr(app.state, name, None) is None
    ]
    if missing:
        return {
            "status": "degraded",
            "checks": {
                "gateway": {
                    "status": "error",
                    "detail": f"runtime not initialised: {', '.join(missing)}",
                }
            },
            **assemble_health_status(app_state=app.state),
        }
    return await build_full_health(
        db=db,
        transport=DispatchTransport(
            worker_client=app.state.worker_client,
            circuit_breaker=app.state.circuit_breaker,
            worker_spawner=app.state.worker_spawner,
        ),
        app_state=app.state,
    )


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


@dataclass(frozen=True, slots=True)
class _DesktopDiscoveryHeartbeatConfig:
    path: Any
    generation: str
    port: int
    owner: str
    credential_reference: str | None
    pid: int


async def _desktop_discovery_heartbeat(
    config: _DesktopDiscoveryHeartbeatConfig,
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
                config.path,
                generation=config.generation,
                port=config.port,
                owner=config.owner,
                credential_reference=config.credential_reference,
                pid=config.pid,
            )
        except OSError:
            logger.warning(
                "Failed to refresh desktop discovery heartbeat at %s",
                config.path,
                exc_info=True,
            )
        await asyncio.sleep(HEARTBEAT_REFRESH_SECONDS)


def _load_desktop_credentials(app: FastAPI) -> None:
    """Load the armed desktop credential planes into the application state.

    The attach-control credential and the receipt-bound ownership capability are
    read from their dashboard-created owner-restricted files; the worker
    interprocess-communication secret is minted per boot and seated on the
    application state, replacing the configured internal token there, so
    gateway-worker traffic authenticates with it. A missing or malformed dashboard
    file fails the gateway closed rather than booting an unauthenticated desktop
    surface.
    """
    from ..desktop.credentials import (
        create_worker_ipc_credential,
        load_attach_credential,
        load_ownership_capability,
    )

    references = settings.desktop_credential_paths
    if references is None:
        return
    credentials_dir = settings.prepare_state_dir(references.credentials_dir)
    app.state.v1_service_token = load_attach_credential(credentials_dir)
    app.state.lifecycle_capability = load_ownership_capability(credentials_dir)
    app.state.internal_token = create_worker_ipc_credential(credentials_dir)


def _http_attach_authorized(request: Request, app: FastAPI) -> bool:
    """Return whether an HTTP request presents a valid attach credential.

    The liveness surface answers every caller, but only a caller that proves the
    attach credential is disclosed the readiness projection, so the liveness
    boundary cannot weaken the attach gate. It cannot drift from it either: the
    rule is the one the refusing gate applies, asked here and mapped onto this
    surface's own answer, which is a silent ``False`` rather than a status code
    because this endpoint discloses less instead of refusing. Corrupted runtime
    state and a bad credential therefore collapse to the same non-disclosure,
    which is the whole difference between the two callers.
    """
    verdict = verify_attach_bearer(
        request.headers.get("authorization"),
        expected=getattr(app.state, "v1_service_token", None),
    )
    return verdict is BearerVerdict.OK


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------


async def _initialize_gateway_database(app: FastAPI, *, armed: bool) -> AsyncEngine:
    engine = await init_db(settings.database_url, apply_migrations=not armed)
    if armed:
        # Desktop boot validates the seated stores without migrating them.
        from ..database.compatibility import validate_desktop_schema

        await validate_desktop_schema(
            database_url=settings.database_url,
            checkpoint_path=settings.checkpoint_path,
        )
        await seat_sqlite_posture(engine)
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
    return engine


def _start_gateway_discovery(
    app: FastAPI,
) -> tuple[Path, int, ProcRecord | None, asyncio.Task[None]]:
    discovery_path = service_json_path(settings.a2a_home)
    discovery_pid = os.getpid()
    armed = settings.desktop_profile_armed
    desktop_generation: str | None = None
    desktop_owner: str | None = None
    desktop_credential_reference: str | None = None
    if armed:
        # The desktop record names the protected credential path, not its bearer.
        from ..lifecycle.singleton import active_singleton, default_owner

        singleton = active_singleton()
        desktop_owner = singleton.owner if singleton is not None else default_owner()
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

    # Check pairing after publication and before registration, as on the
    # original boot path, so a refusal leaves no dev registry record.
    from ..lifecycle.pairing import DispatchPairingStatus, verify_dispatch_pairing

    pairing_status, pairing_message = verify_dispatch_pairing(
        settings.worker_url, settings.port
    )
    if pairing_status is DispatchPairingStatus.MISPAIRED:
        raise RuntimeError(pairing_message)
    if pairing_status is DispatchPairingStatus.UNPAIRED:
        logger.warning("Dispatch pairing: %s", pairing_message)
        app.state.dispatch_pairing_warning = pairing_message

    serve_record = register_serve(
        "gateway-dev",
        settings.port,
        workspace=""
        if settings.workspace_root is None
        else str(settings.workspace_root),
        command=["vaultspec-a2a", "serve", "--port", str(settings.port)],
    )
    if armed:
        discovery_task = asyncio.create_task(
            _desktop_discovery_heartbeat(
                _DesktopDiscoveryHeartbeatConfig(
                    path=discovery_path,
                    generation=cast("str", desktop_generation),
                    port=settings.port,
                    owner=cast("str", desktop_owner),
                    credential_reference=desktop_credential_reference,
                    pid=discovery_pid,
                )
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
    return discovery_path, discovery_pid, serve_record, discovery_task


async def _settle_checkpoint_prunes(app: FastAPI, deadline: ShutdownDeadline) -> None:
    """Wait for this app's in-flight checkpoint prunes, budget spent or not.

    Only the prunes this app started: another app in the same process owns its
    own, and waiting for those here would hold this shutdown open on a store
    this app does not close.
    """
    prunes = getattr(app.state, "checkpoint_prunes", None)
    if prunes is None:
        return
    await finish_before(
        prunes.settle(),
        deadline,
        phase="checkpoint prunes",
        minimum=_PRUNE_SETTLE_MINIMUM_SECONDS,
    )


async def _shutdown_observability(deadline: ShutdownDeadline) -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, SdkTracerProvider):
        await finish_before(
            asyncio.to_thread(provider.shutdown), deadline, phase="trace provider"
        )
    meter_provider = metrics.get_meter_provider()
    if isinstance(meter_provider, SdkMeterProvider):
        await finish_before(
            asyncio.to_thread(meter_provider.shutdown),
            deadline,
            phase="meter provider",
        )


_WorkerShutdownResources = tuple[httpx.AsyncClient, LazyWorkerSpawner, EventAggregator]
_GatewayShutdownTasks = tuple[
    asyncio.Task[None],
    asyncio.Task[None],
    asyncio.Task[None] | None,
    asyncio.Task[None] | None,
]
_DiscoveryRuntime = tuple[Path, int, ProcRecord | None, asyncio.Task[None]]


async def _shutdown_gateway(
    app: FastAPI,
    workers: _WorkerShutdownResources,
    tasks: _GatewayShutdownTasks,
    discovery: _DiscoveryRuntime,
) -> None:
    worker_client, worker_spawner, aggregator = workers
    (
        watchdog_task,
        reconcile_task,
        verdict_subscriber_task,
        replay_retention_task,
    ) = tasks
    discovery_path, discovery_pid, serve_record, discovery_task = discovery
    # Close run admission first so the gateway admits no new run while it
    # drains and reaps its owned worker and run descendants below, then wait
    # a bounded interval for the runs already in flight to reach a terminal
    # outcome and release themselves. The wait returns immediately when
    # nothing is active - the common case - and a non-quiescent result names
    # how many runs the teardown below must cancel and reap, which is the
    # designed escape for a worker that died emitting nothing.
    from .routes.gateway import admission_gate

    deadline = getattr(app.state, "shutdown_deadline", None)
    if deadline is None:
        deadline = ShutdownDeadline.start(settings.shutdown_total_timeout_seconds)
        app.state.shutdown_deadline = deadline
    gate = admission_gate(app)
    await gate.close_admission()
    drain_budget = min(
        _DRAIN_QUIESCENCE_TIMEOUT_SECONDS,
        deadline.remaining(reserve=5.0),
    )
    drained, drain_result = await finish_before(
        gate.wait_quiescent(drain_budget),
        deadline,
        phase="active-run drain",
        reserve=5.0,
    )
    if drained and drain_result is not None and not drain_result.quiescent:
        logger.warning(
            "Gateway drain did not quiesce in %.1fs; %d run(s) still active "
            "and left to shutdown cancellation and reaping",
            drain_result.waited_seconds,
            drain_result.active_runs,
        )

    if verdict_subscriber_task is not None:
        verdict_subscriber_task.cancel()
        await finish_before(
            asyncio.gather(verdict_subscriber_task, return_exceptions=True),
            deadline,
            phase="verdict subscriber",
            reserve=4.0,
        )

    if replay_retention_task is not None:
        # Cancelled rather than drained: a sweep in flight deletes rows the
        # next start would delete anyway, so there is nothing here worth
        # holding a shutdown open for.
        replay_retention_task.cancel()
        await finish_before(
            asyncio.gather(replay_retention_task, return_exceptions=True),
            deadline,
            phase="replay retention",
            reserve=4.0,
        )

    reconcile_task.cancel()
    await finish_before(
        asyncio.gather(reconcile_task, return_exceptions=True),
        deadline,
        phase="reconciliation task",
        reserve=4.0,
    )

    # Stop heartbeating and drop our own discovery record so the next
    # start sees Absent, not a stale record it must treat as Crashed.
    discovery_task.cancel()
    await finish_before(
        asyncio.gather(discovery_task, return_exceptions=True),
        deadline,
        phase="discovery heartbeat",
        reserve=4.0,
    )
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
    await finish_before(
        asyncio.gather(watchdog_task, return_exceptions=True),
        deadline,
        phase="worker watchdog",
        reserve=4.0,
    )

    await finish_before(
        worker_spawner.shutdown(deadline=deadline),
        deadline,
        phase="owned worker tree",
    )
    await finish_before(worker_client.aclose(), deadline, phase="worker HTTP client")
    await finish_before(aggregator.shutdown(), deadline, phase="event aggregator")
    await _settle_checkpoint_prunes(app, deadline)
    await finish_before(close_db(), deadline, phase="database")

    await _shutdown_observability(deadline)

    logger.info("Gateway shutdown complete")


def _start_worker_runtime(
    app: FastAPI,
) -> tuple[
    httpx.AsyncClient,
    LazyWorkerSpawner,
    WorkerCircuitBreaker,
    WorkerLiveness,
    asyncio.Task[None],
]:
    internal_token = app.state.internal_token
    worker_client = httpx.AsyncClient(
        base_url=settings.worker_url,
        timeout=httpx.Timeout(30.0, connect=5.0),
        headers=_internal_auth_headers(internal_token),
    )
    app.state.worker_client = worker_client
    logger.info("Worker client configured: %s", settings.worker_url)

    worker_spawner = LazyWorkerSpawner(
        worker_url=settings.worker_url,
        worker_port=settings.worker_port,
        auto_spawn=settings.auto_spawn_worker,
        internal_token=internal_token,
    )
    app.state.worker_spawner = worker_spawner

    circuit_breaker = WorkerCircuitBreaker(
        failure_threshold=settings.cb_failure_threshold,
        recovery_timeout=settings.cb_recovery_timeout_seconds,
    )
    app.state.circuit_breaker = circuit_breaker

    worker_state = WorkerState()
    app.state.worker_state = worker_state

    liveness = WorkerLiveness()
    app.state.worker_liveness = liveness

    watchdog = WorkerWatchdog(worker_spawner, circuit_breaker, worker_state, app.state)
    watchdog_task = asyncio.create_task(watchdog.run())
    return worker_client, worker_spawner, circuit_breaker, liveness, watchdog_task


async def _reconcile_gateway_startup(app: FastAPI, checkpointer: Checkpointer) -> None:
    session_factory = get_session_factory()
    async with session_factory() as db:
        app.state.repair_summary = await reconcile_threads_on_startup(db, checkpointer)
        await db.commit()


def _start_verdict_subscriber(
    checkpointer: Checkpointer,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
) -> asyncio.Task[None] | None:
    if not settings.authoring_subscriber_enabled:
        return None
    verdict_subscriber = VerdictSubscriber(
        VerdictSubscriberConfig(
            session_factory=get_session_factory(),
            checkpointer=checkpointer,
            worker_client=worker_client,
            circuit_breaker=circuit_breaker,
            worker_spawner=worker_spawner,
            endpoint_provider=resolve_engine,
            trace_headers_fn=trace_headers,
            poll_interval_seconds=settings.authoring_subscriber_poll_interval_seconds,
            reconnect_base_seconds=settings.authoring_subscriber_reconnect_base_seconds,
            reconnect_max_seconds=settings.authoring_subscriber_reconnect_max_seconds,
        )
    )
    task = asyncio.create_task(verdict_subscriber.run())
    logger.info("Authoring verdict subscriber enabled")
    return task


def _start_replay_retention() -> asyncio.Task[None] | None:
    """Start the replay log's own age sweep, or none when nothing is retained.

    A background task rather than a step in any run's lifecycle, because the
    bound it enforces is about time rather than about a run ending: a run that
    settled while this gateway was down, and a run still going after a week,
    are both out of reach of anything triggered by a terminal. It writes to the
    application database only and touches no checkpoint.
    """
    if not settings.stream_replay_enabled:
        return None
    task = asyncio.create_task(
        sweep_replay_log_periodically(
            get_session_factory(),
            retention_hours=settings.stream_replay_retention_hours,
        )
    )
    logger.info(
        "Replay retention sweeping at %.1f hours",
        settings.stream_replay_retention_hours,
    )
    return task


_GatewayRecoveryRuntime = tuple[
    httpx.AsyncClient, WorkerCircuitBreaker, LazyWorkerSpawner, WorkerLiveness
]


async def _direct_recovery_pass(
    app: FastAPI,
    worker_client: httpx.AsyncClient,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: LazyWorkerSpawner,
) -> None:
    try:
        await redrive_direct_control_actions(
            get_session_factory(),
            worker_client=worker_client,
            circuit_breaker=circuit_breaker,
            worker_spawner=worker_spawner,
            trace_headers=trace_headers(),
        )
        app.state.direct_control_recovery_error = None
    except asyncio.CancelledError:
        raise
    except Exception:
        app.state.direct_control_recovery_error = "recovery_pass_failed"
        logger.exception("Direct recovery pass failed; the owner will retry")


def _start_gateway_recovery(
    app: FastAPI,
    checkpointer: Checkpointer,
    runtime: _GatewayRecoveryRuntime,
) -> asyncio.Task[None]:
    worker_client, circuit_breaker, worker_spawner, liveness = runtime

    def record_worker_contact(timestamp: float) -> None:
        liveness.record_contact(when=timestamp)

    async def _redispatch_recovery() -> None:
        await _direct_recovery_pass(app, worker_client, circuit_breaker, worker_spawner)
        try:
            await redispatch_reconciling_threads(
                worker_client,
                circuit_breaker,
                worker_spawner,
                record_worker_contact=record_worker_contact,
                trace_headers_fn=trace_headers,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Startup reconciliation dispatch failed")
        try:
            await redrive_clarification_actions(
                get_session_factory(),
                runtime=ClarificationRuntime(
                    checkpointer,
                    DispatchTransport(
                        worker_client=worker_client,
                        circuit_breaker=circuit_breaker,
                        worker_spawner=worker_spawner,
                        trace_headers=trace_headers(),
                    ),
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Clarification recovery pass failed")
        while True:
            await asyncio.sleep(_RECOVERY_POLL_SECONDS)
            await _direct_recovery_pass(
                app, worker_client, circuit_breaker, worker_spawner
            )

    reconcile_task = asyncio.create_task(_redispatch_recovery())
    return reconcile_task


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown hooks.

    The gateway no longer runs agent execution.  All
    graph compilation and ingest calls are dispatched to the worker
    process.  The lifespan sets up:
    1. Database (SQLAlchemy)
    2. Read-only checkpointer (for snapshot queries -- safe under WAL mode)
    3. EventAggregator (lightweight -- for local event relay only)
    4. Telemetry
    5. httpx.AsyncClient for worker dispatch
    """
    logger.info("Starting gateway lifespan")
    settings.validate_postgres_requirement()
    # A lane plugin this process cannot honour refuses the gateway here, at
    # startup, rather than at the first catalog read that resolves the lanes.
    in_process_lanes()

    armed = settings.desktop_profile_armed
    engine = await _initialize_gateway_database(app, armed=armed)

    async with open_checkpointer() as checkpointer:
        app.state.checkpointer = checkpointer
        # Seated beside the store the prunes delete through, and inside its
        # context, so the shutdown below waits for this app's own prunes while
        # the checkpointer they hold is still open.
        app.state.checkpoint_prunes = CheckpointPruneRegistry()
        logger.info(
            "LangGraph checkpointer initialised (%s)",
            settings.resolved_checkpoint_backend,
        )

        await _reconcile_gateway_startup(app, checkpointer)

        aggregator = EventAggregator(telemetry=OTelAggregatorHook())
        app.state.aggregator = aggregator

        app.state.db_engine = engine

        configure_telemetry()
        logger.info("Telemetry configured")

        (
            worker_client,
            worker_spawner,
            circuit_breaker,
            liveness,
            watchdog_task,
        ) = _start_worker_runtime(app)

        reconcile_task = _start_gateway_recovery(
            app,
            checkpointer,
            (worker_client, circuit_breaker, worker_spawner, liveness),
        )
        discovery_path, discovery_pid, serve_record, discovery_task = (
            _start_gateway_discovery(app)
        )

        verdict_subscriber_task = _start_verdict_subscriber(
            checkpointer, worker_client, circuit_breaker, worker_spawner
        )
        replay_retention_task = _start_replay_retention()

        logger.info("Gateway startup complete")

        yield

        await _shutdown_gateway(
            app,
            (worker_client, worker_spawner, aggregator),
            (
                watchdog_task,
                reconcile_task,
                verdict_subscriber_task,
                replay_retention_task,
            ),
            (discovery_path, discovery_pid, serve_record, discovery_task),
        )


def _bind_server_shutdown_owner(app: FastAPI, server: uvicorn.Server) -> None:
    """Bind the served app to the cooperative transition of its Uvicorn owner."""

    def request_shutdown() -> None:
        server.should_exit = True

    app.state.request_server_shutdown = request_shutdown


def main() -> None:
    """Launch the vaultspec-a2a gateway.

    Invoked by the ``serve`` subcommand of the ``vaultspec-a2a`` script
    (``cli.main:main``) defined in ``[project.scripts]``.
    """
    reconfigure_console_utf8()
    configure_logging("service", settings=settings, service_name="gateway")
    # Built with the infrastructure settings, so a refused domain value is
    # reported by the process that starts the service, not by the first reader.
    build_now(domain_config)
    app = create_app()
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.value,
        access_log=settings.access_log,
        loop="auto",
        timeout_graceful_shutdown=settings.shutdown_stream_grace_seconds,
    )
    server = ShutdownServer(
        config,
        app=app,
        total_seconds=settings.shutdown_total_timeout_seconds,
    )
    _bind_server_shutdown_owner(app, server)
    server.run()


def create_app(lifespan: Any | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    The application snapshots a configured gateway token or generates a
    per-process token; corrupted runtime state with no token fails closed on
    every ``/v1`` request while ``/health`` remains available.

    Args:
        lifespan: Optional lifespan override for testing. When ``None``
            the production ``_lifespan`` is used.

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
    # The worker-IPC secret every internal request is verified against and every
    # worker-bound request presents. Seated here, never written onto the settings,
    # so the one value the gateway holds is the one it authenticates with.
    app.state.internal_token = settings.internal_token
    app.add_exception_handler(RequestValidationError, _bounded_request_validation_error)
    # The receipt-bound lifecycle ownership capability is only present under the
    # armed desktop profile; unarmed profiles never carry one.
    app.state.lifecycle_capability = None
    if settings.desktop_profile_armed:
        # Armed desktop: replace the generated attach token with the
        # dashboard-created attach credential, load the ownership capability, and
        # replace the configured worker IPC secret with one minted for this boot.
        # Fails closed if a dashboard file is absent.
        _load_desktop_credentials(app)

    app.add_middleware(
        cast("Any", BoundedHttpBodyMiddleware), limit=gateway_body_limit(settings)
    )
    app.add_middleware(cast("Any", TelemetryMiddleware))

    register_routes(app)
    app.include_router(internal_router)

    @app.get("/health")
    async def health_endpoint(
        request: Request,
        db: AsyncSession = _HEALTH_DB,
    ) -> dict[str, object]:
        """Top-level health check: the one probe surface for external callers.

        Under the armed desktop profile the unauthenticated boundary discloses
        only the minimal liveness fact - no process identity, product identity, or
        product state - while an attach-authenticated caller additionally receives
        the readiness projection from the single readiness authority, computed
        over a live database probe. Only the authenticated branch probes: the
        unauthenticated answer stays a constant so it cannot be used to measure
        the gateway's dependencies.

        Both profiles PROBE rather than read off app state - the DB here and, on
        Compose and development, the checkpointer and worker as well - because a
        healthcheck that only reports what the process believes about itself
        cannot notice a dependency that has gone away.
        """
        if settings.desktop_profile_armed:
            if _http_attach_authorized(request, app):
                readiness = await probe_desktop_readiness(app_state=app.state, db=db)
                return readiness.model_dump(mode="json")
            return LivenessResponse().model_dump(mode="json")
        aggregate = await _unarmed_health_aggregate(app, db)
        # ``ready`` answers a NARROWER question than the aggregate ``status``,
        # and both are kept because they are not the same fact. The aggregate is
        # the probe verdict across every dependency; ``ready`` is the local
        # question "is this gateway's own worker attached and usable", which the
        # probes cannot answer, because the heartbeat-push freshness gate
        # (worker_connected) is authoritative only for a worker this gateway
        # OWNS (holds the process handle). An adopted / externally-managed
        # worker (spawned but no owned pid) legitimately may not push heartbeats
        # this gateway accepts; its liveness is the probe-driven worker_status,
        # which the watchdog reconciles every tick. Gating readiness on
        # worker_connected for it would report a healthy adopted worker as
        # not-ready.
        worker_owned = (
            aggregate["worker_spawned"] and aggregate["worker_pid"] is not None
        )
        ready = not (
            aggregate["circuit_breaker"] == "open"
            or aggregate["worker_status"] in {"down", "restarting"}
            or (worker_owned and not aggregate["worker_connected"])
        )
        return {
            "service": "gateway",
            **aggregate,
            "ready": ready,
            # The ungated health endpoint reports the live pid so a
            # lifecycle caller can confirm the discovery record's owner is alive.
            "pid": os.getpid(),
            "production_certifying": (
                settings.resolved_database_backend == "postgres"
                and settings.resolved_checkpoint_backend == "postgres"
            ),
        }

    return app
