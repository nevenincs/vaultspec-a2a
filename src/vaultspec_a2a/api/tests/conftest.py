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

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

import httpx
import pytest
import pytest_asyncio
import uvicorn
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

from ...conftest import materialize_schema
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.config import settings
from ...control.event_handlers import CheckpointPruneRegistry
from ...control.worker_management import LazyWorkerSpawner
from ...database import create_thread
from ...providers.factory import ProviderCatalogRegistration, ProviderFactory
from ...providers.in_process_catalog import served_in_process_lanes
from ...streaming.aggregator import EventAggregator
from ...tests._write_authority import make_test_write_authority
from ..app import create_app
from ..dependencies import LIFECYCLE_CAPABILITY_HEADER
from ..internal import internal_router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

    from starlette.types import ASGIApp, Receive, Scope, Send

    from ...providers.provider_catalog_service import ProviderCatalogService
    from ...thread.enums import ThreadStatus

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
    # Copy the session schema template instead of replaying the DDL. The DDL is
    # byte-identical every time and cost ~340ms - more than this package's tests
    # spent doing their actual work. The database is still per-test and still
    # real; only its materialization changes.
    db_file = materialize_schema(case_dir / "test.db")
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
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


async def seed_run_with_status(
    session_factory: SessionFactory, thread_id: str, status: ThreadStatus
) -> None:
    """Persist one run in *status* for tests that read durable stream state.

    The stream body reads the run's status from the database rather than being
    handed one, so a test that wants a stream to see a given status has to put
    that status where the stream looks.
    """
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=status,
        )
        await session.commit()


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

# The credentials every ``make_app`` gateway holds. Known constants, so a test
# that wants to present them, or to present something else, can name them.
SEATED_ATTACH_TOKEN = "seated-attach-token-0123456789abcdef"
SEATED_LIFECYCLE_CAPABILITY = "seated-lifecycle-capability-0123456789abcdef"

_AUTHORIZATION = b"authorization"
_CAPABILITY = LIFECYCLE_CAPABILITY_HEADER.lower().encode("latin-1")


class _SeatedCredentials:
    """Present the app's own credentials on every request that carries none.

    Route-behaviour suites reach the gateway through clients of their own - a
    ``TestClient``, an ASGI transport, a socket - that do not authenticate. This
    layer is the credentialed client they share: it adds the attach bearer and the
    lifecycle capability the app currently holds, so every request still crosses
    the production gates and is verified by the production comparison. A header a
    request already carries is never replaced, so presenting a wrong credential is
    still refused. The relay plane is skipped because it verifies a different
    credential on the same ``Authorization`` header.

    Credentials are read from app state per request rather than captured, since
    suites reseat them after the factory returns.
    """

    def __init__(self, app: ASGIApp, *, owner: FastAPI) -> None:
        self._app = app
        self._owner = owner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not scope["path"].startswith(
            internal_router.prefix
        ):
            scope = {**scope, "headers": self._credentialed(scope["headers"])}
        await self._app(scope, receive, send)

    def _credentialed(
        self, headers: list[tuple[bytes, bytes]]
    ) -> list[tuple[bytes, bytes]]:
        presented = {name for name, _ in headers}
        credentialed = list(headers)
        token = getattr(self._owner.state, "v1_service_token", None)
        if isinstance(token, str) and token and _AUTHORIZATION not in presented:
            credentialed.append((_AUTHORIZATION, f"Bearer {token}".encode()))
        capability = getattr(self._owner.state, "lifecycle_capability", None)
        if isinstance(capability, str) and capability and _CAPABILITY not in presented:
            credentialed.append((_CAPABILITY, capability.encode()))
        return credentialed


_session_catalog_service_cache: ProviderCatalogService | None = None


class _InProcessCatalogFactory(ProviderFactory):
    """Use production registrations without probing external provider CLIs."""

    @override
    def catalog_registrations(
        self, workspace_root: Path, *, serve_in_process_lanes: bool | None = None
    ) -> tuple[ProviderCatalogRegistration, ...]:
        registrations = super().catalog_registrations(
            workspace_root, serve_in_process_lanes=serve_in_process_lanes
        )
        in_process = set(
            served_in_process_lanes(
                armed=bool(serve_in_process_lanes),
                mock_api_base=settings.mock_api_base,
            )
        )
        return tuple(
            registration
            for registration in registrations
            if registration.key in in_process
        )


def _session_catalog_service() -> ProviderCatalogService:
    """Return the process-wide provider catalog service, serving in-process lanes.

    Built once and reused. See the note at its injection site in `make_app` for
    why per-app construction was the wrong default.

    The in-process lanes are armed through the CONSTRUCTOR, never the process
    environment. These suites spawn real gateway subprocesses, and the
    environment is inherited: arming a lane process-wide for this service would
    silently rearm it for every child and change the lane inventory served to
    tests that have nothing to do with selection. The argument declares this
    caller's posture and reaches nothing else.

    Arming at all is what lets the run-bearing fixtures below select a lane that
    bills nothing. Unarmed, the only selectable lane on a developer machine
    holding a live provider session is that real provider - so every suite that
    starts a run was freezing a metered lane to assert on gateway plumbing.
    """
    global _session_catalog_service_cache
    if _session_catalog_service_cache is None:
        from datetime import timedelta

        from ...providers.provider_catalog_service import ProviderCatalogService

        _session_catalog_service_cache = ProviderCatalogService(
            factory=_InProcessCatalogFactory(),
            ttl=timedelta(hours=6),
            serve_in_process_lanes=True,
        )
    return _session_catalog_service_cache


def make_app(
    session_factory: SessionFactory,
    checkpointer: AsyncSqliteSaver,
    aggregator: EventAggregator | None = None,
    *,
    stamp_credentials: bool = True,
) -> AppFixture:
    """Create a test FastAPI app with explicit app-state injection.

    Wires a real in-process dispatch receiver (ASGITransport over a
    minimal FastAPI app) for the worker client, and injects the real
    AsyncSqliteSaver checkpointer from the calling fixture.

    The gateway holds ``SEATED_ATTACH_TOKEN`` and ``SEATED_LIFECYCLE_CAPABILITY``
    and enforces them through the production gates. By default every request
    that presents no credential of its own is sent with them; pass
    ``stamp_credentials=False`` for a test that exercises the gates themselves
    and so must present exactly what it chooses, or nothing.

    Returns:
        Tuple of (app, aggregator, worker, checkpointer).
    """

    @asynccontextmanager
    async def _test_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield

    app = create_app(lifespan=_test_lifespan)
    app.state.v1_service_token = SEATED_ATTACH_TOKEN
    app.state.lifecycle_capability = SEATED_LIFECYCLE_CAPABILITY
    if stamp_credentials:
        app.add_middleware(cast("Any", _SeatedCredentials), owner=app)

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
    # The gateway lifespan seats one beside the store it prunes through, and a
    # relayed terminal schedules nothing without it.
    app.state.checkpoint_prunes = CheckpointPruneRegistry()

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


@asynccontextmanager
async def _live_server(app: FastAPI) -> AsyncGenerator[str]:
    """Serve *app* on an ephemeral loopback port and yield its base URL.

    A real uvicorn server on a real TCP socket, not ``ASGITransport``: an SSE
    consumer must read frames while the producer is still emitting, and the
    in-memory transport buffers a whole response before returning one.
    """
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started and server.servers:
                break
            await asyncio.sleep(0.01)
        assert server.started and server.servers, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5.0)
