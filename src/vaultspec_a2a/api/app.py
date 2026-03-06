"""FastAPI application factory -- the control surface entry point (ADR-019).

Creates the ASGI application with:
- Lifespan management (init/close DB, EventAggregator, telemetry)
- CORS middleware (permissive in dev)
- REST router from ``endpoints.py``
- Internal router from ``internal.py`` (worker relay)
- WebSocket route via ``ConnectionManager``
- StaticFiles mount for React SPA build at ``src/ui/build/`` (ADR-007/018)
- Worker supervisor for auto-spawn mode

The control surface NO LONGER runs agent execution locally.  All graph
compilation and ``aggregator.ingest()`` calls are dispatched to the
worker process via HTTP POST to ``/dispatch`` (ADR-019 service separation).

See: ADR-007 (FastAPI serving, SPA)
     ADR-011 (Frontend-Backend Wire Contract)
     ADR-019 (Service Separation)
"""

import json
import logging
import re

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import anyio
import httpx
import uvicorn

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.websockets import WebSocket

from ..core import EventAggregator, settings
from ..database.crud import get_thread
from ..database.migrations import backfill_teamstate_sdd_fields
from ..database.session import close_db, get_session_factory, init_db
from ..protocols import mcp as mcp_server
from ..telemetry import TelemetryMiddleware, configure_telemetry
from .endpoints import router
from .internal import internal_router
from .schemas.enums import AgentControlAction
from .schemas.internal import DispatchRequest
from .supervisor import WorkerSupervisor
from .websocket import ConnectionManager


__all__ = ["create_app", "main"]

logger = logging.getLogger(__name__)

# Path to the React SPA build output (ADR-007 / ADR-018)
_UI_BUILD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "src" / "ui" / "build"

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


def _create_dispatch_message_handler(
    worker_client: httpx.AsyncClient,
    session_factory: Any,
) -> Callable:
    """Create message handler that dispatches to the worker process.

    Replaces the old ``_create_message_handler`` which ran
    ``aggregator.ingest()`` locally.  Now sends an HTTP POST to the
    worker's ``/dispatch`` endpoint (ADR-019).

    Looks up the thread to forward ``team_preset`` and ``workspace_root``
    so the worker can recompile the correct graph (T26b).
    """

    async def _dispatch_message(
        thread_id: str,
        content: str,
        agent_id: str | None,
    ) -> None:
        # Resolve thread-level fields required by the worker.
        team_preset: str | None = None
        workspace_root: str | None = None
        try:
            async with session_factory() as db:
                thread = await get_thread(db, thread_id)
                if thread is not None:
                    team_preset = thread.team_preset
                    if thread.thread_metadata:
                        try:
                            meta = json.loads(thread.thread_metadata)
                            workspace_root = meta.get("workspace_root")
                        except (ValueError, AttributeError):
                            pass
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
            await worker_client.post(
                "/dispatch",
                json=dispatch.model_dump(),
            )
        except httpx.HTTPError:
            logger.warning(
                "Failed to dispatch message to worker for thread %s",
                thread_id,
                exc_info=True,
            )

    return _dispatch_message


def _create_dispatch_control_handler(
    worker_client: httpx.AsyncClient,
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
                    "WS RESUME without option_id is a no-op; use POST /permissions/{id}/respond -- thread %s",
                    thread_id,
                )
                return
            case AgentControlAction.PAUSE:
                logger.info("Pause not supported -- ignoring for thread %s", thread_id)
                return

        try:
            await worker_client.post(
                "/dispatch",
                json={
                    "action": dispatch_action,
                    "thread_id": thread_id,
                    "agent_id": agent_id,
                },
            )
        except httpx.HTTPError:
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

    ADR-019: The control surface no longer runs agent execution.  All
    graph compilation and ingest calls are dispatched to the worker
    process.  The lifespan sets up:
    1. Database (SQLAlchemy)
    2. Read-only checkpointer (for snapshot queries -- safe under WAL mode)
    3. EventAggregator (lightweight -- for local event relay only)
    4. ConnectionManager
    5. Telemetry
    6. httpx.AsyncClient for worker dispatch
    7. WorkerSupervisor (optional, auto_spawn_worker mode)
    8. Task group for supervisor monitoring only
    """
    # --- Startup ---
    logger.info("Starting control surface lifespan (ADR-019)")

    # Single source of truth for the database file path (Fix 4 / H7).
    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Database engine + session factory + Alembic migrations (ADR-029).
    # init_db routes file-based DBs through run_migrations(); no create_all.
    engine = await init_db(db_path)
    logger.info("Database initialised (WAL mode + migrations) at %s", db_path)

    # Backfill new state fields into existing checkpoint rows (additive,
    # idempotent — fills missing keys with zero values, touches nothing else).
    backfill_teamstate_sdd_fields(db_path)

    # LangGraph checkpointer -- READ-ONLY in the control surface (ADR-019).
    # The worker owns the write path.  This connection is safe for concurrent
    # reads under SQLite WAL mode.  Used by GET /threads/{id}/state to read
    # checkpoint data for snapshot enrichment.
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        logger.info("LangGraph checkpointer initialised (read-only) at %s", db_path)

        # Event aggregator -- lightweight in the control surface.
        # No graphs are registered here; the worker runs ingest.
        aggregator = EventAggregator()
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
        )
        app.state.worker_client = worker_client
        logger.info("Worker client configured: %s", settings.worker_url)

        # Optional: auto-spawn the worker as a child process
        supervisor: WorkerSupervisor | None = None
        if settings.auto_spawn_worker:
            supervisor = WorkerSupervisor(worker_port=settings.worker_port)
            supervisor.start()
            app.state.worker_supervisor = supervisor
            logger.info("Worker supervisor started (auto_spawn_worker=True)")

        # Wire dispatch handlers for WebSocket commands
        msg_handler = _create_dispatch_message_handler(
            worker_client, get_session_factory()
        )
        connection_manager.set_message_handler(msg_handler)

        ctrl_handler = _create_dispatch_control_handler(worker_client)
        connection_manager.set_agent_control_handler(ctrl_handler)

        # Task group for supervisor monitoring only (NOT for agent execution)
        async with anyio.create_task_group() as tg:
            if supervisor is not None:
                tg.start_soon(supervisor.monitor)

            logger.info("Control surface startup complete")

            yield

            # --- Shutdown ---
            logger.info("Shutting down control surface")

            # Cancel monitor task FIRST to prevent restart race: if the worker
            # dies between stop() and cancel, monitor would immediately respawn it.
            tg.cancel_scope.cancel()

            # Close worker HTTP client
            await worker_client.aclose()

            # Stop worker supervisor (async since T29)
            if supervisor is not None:
                await supervisor.stop()

            await connection_manager.shutdown()
            await aggregator.shutdown()
            await close_db()

            logger.info("Control surface shutdown complete")


def main() -> None:
    """Launch the vaultspec-a2a server.

    Entry point for the ``vaultspec`` CLI command defined in
    ``[project.scripts]`` (ADR-015).
    """
    uvicorn.run(
        "vaultspec_a2a.api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
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
        cast(Any, CORSMiddleware),
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Telemetry Middleware (ADR-010) ---
    app.add_middleware(cast(Any, TelemetryMiddleware))

    # --- Cache-Control Middleware (ADR-007 S5) ---
    app.add_middleware(cast(Any, _CacheControlMiddleware))

    # --- REST Router ---
    app.include_router(router, prefix="/api")

    # --- Internal Router (worker relay -- ADR-019) ---
    app.include_router(internal_router)

    # --- MCP Server (SSE transport for IDE clients: Cursor, Windsurf) ---
    # Mounted at /mcp; exposes team_create and team_status tools (ADR-006 S5)
    app.mount("/mcp", mcp_server.sse_app())

    # --- WebSocket Route ---
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for multiplexed real-time events."""
        cm: ConnectionManager = app.state.connection_manager
        client_id = await cm.connect(websocket)
        await cm.listen(client_id)

    # --- Static Files (React SPA) ---
    if _UI_BUILD_DIR.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_UI_BUILD_DIR), html=True),
            name="ui",
        )
        logger.info("Mounted React SPA from %s", _UI_BUILD_DIR)
    else:
        logger.warning(
            "SPA build not found at %s -- UI will not be served",
            _UI_BUILD_DIR,
        )

    return app
