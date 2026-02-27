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

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocket

from ..core.aggregator import EventAggregator
from ..core.config import settings
from ..database.session import close_db, init_db
from ..protocols import mcp as mcp_server
from .endpoints import router
from .websocket import ConnectionManager


# Telemetry is an optional extra; import once at module level so the function
# reference is stable and the import lives at the top level (PLC0415).
try:
    from ..telemetry import configure_telemetry as _configure_telemetry
except ImportError:
    _configure_telemetry: Callable[[], None] | None = None


__all__ = ["create_app"]

logger = logging.getLogger(__name__)

# Path to the SvelteKit build output (ADR-007)
_UI_BUILD_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "ui" / "build"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown hooks.

    Startup:
    - Initialise the database (SQLite WAL mode, create tables)
    - Create the EventAggregator singleton
    - Create the ConnectionManager
    - Optionally configure telemetry

    Shutdown:
    - Shut down the ConnectionManager (disconnect all clients)
    - Shut down the EventAggregator (cancel debounce tasks)
    - Close the database engine
    """
    # --- Startup ---
    logger.info("Starting application lifespan")

    # Database
    engine = await init_db()
    logger.info("Database initialised (WAL mode)")

    # Event aggregator
    aggregator = EventAggregator()
    app.state.aggregator = aggregator

    # Connection manager (depends on aggregator)
    connection_manager = ConnectionManager(aggregator)
    app.state.connection_manager = connection_manager

    # Store engine ref for shutdown
    app.state.db_engine = engine

    # Optional telemetry
    if _configure_telemetry is not None:
        _configure_telemetry()
        logger.info("Telemetry configured")
    else:
        logger.debug("Telemetry packages not installed, skipping")

    logger.info("Application startup complete")

    yield

    # --- Shutdown ---
    logger.info("Shutting down application")

    await connection_manager.shutdown()
    await aggregator.shutdown()
    await close_db()

    logger.info("Application shutdown complete")


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
    if settings.is_dev:
        app.add_middleware(
            cast(Any, CORSMiddleware),
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

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
