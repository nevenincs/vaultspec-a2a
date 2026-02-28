"""FastAPI application factory — the system entry point.

Creates the ASGI application with:
- Lifespan management (init/close DB, EventAggregator, telemetry)
- CORS middleware (permissive in dev)
- REST router from ``endpoints.py``
- WebSocket route via ``ConnectionManager`` from Task 4
- StaticFiles mount for SvelteKit build at ``src/ui/build/`` (ADR-007)

See: ADR-007 (FastAPI serving, SPA)
     ADR-011 (Frontend-Backend Wire Contract)
"""

import logging
import re

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import anyio
import uvicorn

from anyio.abc import TaskGroup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.websockets import WebSocket

from ..core.aggregator import EventAggregator
from ..core.config import settings
from ..database.session import close_db, init_db
from ..protocols import mcp as mcp_server
from ..telemetry import TelemetryMiddleware, configure_telemetry
from .endpoints import GraphRegistry, router
from .schemas.enums import AgentControlAction, AgentLifecycleState
from .websocket import ConnectionManager


__all__ = ["create_app", "main"]

logger = logging.getLogger(__name__)

# Path to the SvelteKit build output (ADR-007)
_UI_BUILD_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "ui" / "build"

# SvelteKit hashed immutable assets: /_app/immutable/**
_IMMUTABLE_PATTERN = re.compile(r"^/_app/immutable/")
_CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
_CACHE_HTML = "no-cache"


class _CacheControlMiddleware(BaseHTTPMiddleware):
    """Set Cache-Control headers for static SvelteKit assets (ADR-007 §5).

    - ``/_app/immutable/**`` (content-hashed JS/CSS): cache forever
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


def _create_message_handler(
    graph_registry: GraphRegistry,
    aggregator: EventAggregator,
    tg: TaskGroup,
) -> Callable:
    """Create message handler closure for graph_registry/aggregator."""

    async def _message_handler(
        thread_id: str,
        content: str,
        agent_id: str | None,
    ) -> None:
        graph = graph_registry.get(thread_id)
        if graph is None:
            logger.warning(
                "No graph registered for thread %s — ignoring message",
                thread_id,
            )
            return
        if not graph_registry.mark_ingest_active(thread_id):
            logger.warning(
                "Ingest already active for thread %s — dropping WS message",
                thread_id,
            )
            return
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 100,
        }
        graph_input = {"messages": [HumanMessage(content=content)]}
        _aid = agent_id or "supervisor"

        async def _ingest_and_release(_tid: str = thread_id) -> None:
            try:
                await aggregator.ingest(_tid, _aid, graph, graph_input, config)
            finally:
                graph_registry.mark_ingest_done(_tid)

        tg.start_soon(_ingest_and_release)

    return _message_handler


def _create_agent_control_handler(
    graph_registry: GraphRegistry,
    aggregator: EventAggregator,
    tg: TaskGroup,
) -> Callable:
    """Create agent control handler closure."""

    async def _agent_control_handler(
        thread_id: str,
        agent_id: str,
        action: AgentControlAction,
    ) -> None:
        match action:
            case AgentControlAction.TERMINATE:
                aggregator.cancel_thread(thread_id)
            case AgentControlAction.RESUME:
                graph = graph_registry.get(thread_id)
                if graph is None:
                    logger.warning(
                        "No graph registered for thread %s — cannot resume",
                        thread_id,
                    )
                    return
                if not graph_registry.mark_ingest_active(thread_id):
                    logger.warning(
                        "Ingest already active for thread %s — cannot resume",
                        thread_id,
                    )
                    return
                config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 100,
                }

                async def _resume_and_release(_tid: str = thread_id) -> None:
                    try:
                        await aggregator.ingest(
                            _tid,
                            agent_id,
                            graph,
                            None,
                            config,
                        )
                    finally:
                        graph_registry.mark_ingest_done(_tid)

                tg.start_soon(_resume_and_release)
            case AgentControlAction.PAUSE:
                logger.info(
                    "Pause not supported by LangGraph — ignoring for thread %s",
                    thread_id,
                )
                await aggregator.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    node_name="supervisor",
                    state=AgentLifecycleState.WORKING,
                    detail="Pause not supported; agent continues working",
                )

    return _agent_control_handler


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown hooks."""
    # --- Startup ---
    logger.info("Starting application lifespan")

    # Single source of truth for the database file path (Fix 4 / H7).
    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Database (SQLAlchemy)
    engine = await init_db(db_path)
    logger.info("Database initialised (WAL mode) at %s", db_path)

    # LangGraph checkpointer — uses the same path as the application DB.
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        logger.info("LangGraph checkpointer initialised at %s", db_path)

        # Event aggregator
        aggregator = EventAggregator()
        app.state.aggregator = aggregator

        # Graph registry: thread_id -> compiled LangGraph runnable
        graph_registry = GraphRegistry()
        app.state.graph_registry = graph_registry

        # Connection manager (depends on aggregator)
        connection_manager = ConnectionManager(aggregator)
        app.state.connection_manager = connection_manager

        # Store engine ref for shutdown
        app.state.db_engine = engine

        # Telemetry (ADR-010 — mandatory)
        configure_telemetry()
        logger.info("Telemetry configured")

        # Task group for background work (ADR-007 §5).
        async with anyio.create_task_group() as tg:
            app.state.task_group = tg

            # Wire handlers
            msg_handler = _create_message_handler(graph_registry, aggregator, tg)
            connection_manager.set_message_handler(msg_handler)

            ctrl_handler = _create_agent_control_handler(graph_registry, aggregator, tg)
            connection_manager.set_agent_control_handler(ctrl_handler)

            logger.info("Application startup complete")

            yield

            # --- Shutdown ---
            logger.info("Shutting down application")

            await connection_manager.shutdown()
            await aggregator.shutdown()
            await close_db()

            logger.info("Application shutdown complete")
            # Task group __aexit__ awaits remaining background tasks
            tg.cancel_scope.cancel()


def main() -> None:
    """Launch the vaultspec-a2a server.

    Entry point for the ``vaultspec`` CLI command defined in
    ``[project.scripts]`` (ADR-015).
    """
    uvicorn.run(
        "lib.api.app:create_app",
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
    # Always add CORS so the SvelteKit SPA can make cross-origin requests in
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

    # --- Cache-Control Middleware (ADR-007 §5) ---
    app.add_middleware(cast(Any, _CacheControlMiddleware))

    # --- REST Router ---
    app.include_router(router, prefix="/api")

    # --- MCP Server (SSE transport for IDE clients: Cursor, Windsurf) ---
    # Mounted at /mcp; exposes team_create and team_status tools (ADR-006 §5)
    app.mount("/mcp", mcp_server.sse_app())

    # --- WebSocket Route ---
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for multiplexed real-time events."""
        cm: ConnectionManager = app.state.connection_manager
        client_id = await cm.connect(websocket)
        await cm.listen(client_id)

    # --- Static Files (SvelteKit SPA) ---
    if _UI_BUILD_DIR.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_UI_BUILD_DIR), html=True),
            name="ui",
        )
        logger.info("Mounted SvelteKit SPA from %s", _UI_BUILD_DIR)
    else:
        logger.warning(
            "SvelteKit build not found at %s — UI will not be served",
            _UI_BUILD_DIR,
        )

    return app
