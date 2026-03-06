"""Shared fixtures for lib/api/tests/.

Centralises engine, session_factory, session, and make_app so that all test
modules use the same in-memory SQLite setup and dependency overrides.

ADR-019: The control surface no longer runs agent execution locally.
Tests override get_worker_client with a test httpx.AsyncClient that
posts to a local test handler (or simply captures requests).  The
GraphRegistry has moved to the worker process.

API-M7 fix: shared fixtures eliminate duplicate engine/session_factory
definitions across test files.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...core.aggregator import EventAggregator
from ...database.models import Base
from ...database.session import get_db
from ..app import create_app
from ..endpoints import (
    get_aggregator,
    get_checkpointer,
    get_worker_client,
)


__all__: list[str] = []


# ---------------------------------------------------------------------------
# Engine / Session fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """In-memory async SQLAlchemy engine with all tables created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Async session factory bound to the in-memory engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(engine):
    """Provide a fresh async session for direct DB assertions."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# Test worker transport -- captures dispatch requests
# ---------------------------------------------------------------------------


class _CapturedDispatch:
    """Records dispatch requests sent by the control surface to the worker."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def clear(self) -> None:
        self.requests.clear()


def _make_test_worker_transport(
    captured: _CapturedDispatch,
) -> httpx.MockTransport:
    """Create an httpx transport that captures /dispatch POSTs.

    Returns 200 with ``{"status": "dispatched", "thread_id": "..."}`` for
    all POST /dispatch requests, recording the request body in *captured*.
    """
    import json as _json

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dispatch" and request.method == "POST":
            body = _json.loads(request.content)
            captured.requests.append(body)
            return httpx.Response(
                200,
                json={"status": "dispatched", "thread_id": body.get("thread_id", "")},
            )
        return httpx.Response(404, json={"detail": "Not found"})

    return httpx.MockTransport(_handler)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def make_app(session_factory, aggregator=None, captured_dispatch=None):
    """Create a test FastAPI app with all dependency overrides applied.

    ADR-019: overrides get_worker_client with a test httpx client that
    captures dispatch requests.  GraphRegistry and TaskGroup are no longer
    needed -- the worker owns graph lifecycle.

    Returns:
        Tuple of (app, aggregator, captured_dispatch, checkpointer).
    """
    app = create_app()

    if aggregator is None:
        aggregator = EventAggregator()
    if captured_dispatch is None:
        captured_dispatch = _CapturedDispatch()

    # Store singletons in app.state so WebSocket handlers can read them
    app.state.aggregator = aggregator

    # In-memory checkpointer -- never touches vaultspec.db
    checkpointer = MemorySaver()
    app.state.checkpointer = checkpointer

    # Test worker client -- captures dispatch POST requests
    transport = _make_test_worker_transport(captured_dispatch)
    worker_client = httpx.AsyncClient(
        transport=transport, base_url="http://test-worker:8001"
    )
    app.state.worker_client = worker_client

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    app.dependency_overrides[get_checkpointer] = lambda: checkpointer
    app.dependency_overrides[get_worker_client] = lambda: worker_client

    return app, aggregator, captured_dispatch, checkpointer
