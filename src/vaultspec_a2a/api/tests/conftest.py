"""Shared fixtures for src/vaultspec_a2a/api/tests/.

Centralises engine, session_factory, session, checkpointer, and make_app so
that all test modules use the same isolated SQLite setup and dependency
overrides.

ADR-019: The gateway no longer runs agent execution locally.  Tests wire a
real in-process dispatch receiver (a minimal FastAPI ASGI app served via
``httpx.ASGITransport``) so that HTTP serialisation and routing are exercised
without a live worker process.  No ``MockTransport``, no ``unittest.mock``.

The ``checkpointer`` fixture uses ``AsyncSqliteSaver`` backed by a per-test
SQLite file so that gateway read-path enrichment exercises the real
checkpointer implementation, not a ``MemorySaver`` stub.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest_asyncio

from fastapi import FastAPI, Request
from httpx import ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...core.aggregator import EventAggregator
from ...database.models import Base
from ...database.session import get_db
from ..app import LazyWorkerSpawner, WorkerCircuitBreaker, create_app
from ..endpoints import (
    get_aggregator,
    get_checkpointer,
    get_circuit_breaker,
    get_worker_client,
    get_worker_spawner,
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
# Real checkpointer fixture — AsyncSqliteSaver backed by a per-test file
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def checkpointer():
    """Real AsyncSqliteSaver backed by a temporary SQLite file per test.

    Replaces the former MemorySaver stub so that gateway read-path enrichment
    exercises the real checkpointer implementation (AsyncSqliteSaver).
    """
    case_dir = Path.cwd() / ".tmp" / "api-test-checkpoints" / uuid4().hex
    case_dir.mkdir(parents=True, exist_ok=True)
    db_file = case_dir / "test_checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(db_file)) as cp:
        yield cp


# ---------------------------------------------------------------------------
# In-process dispatch receiver — real FastAPI ASGI, no mock
# ---------------------------------------------------------------------------


class _InProcessWorker:
    """Minimal in-process worker that accepts /dispatch and /health requests.

    Uses a real FastAPI ASGI app served via ``httpx.ASGITransport`` — real
    HTTP serialisation and Pydantic validation are exercised on every request.
    Not a mock, not a fake transport handler, not ``unittest.mock``.

    Attributes:
        dispatches: All dispatch request bodies received so far.
    """

    def __init__(self) -> None:
        self.dispatches: list[dict] = []

        _app = FastAPI()

        @_app.post("/dispatch")
        async def _dispatch(request: Request) -> dict:
            body = await request.json()
            self.dispatches.append(body)
            return {"status": "dispatched", "thread_id": body.get("thread_id", "")}

        @_app.get("/health")
        async def _health() -> dict:
            return {"status": "ok"}

        self._client = httpx.AsyncClient(
            transport=ASGITransport(app=_app),
            base_url="http://test-worker:8001",
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the httpx client backed by the in-process worker app."""
        return self._client

    def clear(self) -> None:
        """Clear all recorded dispatch requests."""
        self.dispatches.clear()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def make_app(
    session_factory,
    checkpointer: AsyncSqliteSaver,
    aggregator: EventAggregator | None = None,
) -> tuple:
    """Create a test FastAPI app with all dependency overrides applied.

    ADR-019: wires a real in-process dispatch receiver (ASGITransport over a
    minimal FastAPI app) for the worker client, and injects the real
    AsyncSqliteSaver checkpointer from the calling fixture.

    Returns:
        Tuple of (app, aggregator, worker, checkpointer).
    """
    app = create_app()

    @asynccontextmanager
    async def _test_lifespan(_app):
        yield

    app.router.lifespan_context = _test_lifespan

    if aggregator is None:
        aggregator = EventAggregator()

    worker = _InProcessWorker()

    # Store singletons in app.state so WebSocket handlers can read them
    app.state.aggregator = aggregator
    app.state.checkpointer = checkpointer

    # In-process worker client — real ASGI, no mock
    app.state.worker_client = worker.client

    # PROD-028: circuit breaker for dispatch calls
    cb = WorkerCircuitBreaker()
    app.state.circuit_breaker = cb

    # PHASE-1a: lazy worker spawner — pre-marked as spawned for tests
    spawner = LazyWorkerSpawner(
        worker_url="http://test-worker:8001",
        worker_port=8001,
        auto_spawn=False,
    )
    spawner._spawned = True  # noqa: SLF001
    app.state.worker_spawner = spawner

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    app.dependency_overrides[get_checkpointer] = lambda: checkpointer
    app.dependency_overrides[get_worker_client] = lambda: worker.client
    app.dependency_overrides[get_circuit_breaker] = lambda: cb
    app.dependency_overrides[get_worker_spawner] = lambda: spawner

    return app, aggregator, worker, checkpointer
