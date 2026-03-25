"""FastAPI application factory -- the gateway entry point (ADR-019).

Creates the ASGI application with:
- Lifespan management (init/close DB, EventAggregator, telemetry)
- CORS middleware (permissive in dev)
- REST router from ``endpoints.py``
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
import json
import logging
import re
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from opentelemetry import propagate as _otel_propagate
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.websockets import WebSocket

from ..control.circuit_breaker import WorkerCircuitBreaker
from ..control.config import settings
from ..control.worker_management import (
    LazyWorkerSpawner,
    WorkerState,
    WorkerWatchdog,
)
from ..database.checkpoints import open_checkpointer
from ..database.crud import ThreadStatus, get_thread, list_threads, update_thread_status
from ..database.migrations import backfill_teamstate_sdd_fields
from ..database.reconciliation import reconcile_threads_on_startup
from ..database.session import (
    close_db,
    get_session_factory,
    init_db,
    inspect_sqlite_database,
)
from ..ipc.schemas import DispatchRequest
from ..streaming.aggregator import EventAggregator
from ..telemetry import TelemetryMiddleware, configure_telemetry
from ..telemetry.aggregator_hook import OTelAggregatorHook
from ..utils.asyncio_compat import configure_asyncio_runtime
from .endpoints import router
from .internal import internal_router
from .schemas.enums import AgentControlAction
from .websocket import ConnectionManager, WebSocketCommandRejectedError

__all__ = [
    "create_app",
    "main",
]

logger = logging.getLogger(__name__)


def _build_sqlite_fallback_diagnostics(
    *,
    database_backend: str | None = None,
    checkpoint_backend: str | None = None,
    database_path: Path | None = None,
    checkpoint_path: Path | None = None,
    busy_timeout_ms: int | None = None,
) -> dict[str, object] | None:
    """Build explicit diagnostics for the SQLite fallback path."""
    resolved_database_backend = database_backend or settings.resolved_database_backend
    resolved_checkpoint_backend = (
        checkpoint_backend or settings.resolved_checkpoint_backend
    )
    if (
        resolved_database_backend != "sqlite"
        and resolved_checkpoint_backend != "sqlite"
    ):
        return None

    diagnostics: dict[str, object] = {
        "active": True,
        "busy_timeout_ms": busy_timeout_ms or settings.sqlite_busy_timeout_ms,
        "production_certifying": False,
        "limitations": ["sqlite_fallback_not_production_certifying"],
    }
    if resolved_database_backend == "sqlite":
        diagnostics["database"] = inspect_sqlite_database(
            database_path or settings.database_path
        )
    if resolved_checkpoint_backend == "sqlite":
        diagnostics["checkpoint"] = inspect_sqlite_database(
            checkpoint_path or settings.checkpoint_path
        )
    return diagnostics


# React/Vite hashed immutable assets: /_app/immutable/** or /assets/**
_IMMUTABLE_PATTERN = re.compile(r"^/(_app/immutable|assets)/")
_CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
_CACHE_HTML = "no-cache"


class _CacheControlMiddleware(BaseHTTPMiddleware):
    """Set Cache-Control headers for static SPA assets (ADR-007 S5).

    - ``/_app/immutable/**`` or ``/assets/**`` (content-hashed JS/CSS): cache forever
    - HTML responses (``index.html``, SPA fallback): ``no-cache``
    """

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: RequestResponseEndpoint,
    ) -> StarletteResponse:
        response = await call_next(request)
        path = request.url.path
        if _IMMUTABLE_PATTERN.search(path):
            response.headers["Cache-Control"] = _CACHE_IMMUTABLE
        elif response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = _CACHE_HTML
        return response


# ---------------------------------------------------------------------------
# Dispatch handlers -- forward work to the worker process (ADR-019)
# ---------------------------------------------------------------------------


def _trace_headers() -> dict[str, str]:
    """Build W3C trace context headers for WS-path gateway-to-worker calls (TEL-03)."""
    carrier: dict[str, str] = {}
    _otel_propagate.inject(carrier)
    return carrier


async def _classify_missing_ws_thread(
    *,
    thread_id: str,
    session_factory: Any,
    checkpointer: Any,
) -> WebSocketCommandRejectedError:
    """Classify a missing-thread WebSocket command without assuming total absence."""
    from ..database.crud import get_thread_execution_state

    execution_state_present = False
    try:
        async with session_factory() as db:
            execution_state_present = (
                await get_thread_execution_state(db, thread_id)
            ) is not None
    except Exception:
        logger.warning(
            "Could not inspect execution-state projection for websocket thread %s",
            thread_id,
            exc_info=True,
        )

    checkpoint_present = False
    checkpoint_unverified = False
    try:
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = await asyncio.wait_for(
            checkpointer.aget_tuple(config),
            timeout=2.0,
        )
        checkpoint_present = checkpoint_tuple is not None
    except TimeoutError:
        checkpoint_unverified = True
    except Exception:
        logger.debug(
            "Could not verify checkpoint for missing thread %s",
            thread_id,
            exc_info=True,
        )
        checkpoint_unverified = True

    metadata = {
        "execution_state_present": execution_state_present,
        "checkpoint_present": checkpoint_present,
        "checkpoint_unverified": checkpoint_unverified,
    }
    if execution_state_present or checkpoint_present:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="THREAD_STATE_DRIFT",
            message=(
                "Thread is missing from the gateway database, but durable backend "
                "state still exists. Refresh thread state or trigger repair before "
                "sending follow-up commands."
            ),
            recoverable=True,
            metadata=metadata,
        )
    if checkpoint_unverified:
        return WebSocketCommandRejectedError(
            thread_id=thread_id,
            code="THREAD_STATE_UNVERIFIED",
            message=(
                "Thread is missing from the gateway database and checkpoint truth "
                "could not be verified. Retry after the backend is healthy."
            ),
            recoverable=True,
            metadata=metadata,
        )
    return WebSocketCommandRejectedError(
        thread_id=thread_id,
        code="THREAD_NOT_FOUND",
        message="Thread not found.",
        recoverable=True,
        metadata=metadata,
    )


async def _ws_mark_failed_and_broadcast(
    thread_id: str,
    session_factory: Any,
    connection_manager: Any,
    error_detail: str,
) -> None:
    """Mark a thread FAILED and broadcast a terminal WS event.

    Shared by WS dispatch handlers when the worker is unreachable.
    """
    try:
        async with session_factory() as db:
            await update_thread_status(db, thread_id, ThreadStatus.FAILED)
            await db.commit()
    except Exception:
        logger.warning(
            "Could not set thread %s to FAILED after WS dispatch error",
            thread_id,
            exc_info=True,
        )
    terminal_payload = {
        "event_type": "thread_terminal",
        "thread_id": thread_id,
        "status": "failed",
        "error_detail": error_detail,
    }
    try:
        await connection_manager.broadcast_to_thread(thread_id, terminal_payload)
    except Exception:
        logger.warning(
            "Could not broadcast terminal event for thread %s",
            thread_id,
            exc_info=True,
        )


def _create_dispatch_message_handler(
    worker_client: httpx.AsyncClient,
    session_factory: Any,
    checkpointer: Any,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: "LazyWorkerSpawner",
    connection_manager: Any,
    app_state: Any,
) -> Callable:
    """Create message handler that dispatches to the worker process.

    Replaces the old ``_create_message_handler`` which ran
    ``aggregator.ingest()`` locally.  Now sends an HTTP POST to the
    worker's ``/dispatch`` endpoint (ADR-019).

    Looks up the thread to forward ``team_preset`` and ``workspace_root``
    so the worker can recompile the correct graph (T26b).

    WS-G01: On dispatch failure, marks thread as FAILED in the DB and
    broadcasts a ``thread_terminal`` event so UI clients see the failure
    instead of the thread staying stuck in SUBMITTED state forever.
    """

    async def _dispatch_message(
        thread_id: str,
        content: str,
        agent_id: str | None,
    ) -> None:
        await worker_spawner.ensure_worker()
        if not circuit_breaker.pre_dispatch():
            raise HTTPException(
                status_code=503, detail=circuit_breaker.rejection_detail
            )

        # Resolve thread-level fields required by the worker.
        team_preset: str | None = None
        workspace_root: str | None = None
        try:
            async with session_factory() as db:
                thread = await get_thread(db, thread_id)
                if thread is None:
                    raise await _classify_missing_ws_thread(
                        thread_id=thread_id,
                        session_factory=session_factory,
                        checkpointer=checkpointer,
                    )
                # WS-G01: Mirror REST 409 guards — reject dispatch to
                # terminal or input-paused threads.
                _terminal_values = (
                    ThreadStatus.COMPLETED.value,
                    ThreadStatus.FAILED.value,
                    ThreadStatus.CANCELLED.value,
                    ThreadStatus.ARCHIVED.value,
                )
                if thread.status in _terminal_values:
                    raise WebSocketCommandRejectedError(
                        thread_id=thread_id,
                        code="THREAD_TERMINAL",
                        message=(
                            f"Cannot send messages to thread in {thread.status!r} state"
                        ),
                        recoverable=False,
                    )
                if thread.status == ThreadStatus.INPUT_REQUIRED.value:
                    raise WebSocketCommandRejectedError(
                        thread_id=thread_id,
                        code="THREAD_INPUT_REQUIRED",
                        message=(
                            "Cannot send a follow-up message while the"
                            " thread is paused for input"
                        ),
                        recoverable=True,
                    )
                team_preset = thread.team_preset
                if thread.thread_metadata:
                    try:
                        meta = json.loads(thread.thread_metadata)
                        workspace_root = meta.get("workspace_root")
                    except (ValueError, AttributeError):
                        pass
        except WebSocketCommandRejectedError:
            raise
        except Exception:
            logger.warning(
                "Could not look up thread %s for WS dispatch — "
                "team_preset/workspace_root will be None",
                thread_id,
                exc_info=True,
            )

        dispatch = DispatchRequest(
            action="ingest",
            thread_id=thread_id,
            agent_id=agent_id or "vaultspec-supervisor",
            content=content,
            team_preset=team_preset,
            workspace_root=workspace_root,
        )

        try:
            resp = await worker_client.post(
                "/dispatch",
                json=dispatch.model_dump(),
                headers=_trace_headers(),
            )
            # PROD-068: worker 429 means alive but at capacity — message dropped.
            if resp.status_code == httpx.codes.TOO_MANY_REQUESTS:
                logger.warning(
                    "Worker at capacity (429) for WS dispatch thread %s"
                    " — message not delivered",
                    thread_id,
                )
                raise WebSocketCommandRejectedError(
                    thread_id=thread_id,
                    code="WORKER_AT_CAPACITY",
                    message="Worker at capacity — try again later",
                    recoverable=True,
                )
            circuit_breaker.record_success()
            app_state.worker_last_heartbeat_ts = time.monotonic()
        except WebSocketCommandRejectedError:
            raise
        except httpx.HTTPError:
            circuit_breaker.record_failure()
            logger.warning(
                "Failed to dispatch message to worker for thread %s",
                thread_id,
                exc_info=True,
            )
            # WS-G01: Mirror REST path — mark thread FAILED and broadcast.
            await _ws_mark_failed_and_broadcast(
                thread_id,
                session_factory,
                connection_manager,
                "Worker unreachable — message not delivered",
            )

    return _dispatch_message


def _create_dispatch_control_handler(
    worker_client: httpx.AsyncClient,
    session_factory: Any,
    checkpointer: Any,
    circuit_breaker: WorkerCircuitBreaker,
    worker_spawner: "LazyWorkerSpawner",
    app_state: Any,
) -> Callable:
    """Create agent control handler that dispatches to the worker.

    Replaces the old ``_create_agent_control_handler`` which ran
    graph operations locally.  Now sends an HTTP POST to the worker's
    ``/dispatch`` endpoint.
    """

    async def _dispatch_control(
        thread_id: str,
        agent_id: str,
        action: AgentControlAction,
    ) -> None:
        match action:
            case AgentControlAction.TERMINATE:
                dispatch_action = "cancel"
            case AgentControlAction.RESUME:
                logger.warning(
                    "WS RESUME without option_id is a no-op;"
                    " use POST /permissions/{id}/respond"
                    " -- thread %s",
                    thread_id,
                )
                return
            case AgentControlAction.PAUSE:
                logger.info("Pause not supported -- ignoring for thread %s", thread_id)
                return

        async with session_factory() as db:
            thread = await get_thread(db, thread_id)
            if thread is None:
                raise await _classify_missing_ws_thread(
                    thread_id=thread_id,
                    session_factory=session_factory,
                    checkpointer=checkpointer,
                )

        await worker_spawner.ensure_worker()
        # PROD-066: Cancel control must bypass circuit breaker so users can
        # always stop a running agent even when the breaker is OPEN.
        try:
            resp = await worker_client.post(
                "/dispatch",
                json={
                    "action": dispatch_action,
                    "thread_id": thread_id,
                    "agent_id": agent_id,
                },
                headers=_trace_headers(),
            )
            if resp.is_success:
                circuit_breaker.record_success()
                app_state.worker_last_heartbeat_ts = time.monotonic()
        except httpx.HTTPError:
            circuit_breaker.record_failure()
            logger.warning(
                "Failed to dispatch control to worker for thread %s",
                thread_id,
                exc_info=True,
            )

    return _dispatch_control


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
    # --- Startup ---
    logger.info("Starting gateway lifespan (ADR-019)")
    settings.validate_postgres_requirement()

    engine = await init_db(settings.database_url)
    logger.info(
        "Database initialised (%s, migrations applied)",
        settings.resolved_database_backend,
    )
    app.state.sqlite_fallback_diagnostics = _build_sqlite_fallback_diagnostics()

    if settings.resolved_checkpoint_backend == "sqlite":
        backfill_teamstate_sdd_fields(settings.checkpoint_path)

    # LangGraph checkpointer -- READ-ONLY in the gateway (ADR-019).
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

        # Event aggregator -- lightweight in the gateway.
        # No graphs are registered here; the worker runs ingest.
        aggregator = EventAggregator(telemetry=OTelAggregatorHook())
        app.state.aggregator = aggregator

        # Connection manager (depends on aggregator)
        connection_manager = ConnectionManager(aggregator)
        app.state.connection_manager = connection_manager

        # Store engine ref for shutdown
        app.state.db_engine = engine

        # Telemetry (ADR-010 -- mandatory)
        configure_telemetry()
        logger.info("Telemetry configured")

        # httpx client for dispatching work to the worker process
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

        # PHASE-1a: Lazy worker spawn — defer to first dispatch so
        # read-only endpoints (list_threads, get_thread_status, etc.)
        # work instantly without waiting for the worker to start.
        worker_spawner = LazyWorkerSpawner(
            worker_url=settings.worker_url,
            worker_port=settings.worker_port,
            auto_spawn=settings.auto_spawn_worker,
        )
        app.state.worker_spawner = worker_spawner

        # PROD-028: Circuit breaker for worker dispatch
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=settings.cb_failure_threshold,
            recovery_timeout=settings.cb_recovery_timeout_seconds,
        )
        app.state.circuit_breaker = circuit_breaker

        # PROD-002: Worker watchdog — auto-restart on crash
        worker_state = WorkerState()
        app.state.worker_state = worker_state
        watchdog = WorkerWatchdog(
            worker_spawner, circuit_breaker, worker_state, app.state
        )
        watchdog_task = asyncio.create_task(watchdog.run())

        # Wire dispatch handlers for WebSocket commands
        msg_handler = _create_dispatch_message_handler(
            worker_client,
            get_session_factory(),
            checkpointer,
            circuit_breaker,
            worker_spawner,
            connection_manager,
            app.state,
        )
        connection_manager.set_message_handler(msg_handler)

        ctrl_handler = _create_dispatch_control_handler(
            worker_client,
            get_session_factory(),
            checkpointer,
            circuit_breaker,
            worker_spawner,
            app.state,
        )
        connection_manager.set_agent_control_handler(ctrl_handler)

        # F-36 fix: re-dispatch RECONCILING threads after worker is ready.
        # reconcile_threads_on_startup marks threads but never dispatches them.
        async def _redispatch_reconciling() -> None:
            try:
                await worker_spawner.ensure_worker()
                session_factory = get_session_factory()
                async with session_factory() as db:
                    threads, _ = await list_threads(
                        db, status=ThreadStatus.RECONCILING, limit=100
                    )
                    if not threads:
                        return
                    logger.info("Re-dispatching %d reconciling threads", len(threads))
                    for thread in threads:
                        meta = {}
                        if thread.thread_metadata:
                            try:
                                meta = json.loads(thread.thread_metadata)
                            except Exception:
                                logger.debug(
                                    "Failed to parse thread metadata for %s",
                                    thread.id,
                                    exc_info=True,
                                )
                        dispatch = DispatchRequest(
                            action="ingest",
                            thread_id=thread.id,
                            team_preset=thread.team_preset,
                            workspace_root=meta.get("workspace_root"),
                        )
                        try:
                            if circuit_breaker.state == "open":
                                logger.warning(
                                    "Circuit breaker open, skipping re-dispatch for %s",
                                    thread.id,
                                )
                                continue
                            resp = await worker_client.post(
                                "/dispatch",
                                json=dispatch.model_dump(),
                                headers=_trace_headers(),
                            )
                            if resp.is_success:
                                circuit_breaker.record_success()
                                app.state.worker_last_heartbeat_ts = time.monotonic()
                                logger.info(
                                    "Re-dispatched reconciling thread %s",
                                    thread.id,
                                )
                            else:
                                logger.warning(
                                    "Re-dispatch failed for thread %s: %s",
                                    thread.id,
                                    resp.status_code,
                                )
                        except Exception as exc:
                            logger.warning(
                                "Re-dispatch error for thread %s: %s",
                                thread.id,
                                exc,
                            )
            except Exception as exc:
                logger.error("Reconciling re-dispatch task failed: %s", exc)

        reconcile_task = asyncio.create_task(_redispatch_reconciling())

        logger.info("Gateway startup complete")

        yield

        reconcile_task.cancel()
        await asyncio.gather(reconcile_task, return_exceptions=True)

        # --- Shutdown ---
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

    # --- CORS Middleware ---
    # Always add CORS so the React SPA can make cross-origin requests in
    # both dev and production (C1 fix).  CORS spec forbids allow_origins=["*"]
    # combined with allow_credentials=True (browsers reject such responses), so
    # we never use wildcard origins.  In dev the extra Vite origins are included;
    # in production the deployer sets VAULTSPEC_CORS_ALLOWED_ORIGINS.
    cors_origins: list[str] = list(settings.cors_allowed_origins)
    app.add_middleware(
        cast("Any", CORSMiddleware),
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Telemetry Middleware (ADR-010) ---
    app.add_middleware(cast("Any", TelemetryMiddleware))

    # --- Cache-Control Middleware (ADR-007 S5) ---
    app.add_middleware(cast("Any", _CacheControlMiddleware))

    # --- REST Router ---
    app.include_router(router, prefix="/api")

    # --- Internal Router (worker relay -- ADR-019) ---
    app.include_router(internal_router)

    # --- Gateway Health (CRIT-03 — MCP startup probe target) ---
    @app.get("/health")
    async def health_endpoint() -> dict[str, object]:
        """Top-level liveness check for external probes.

        `/health` stays green when the gateway process is alive. Aggregate
        dependency readiness is exposed separately via `/api/health`.
        """
        worker_connected = False
        last_hb = getattr(app.state, "worker_last_heartbeat_ts", None)
        if last_hb is not None:
            worker_connected = (
                time.monotonic() - last_hb
            ) < settings.worker_heartbeat_timeout_seconds
        cb: WorkerCircuitBreaker | None = getattr(
            app.state,
            "circuit_breaker",
            None,
        )
        cb_state = cb.state if cb is not None else "unknown"
        spawner: LazyWorkerSpawner | None = getattr(
            app.state,
            "worker_spawner",
            None,
        )
        worker_spawned = spawner.spawned if spawner is not None else False
        worker_pid = (
            spawner.process.pid if spawner is not None and spawner.process else None
        )
        ws: WorkerState | None = getattr(app.state, "worker_state", None)
        worker_status = ws.worker_status if ws is not None else "unknown"
        worker_restart_count = ws.worker_restart_count if ws is not None else 0
        worker_last_restart_reason = (
            ws.worker_last_restart_reason if ws is not None else None
        )
        worker_last_restart_detail = (
            ws.worker_last_restart_detail if ws is not None else None
        )
        worker_last_restart_started_at = (
            ws.worker_last_restart_started_at if ws is not None else None
        )
        worker_last_restart_completed_at = (
            ws.worker_last_restart_completed_at if ws is not None else None
        )
        worker_last_restart_succeeded = (
            ws.worker_last_restart_succeeded if ws is not None else None
        )
        worker_last_restart_attempts = (
            ws.worker_last_restart_attempts if ws is not None else 0
        )
        worker_stderr_log_path = ws.worker_stderr_log_path if ws is not None else None
        repair_summary = getattr(
            app.state,
            "repair_summary",
            {
                "repair_backlog": 0,
                "paused_resumable": 0,
                "checkpoint_unavailable": 0,
            },
        )
        sqlite_fallback_diagnostics = getattr(
            app.state, "sqlite_fallback_diagnostics", None
        )
        ready = not (
            cb_state == "open"
            or worker_status in {"down", "restarting"}
            or (worker_spawned and not worker_connected)
        )
        return {
            "status": "ok",
            "service": "gateway",
            "ready": ready,
            "worker_connected": worker_connected,
            "worker_spawned": worker_spawned,
            "worker_pid": worker_pid,
            "worker_status": worker_status,
            "worker_restart_count": worker_restart_count,
            "worker_last_restart_reason": worker_last_restart_reason,
            "worker_last_restart_detail": worker_last_restart_detail,
            "worker_last_restart_started_at": worker_last_restart_started_at,
            "worker_last_restart_completed_at": worker_last_restart_completed_at,
            "worker_last_restart_succeeded": worker_last_restart_succeeded,
            "worker_last_restart_attempts": worker_last_restart_attempts,
            "worker_stderr_log_path": worker_stderr_log_path,
            "circuit_breaker": cb_state,
            "database_backend": settings.resolved_database_backend,
            "checkpoint_backend": settings.resolved_checkpoint_backend,
            "postgres_required": settings.postgres_required,
            # production_certifying is true only when BOTH the application DB
            # and the checkpoint backend resolve to Postgres.  SQLite is a
            # supported fallback for local/CI use but is not the certifying
            # production backend.  Operators should monitor this field and
            # alert when it is false in a production deployment.
            "production_certifying": (
                settings.resolved_database_backend == "postgres"
                and settings.resolved_checkpoint_backend == "postgres"
            ),
            "repair_backlog": repair_summary.get("repair_backlog", 0),
            "paused_resumable": repair_summary.get("paused_resumable", 0),
            "checkpoint_unavailable": repair_summary.get("checkpoint_unavailable", 0),
            "sqlite_fallback": sqlite_fallback_diagnostics,
        }

    # --- WebSocket Route ---
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for multiplexed real-time events."""
        cm: ConnectionManager = app.state.connection_manager
        client_id = await cm.connect(websocket)
        await cm.listen(client_id)

    # --- Static Files (React SPA) ---
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
