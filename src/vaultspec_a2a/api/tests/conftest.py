"""Middleware test configuration + shared fixtures for api/tests/.

Centralises engine, session_factory, session, checkpointer, and make_app so
that all test modules use the same isolated file-backed SQLite setup and
app-state injection.

The gateway no longer runs agent execution locally.  Tests wire a
real in-process dispatch receiver (a minimal FastAPI ASGI app served via
``httpx.ASGITransport``) so that HTTP serialisation and routing are exercised
without a live worker process.  No ``MockTransport``, no ``unittest.mock``.

The ``checkpointer`` fixture uses ``AsyncSqliteSaver`` backed by a per-test
SQLite file so that gateway read-path enrichment exercises the real
checkpointer implementation, not a ``MemorySaver`` stub.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.config import settings
from ...control.worker_management import LazyWorkerSpawner
from ...database.models import Base
from ...streaming.aggregator import EventAggregator
from ..app import create_app

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


# API tests are middleware-layer; they drive the real SQLite/ASGI fixtures below.
_PURE_FILES: frozenset[str] = frozenset()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark tests here as ``middleware`` (plus ``unit`` for the pure-logic files)."""
    for item in items:
        if not str(item.path).startswith(_PACKAGE_DIR):
            continue
        item.add_marker(pytest.mark.middleware)
        if item.path.name in _PURE_FILES:
            item.add_marker(pytest.mark.unit)


__all__: list[str] = []


# ---------------------------------------------------------------------------
# Engine / Session fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine(tmp_path_factory: pytest.TempPathFactory):
    """File-backed async SQLAlchemy engine with all tables created."""
    case_dir = tmp_path_factory.mktemp("api-test-db")
    db_file = case_dir / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Async session factory bound to the file-backed engine."""
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
async def checkpointer(tmp_path_factory: pytest.TempPathFactory):
    """Real AsyncSqliteSaver backed by a temporary SQLite file per test.

    Replaces the former MemorySaver stub so that gateway read-path enrichment
    exercises the real checkpointer implementation (AsyncSqliteSaver).
    """
    case_dir = tmp_path_factory.mktemp("api-test-checkpoints")
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
        self.dispatch_received = asyncio.Event()
        self.release_dispatch = asyncio.Event()
        self.release_dispatch.set()

        _app = FastAPI()

        @_app.post("/dispatch")
        async def _dispatch(request: Request):
            expected = settings.internal_token
            if expected is not None:
                authorization = request.headers.get("authorization")
                if authorization != f"Bearer {expected}":
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid internal token"},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            body = await request.json()
            self.dispatches.append(body)
            self.dispatch_received.set()
            await self.release_dispatch.wait()
            return {"status": "dispatched", "thread_id": body.get("thread_id", "")}

        @_app.get("/health")
        async def _health() -> dict:
            return {"status": "ok"}

        self._client = httpx.AsyncClient(
            transport=ASGITransport(app=_app),
            base_url="http://test-worker:8001",
            headers=(
                {"Authorization": f"Bearer {settings.internal_token}"}
                if settings.internal_token is not None
                else None
            ),
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the httpx client backed by the in-process worker app."""
        return self._client

    def clear(self) -> None:
        """Clear all recorded dispatch requests."""
        self.dispatches.clear()

    def hold_dispatch_response(self) -> None:
        """Pause a real dispatch response after its request has been recorded."""
        self.dispatch_received.clear()
        self.release_dispatch.clear()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def make_app(
    session_factory,
    checkpointer: AsyncSqliteSaver,
    aggregator: EventAggregator | None = None,
) -> tuple:
    """Create a test FastAPI app with explicit app-state injection.

    Wires a real in-process dispatch receiver (ASGITransport over a
    minimal FastAPI app) for the worker client, and injects the real
    AsyncSqliteSaver checkpointer from the calling fixture.

    Returns:
        Tuple of (app, aggregator, worker, checkpointer).
    """

    @asynccontextmanager
    async def _test_lifespan(_app):
        yield

    app = create_app(
        lifespan=_test_lifespan,
        allow_unauthenticated_v1_for_testing=True,
    )

    if aggregator is None:
        aggregator = EventAggregator()

    worker = _InProcessWorker()

    # Store singletons in app.state so WebSocket handlers can read them
    app.state.aggregator = aggregator
    app.state.checkpointer = checkpointer

    # In-process worker client — real ASGI, no mock
    app.state.worker_client = worker.client

    # circuit breaker for dispatch calls
    cb = WorkerCircuitBreaker(
        failure_threshold=settings.cb_failure_threshold,
        recovery_timeout=settings.cb_recovery_timeout_seconds,
    )
    app.state.circuit_breaker = cb

    # PHASE-1a: lazy worker spawner — pre-marked as spawned for tests
    spawner = LazyWorkerSpawner(
        worker_url="http://test-worker:8001",
        worker_port=8001,
        auto_spawn=False,
    )
    spawner.replace_process(None)
    app.state.worker_spawner = spawner
    app.state.db_session_factory = session_factory

    return app, aggregator, worker, checkpointer
