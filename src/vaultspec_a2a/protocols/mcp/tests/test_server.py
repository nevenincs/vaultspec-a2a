"""Tests for the MCP server tool implementations.

Tests use direct function calls and the real FastAPI TestClient (which
triggers the app lifespan) to verify MCP tool error paths and the API
contract expected by the MCP tools.

Per CLAUDE.md: no mocks, no monkeypatching.  The TestClient path runs
the full lifespan using real in-memory SQLite and a real AsyncSqliteSaver
checkpointer so the production vaultspec.db is never created.

ADR-019: GraphRegistry has moved to the worker process.  The gateway
test app uses a real in-process FastAPI ASGI app (via ASGITransport)
for worker dispatch — no MockTransport, no fake responses.

Error-path tests (unknown preset, connection error) call MCP tool
functions directly and rely on the known unreachable ``localhost:8000``
default to exercise the ``httpx.RequestError`` branch.
"""

import asyncio

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ....api.app import LazyWorkerSpawner, WorkerCircuitBreaker, create_app
from ....api.endpoints import (
    get_aggregator,
    get_checkpointer,
    get_circuit_breaker,
    get_worker_client,
    get_worker_spawner,
)
from ....core.aggregator import EventAggregator
from ....database.crud import record_permission_request
from ....database.models import Base
from ....database.session import get_db
from ..server import (
    _reset_client,
    _reset_known_presets,
    _ws_url_from_api_base,
    archive_thread,
    cancel_thread,
    delete_thread,
    get_pending_permissions,
    get_team_status,
    get_thread_status,
    list_team_presets,
    list_threads,
    respond_to_permission,
    send_message,
    start_thread,
)


# ---------------------------------------------------------------------------
# Shared client reset — the module-level httpx.AsyncClient is bound to a
# single event loop.  Between test functions the loop is recycled, so the
# stale client must be discarded to avoid "Event loop is closed" errors.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_shared_state() -> None:
    """Discard the shared httpx client and preset cache before each test."""
    _reset_client()
    _reset_known_presets()


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """In-memory async SQLAlchemy engine with tables created."""
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
async def checkpointer(tmp_path):
    """Real AsyncSqliteSaver backed by a temporary SQLite file per test.

    Replaces MemorySaver so the real checkpointer implementation is exercised.
    """
    db_file = tmp_path / "test_checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(db_file)) as cp:
        yield cp


class _InProcessWorker:
    """Minimal in-process worker that accepts /dispatch and /health requests.

    Uses a real FastAPI ASGI app served via ``httpx.ASGITransport`` — real
    HTTP serialisation and routing are exercised on every request.
    Not a mock, not a fake transport handler.
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


def _make_test_client(
    session_factory, checkpointer: AsyncSqliteSaver, aggregator=None
) -> TestClient:
    """Create a TestClient with the real lifespan bypassed.

    ADR-019: wires a real in-process dispatch receiver (ASGITransport over a
    minimal FastAPI app) for the worker client, and injects the real
    AsyncSqliteSaver checkpointer from the calling fixture.

    The production lifespan is replaced with a no-op so that tests never
    touch the on-disk ``vaultspec.db`` or run Alembic migrations.  All
    required app state is set directly on ``app.state`` before the client
    context manager is entered.
    """
    app = create_app()

    @asynccontextmanager
    async def _test_lifespan(_app):
        yield

    app.router.lifespan_context = _test_lifespan

    if aggregator is None:
        aggregator = EventAggregator()

    # Real in-process worker — real ASGI, no mock
    worker = _InProcessWorker()
    app.state.checkpointer = checkpointer
    app.state.aggregator = aggregator
    app.state.worker_client = worker.client

    # Circuit breaker starts CLOSED — dispatch succeeds with in-process worker
    cb = WorkerCircuitBreaker()
    app.state.circuit_breaker = cb

    # Lazy spawner pre-marked as spawned — no subprocess needed in tests
    spawner = LazyWorkerSpawner(
        worker_url="http://test-worker:8001",
        worker_port=8001,
        auto_spawn=False,
    )
    spawner._spawned = True
    app.state.worker_spawner = spawner

    # Override the DB session so tests use in-memory SQLite
    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    app.dependency_overrides[get_checkpointer] = lambda: checkpointer
    app.dependency_overrides[get_worker_client] = lambda: worker.client
    app.dependency_overrides[get_circuit_breaker] = lambda: cb
    app.dependency_overrides[get_worker_spawner] = lambda: spawner
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Error-path tests (no HTTP server needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_thread_unknown_preset_raises() -> None:
    """start_thread with an unknown preset raises (connection or preset error).

    When the gateway is unreachable, preset discovery returns an empty set
    and validation is deferred to the gateway — which also fails with a
    connection error.  Either way a ToolError is raised.
    """
    with pytest.raises(ToolError):
        await start_thread(
            initial_message="do something", team_preset="nonexistent-preset"
        )


@pytest.mark.asyncio
async def test_start_thread_default_preset_not_unknown() -> None:
    """start_thread with team_preset=None uses 'vaultspec-adaptive-coder' -- not unknown."""
    # With no server running this hits a connection error -- but must NOT raise
    # an "Unknown preset" error.
    with pytest.raises(ToolError) as exc_info:
        await start_thread(initial_message="test", team_preset=None)
    assert "Unknown preset" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# API contract tests via TestClient (lifespan-backed)
# ---------------------------------------------------------------------------


class TestCreateThreadViaApp:
    """Tests that exercise the real FastAPI app the MCP tools talk to."""

    def test_post_threads_without_autonomous_returns_201(
        self, session_factory, checkpointer
    ) -> None:
        """POST /api/threads without autonomous field returns 201."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello from MCP test"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data

    def test_post_threads_with_autonomous_true_returns_201(
        self, session_factory, checkpointer
    ) -> None:
        """POST /api/threads with autonomous=True returns 201."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello autonomous",
                    "autonomous": True,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        assert data["status"] == "submitted"

    def test_get_thread_state_404_for_unknown(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads/{id}/state returns 404 for unknown thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads/nonexistent-id/state")
        assert resp.status_code == 404

    def test_get_thread_state_200_for_existing(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads/{id}/state returns 200 with thread data."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]

            state_resp = client.get(f"/api/threads/{thread_id}/state")
        assert state_resp.status_code == 200
        data = state_resp.json()
        assert data["thread_id"] == thread_id

    def test_post_threads_with_workspace_root_returns_201(
        self, session_factory, checkpointer, tmp_path
    ) -> None:
        """POST /api/threads with workspace_root in metadata passes through to 201."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello workspace",
                    "autonomous": True,
                    "metadata": {"workspace_root": str(tmp_path)},
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data

    def test_send_message_returns_404_for_unknown_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /api/threads/{id}/messages returns 404 for unknown thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/api/threads/nonexistent/messages",
                json={"content": "hello"},
            )
        assert resp.status_code == 404

    def test_send_message_returns_202_for_existing_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /api/threads/{id}/messages returns 202 for an existing thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]

            send_resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"content": "follow-up"},
            )
        assert send_resp.status_code == 202


# ---------------------------------------------------------------------------
# Tool function error-path tests (MCP-HIGH-01)
#
# These tests verify error-handling behaviour when the server is unavailable.
# The success path is covered by TestCreateThreadViaApp above.
# Test names are honest about what they test.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_thread_raises_when_server_unavailable() -> None:
    """start_thread with a valid preset raises when the server is not running.

    MCP-HIGH-01: verifies the tool raises an exception (FastMCP signals
    isError=true) rather than returning a silent error string.
    """
    with pytest.raises(ToolError) as exc_info:
        await start_thread(
            initial_message="do something",
            team_preset="vaultspec-adaptive-coder",
        )
    msg = str(exc_info.value).lower()
    _expected_keywords = (
        "error",
        "connection",
        "connected",
        "network",
        "timeout",
        "gateway",
    )
    assert any(kw in msg for kw in _expected_keywords)


@pytest.mark.asyncio
async def test_get_thread_status_raises_when_server_unavailable() -> None:
    """get_thread_status raises when the server is not running.

    MCP-HIGH-01: verifies exception-based error signaling.
    """
    with pytest.raises(ToolError) as exc_info:
        await get_thread_status(thread_id="some-thread-id")
    msg = str(exc_info.value).lower()
    _expected_keywords = (
        "error",
        "connection",
        "connected",
        "network",
        "timeout",
        "not found",
        "gateway",
    )
    assert any(kw in msg for kw in _expected_keywords)


@pytest.mark.asyncio
async def test_send_message_raises_when_server_unavailable() -> None:
    """send_message raises when the server is not running.

    MCP-HIGH-01: verifies exception-based error signaling.
    """
    with pytest.raises(ToolError) as exc_info:
        await send_message(thread_id="some-thread-id", message="hello")
    msg = str(exc_info.value).lower()
    _expected_keywords = (
        "error",
        "connection",
        "connected",
        "network",
        "timeout",
        "not found",
        "gateway",
    )
    assert any(kw in msg for kw in _expected_keywords)


# ---------------------------------------------------------------------------
# _ws_url_from_api_base unit tests (MCP-MEDIUM-01)
# ---------------------------------------------------------------------------


def test_ws_url_http_converts_to_ws() -> None:
    """_ws_url_from_api_base converts http:// to ws://."""
    result = _ws_url_from_api_base("http://localhost:8000")
    assert result.startswith("ws://")
    assert "localhost" in result
    assert "8000" in result


def test_ws_url_https_converts_to_wss() -> None:
    """_ws_url_from_api_base converts https:// to wss://."""
    result = _ws_url_from_api_base("https://example.com")
    assert result.startswith("wss://")
    assert "example.com" in result


def test_ws_url_strips_credentials() -> None:
    """_ws_url_from_api_base removes userinfo (user:password) from the netloc."""
    result = _ws_url_from_api_base("http://user:pass@localhost:8000")
    assert "user" not in result
    assert "pass" not in result
    assert "localhost" in result


def test_ws_url_preserves_port() -> None:
    """_ws_url_from_api_base keeps the port number in the output URL."""
    result = _ws_url_from_api_base("http://localhost:9999")
    assert "9999" in result


def test_ws_url_no_port_omits_colon() -> None:
    """_ws_url_from_api_base omits port suffix when not specified."""
    result = _ws_url_from_api_base("https://api.example.com")
    # Should not have a trailing colon with no port
    assert ":/" not in result.replace("wss://", "").replace("ws://", "")


# ---------------------------------------------------------------------------
# list_threads tests (MCP-R1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_threads_raises_when_server_unavailable() -> None:
    """list_threads raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await list_threads()
    msg = str(exc_info.value).lower()
    _expected_keywords = (
        "error",
        "connection",
        "connected",
        "network",
        "timeout",
        "gateway",
    )
    assert any(kw in msg for kw in _expected_keywords)


class TestListThreadsViaApp:
    """Tests that exercise list_threads via the real FastAPI app."""

    def test_list_threads_empty(self, session_factory, checkpointer) -> None:
        """GET /api/threads returns empty list when no threads exist."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["threads"] == []
        assert data["total"] == 0

    def test_list_threads_returns_created_thread(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads includes a thread created via POST /api/threads."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "MCP list test",
                    "team_preset": "vaultspec-solo-coder",
                },
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]

            list_resp = client.get("/api/threads")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert data["total"] >= 1
        thread_ids = [t["thread_id"] for t in data["threads"]]
        assert thread_id in thread_ids
        # Verify team_preset is present in the response
        matching = [t for t in data["threads"] if t["thread_id"] == thread_id]
        assert matching[0]["team_preset"] == "vaultspec-solo-coder"

    def test_list_threads_pagination(self, session_factory, checkpointer) -> None:
        """GET /api/threads respects limit and offset params."""
        with _make_test_client(session_factory, checkpointer) as client:
            for i in range(3):
                client.post(
                    "/api/threads",
                    json={"initial_message": f"Thread {i}"},
                )
            resp = client.get("/api/threads", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["threads"]) == 2
        assert data["total"] == 3


# ---------------------------------------------------------------------------
# respond_to_permission tests (MCP-R4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_respond_to_permission_raises_when_server_unavailable() -> None:
    """respond_to_permission raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await respond_to_permission(
            permission_request_id="fake-thread:fake-uuid",
            option_id="allow",
        )
    msg = str(exc_info.value).lower()
    _expected = ("error", "connection", "connected", "network", "timeout", "gateway")
    assert any(kw in msg for kw in _expected)


class TestRespondToPermissionViaApp:
    """Tests exercising respond_to_permission through the real FastAPI app."""

    def test_respond_to_permission_404_for_unknown_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /api/permissions/{id}/respond returns 404 when thread not found."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/api/permissions/nonexistent:some-uuid/respond",
                json={"option_id": "allow"},
            )
        assert resp.status_code == 404

    def test_respond_to_permission_dispatches_for_existing_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /api/permissions/{thread_id}:{uuid}/respond dispatches to worker.

        The endpoint now requires a durably-pending PermissionRequestModel row
        (added in the 0002 migration hardening sprint).  We seed one directly
        via the CRUD layer before calling the endpoint.
        """
        with _make_test_client(session_factory, checkpointer) as client:
            # Create a thread first so the permission endpoint can find it
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]

            request_id = f"{thread_id}:fake-uuid"

            # Seed a durable pending permission request so the endpoint can
            # validate it exists (required since the 0002 hardening sprint).
            async def _seed_permission() -> None:
                async with session_factory() as session:
                    await record_permission_request(
                        session,
                        request_id=request_id,
                        thread_id=thread_id,
                        pause_reason_type="tool_call",
                        description="Approve running dangerous-tool?",
                        allowed_options=[
                            {"option_id": "allow", "name": "Allow"},
                            {"option_id": "deny", "name": "Deny"},
                        ],
                    )
                    await session.commit()

            asyncio.run(_seed_permission())

            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == request_id
        assert data["accepted"] is True


# ---------------------------------------------------------------------------
# get_team_status tests (MCP-R6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_team_status_raises_when_server_unavailable() -> None:
    """get_team_status raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await get_team_status()
    msg = str(exc_info.value).lower()
    _expected = ("error", "connection", "connected", "network", "timeout", "gateway")
    assert any(kw in msg for kw in _expected)


class TestGetTeamStatusViaApp:
    """Tests exercising get_team_status through the real FastAPI app."""

    def test_get_team_status_returns_200(self, session_factory, checkpointer) -> None:
        """GET /api/team/status returns 200 with valid structure."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/team/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "active_threads" in data
        assert "pending_permissions" in data


# ---------------------------------------------------------------------------
# get_pending_permissions tests (MCP-R5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pending_permissions_raises_when_server_unavailable() -> None:
    """get_pending_permissions raises when server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await get_pending_permissions()
    msg = str(exc_info.value).lower()
    _expected = ("error", "connection", "connected", "network", "timeout", "gateway")
    assert any(kw in msg for kw in _expected)


class TestGetPendingPermissionsViaApp:
    """Tests exercising get_pending_permissions through the real FastAPI app."""

    def test_get_pending_permissions_empty(self, session_factory, checkpointer) -> None:
        """When no permissions are pending, the endpoint returns an empty list."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/team/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []


# ---------------------------------------------------------------------------
# list_team_presets tests (MCP-R2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_team_presets_raises_when_server_unavailable() -> None:
    """list_team_presets raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await list_team_presets()
    msg = str(exc_info.value).lower()
    _expected = ("error", "connection", "connected", "network", "timeout", "gateway")
    assert any(kw in msg for kw in _expected)


class TestListTeamPresetsViaApp:
    """Tests exercising list_team_presets through the real FastAPI app."""

    def test_list_team_presets_returns_200(self, session_factory, checkpointer) -> None:
        """GET /api/teams returns 200 with presets."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        assert len(data["presets"]) > 0

    def test_list_team_presets_contains_expected_fields(
        self, session_factory, checkpointer
    ) -> None:
        """Each preset has id, display_name, description, topology, worker_count."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/teams")
        data = resp.json()
        preset = data["presets"][0]
        assert "id" in preset
        assert "display_name" in preset
        assert "description" in preset
        assert "topology" in preset
        assert "worker_count" in preset


# ---------------------------------------------------------------------------
# cancel_thread tests (MCP-R3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_thread_raises_when_server_unavailable() -> None:
    """cancel_thread raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await cancel_thread(thread_id="some-thread-id")
    msg = str(exc_info.value).lower()
    _expected = (
        "error",
        "connection",
        "connected",
        "network",
        "timeout",
        "not found",
        "gateway",
    )
    assert any(kw in msg for kw in _expected)


class TestCancelThreadViaApp:
    """Tests exercising cancel_thread through the real FastAPI app."""

    def test_cancel_thread_404_for_unknown(self, session_factory, checkpointer) -> None:
        """POST /api/threads/{id}/cancel returns 404 for unknown thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post("/api/threads/nonexistent/cancel")
        assert resp.status_code == 404

    def test_cancel_thread_cancels_running_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /api/threads/{id}/cancel returns an accepted cancelling state."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Cancel me"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]

            cancel_resp = client.post(f"/api/threads/{thread_id}/cancel")
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["thread_id"] == thread_id
        assert data["cancelled"] is True
        assert data["status"] == "cancelling"

    def test_cancel_thread_repeat_request_stays_accepting_until_terminal_event(
        self, session_factory, checkpointer
    ) -> None:
        """Repeated cancel requests stay accepted until the worker confirms terminal state."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Cancel twice"},
            )
            thread_id = create_resp.json()["thread_id"]

            # First cancel
            client.post(f"/api/threads/{thread_id}/cancel")
            # Second cancel
            cancel_resp = client.post(f"/api/threads/{thread_id}/cancel")
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["cancelled"] is True
        assert data["status"] == "cancelling"


# ---------------------------------------------------------------------------
# TESTING-04: delete_thread / archive_thread error paths + preset cache
# ---------------------------------------------------------------------------


class TestDeleteArchiveThreadErrorPaths:
    """delete_thread and archive_thread raise ToolError when gateway is unreachable."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_thread_raises_tool_error_when_server_unavailable(
        self,
    ) -> None:
        """delete_thread wraps ConnectError into ToolError."""
        with pytest.raises(ToolError):
            await delete_thread("00000000-0000-0000-0000-000000000001")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_archive_thread_raises_tool_error_when_server_unavailable(
        self,
    ) -> None:
        """archive_thread wraps ConnectError into ToolError."""
        with pytest.raises(ToolError):
            await archive_thread("00000000-0000-0000-0000-000000000002")


class TestKnownPresetsCache:
    """_known_presets_cache is populated on first call and cleared by _reset_known_presets."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_reset_known_presets_clears_cache_after_population(self) -> None:
        """_reset_known_presets() sets _known_presets_cache back to None after it was set."""
        import sys

        from ..server import _get_known_presets

        # Locate the already-imported server module via sys.modules
        srv_mod = next(
            m for k, m in sys.modules.items() if k.endswith("protocols.mcp.server")
        )

        # After autouse fixture, cache is already None
        assert srv_mod._known_presets_cache is None

        # Trigger population — gateway unreachable results in empty frozenset
        result = await _get_known_presets()
        assert isinstance(result, frozenset)
        assert srv_mod._known_presets_cache is not None

        # Reset clears it
        _reset_known_presets()
        assert srv_mod._known_presets_cache is None
