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
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
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

type SessionFactory = async_sessionmaker[AsyncSession]
type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)

# A recorded dispatch body, whose VALUES stay `Any` deliberately. Typing them as
# `JsonValue` describes the wire shape accurately but makes the payload unusable
# to the tests that consume it: a dispatch is navigated several levels deep
# (``d["option_id"]["answers"]["scope"]``), and every step off a recursive union
# is unsubscriptable because the union admits `int`, `str` and `None`. The
# precision is real and unhelpful here - it forces a cast or a narrowing branch
# at each of ~45 assertion sites, which buys no safety in a test that is
# asserting the very structure it would be narrowing. The dict itself stays
# typed, so the container contract is still stated.
type DispatchPayload = dict[str, Any]

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
async def engine(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[AsyncEngine]:
    """File-backed async SQLAlchemy engine with all tables created."""
    case_dir = tmp_path_factory.mktemp("api-test-db")
    db_file = case_dir / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> SessionFactory:
    """Async session factory bound to the file-backed engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Provide a fresh async session for direct DB assertions."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# Real checkpointer fixture — AsyncSqliteSaver backed by a per-test file
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def checkpointer(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[AsyncSqliteSaver]:
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
        self.dispatches: list[DispatchPayload] = []
        self.dispatch_received = asyncio.Event()
        self.release_dispatch = asyncio.Event()
        self.release_dispatch.set()
        self._at_capacity = False

        _app = FastAPI()

        async def _dispatch(request: Request) -> JSONResponse | dict[str, str]:
            expected = settings.internal_token
            if expected is not None:
                authorization = request.headers.get("authorization")
                if authorization != f"Bearer {expected}":
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid internal token"},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            body = cast("DispatchPayload", await request.json())
            self.dispatches.append(body)
            self.dispatch_received.set()
            await self.release_dispatch.wait()
            if self._at_capacity:
                # Byte-for-byte the refusal the real worker returns once its
                # concurrent-thread cap is reached, so the gateway classifies a
                # genuine definite non-delivery from a genuine HTTP response.
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Worker at capacity — too many concurrent threads"
                    },
                )
            thread_id = body.get("thread_id", "")
            if not isinstance(thread_id, str):
                thread_id = ""
            return {"status": "dispatched", "thread_id": thread_id}

        async def _health() -> dict[str, str]:
            return {"status": "ok"}

        _app.add_api_route(
            "/dispatch",
            _dispatch,
            methods=["POST"],
            response_model=None,
        )
        _app.add_api_route("/health", _health, methods=["GET"])

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

    def refuse_at_capacity(self) -> None:
        """Answer every further dispatch with the worker's real 429 refusal."""
        self._at_capacity = True


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

type AppFixture = tuple[FastAPI, EventAggregator, _InProcessWorker, AsyncSqliteSaver]


_SESSION_CATALOG_SERVICE: Any = None


def _session_catalog_service() -> Any:
    """Return the process-wide provider catalog service.

    Built once and reused. See the note at its injection site in `make_app` for
    why per-app construction was the wrong default.
    """
    global _SESSION_CATALOG_SERVICE
    if _SESSION_CATALOG_SERVICE is None:
        from datetime import timedelta

        from ...providers.provider_catalog_service import ProviderCatalogService

        _SESSION_CATALOG_SERVICE = ProviderCatalogService(ttl=timedelta(hours=6))
    return _SESSION_CATALOG_SERVICE


def make_app(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    aggregator: EventAggregator | None = None,
) -> AppFixture:
    """Create a test FastAPI app with explicit app-state injection.

    Wires a real in-process dispatch receiver (ASGITransport over a
    minimal FastAPI app) for the worker client, and injects the real
    AsyncSqliteSaver checkpointer from the calling fixture.

    Returns:
        Tuple of (app, aggregator, worker, checkpointer).
    """

    @asynccontextmanager
    async def _test_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield

    app = create_app(
        lifespan=_test_lifespan,
        allow_unauthenticated_v1_for_testing=True,
    )

    if aggregator is None:
        aggregator = EventAggregator()

    worker = _InProcessWorker()

    # ONE catalog service for the whole session, not one per app.
    #
    # The service owns a real TTL cache, but `make_app` builds a fresh app per
    # test, so a per-app service threw that cache away and re-probed every
    # provider lane on every test - measured at ~15s each, which dominated the
    # runtime of every suite that starts a run. The probe result is a property
    # of the machine and workspace, not of the app under test, so rebuilding it
    # per test is pure waste rather than isolation.
    #
    # Sharing the real production object keeps the real code path: the cache
    # being exercised is the one that ships, its TTL is simply widened past the
    # length of a suite so a long run does not re-probe mid-flight.
    app.state.provider_catalog_service = _session_catalog_service()

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


_CATALOG_FIELD_CACHE: dict[str, dict[str, Any]] = {}


def catalog_run_fields(
    client: Any, *, workspace_root: str | None = None
) -> dict[str, Any]:
    """Return the run-start fields an explicit catalog selection now requires.

    Run-start refuses a body without a ``selection``, and revalidates that
    selection against the catalog SERVED FOR ITS WORKSPACE - so a hand-written
    reference is refused even when its shape is perfect. This derives one from
    the live served catalog the way a real client must: read the catalog, take a
    lane the gateway actually reports as selectable, and reference that lane's
    own revision and entry.

    A canned literal would be the tempting shortcut and would be wrong twice
    over: it would break whenever the catalog's revision moved, and it would let
    a test assert against a lane the gateway would never serve. Deriving keeps
    the fixture honest about what the gateway is offering at that moment.

    ``workspace_root`` is returned alongside because the same gate refuses a
    selection with no existing workspace to anchor it in.
    """
    root = workspace_root or str(Path.cwd())
    cached = _CATALOG_FIELD_CACHE.get(root)
    if cached is not None:
        return {
            "selection": dict(cached["selection"]),
            "metadata": dict(cached["metadata"]),
        }
    response = client.get("/v1/provider-catalog", params={"workspace_root": root})
    assert response.status_code == 200, response.text
    record = next(
        item
        for item in response.json()["providers"]
        if item["health"]["selectable"] and item["catalog"]["models"]
    )
    catalog = record["catalog"]
    fields: dict[str, Any] = {
        "selection": {
            "schema_version": 1,
            "provider_id": record["provider_id"],
            "execution_mode": record["execution_mode"],
            "catalog_revision": catalog["state"]["revision"],
            "entry_id": catalog["models"][0]["entry_id"],
            "controls": {},
        },
        "metadata": {"workspace_root": root},
    }
    _CATALOG_FIELD_CACHE[root] = fields
    return {
        "selection": dict(fields["selection"]),
        "metadata": dict(fields["metadata"]),
    }
