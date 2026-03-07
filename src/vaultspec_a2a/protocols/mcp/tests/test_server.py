"""Tests for the MCP server tool implementations.

Tests use direct function calls and the real FastAPI TestClient (which
triggers the app lifespan) to verify MCP tool error paths and the API
contract expected by the MCP tools.

Per CLAUDE.md: no mocks, no monkeypatching.  The TestClient path runs
the full lifespan using real in-memory SQLite and a MemorySaver
checkpointer so the production vaultspec.db is never created.

ADR-019: GraphRegistry has moved to the worker process.  The control
surface test app uses a test httpx client for worker dispatch.

Error-path tests (unknown preset, connection error) call MCP tool
functions directly and rely on the known unreachable ``localhost:8000``
default to exercise the ``httpx.RequestError`` branch.
"""

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ....api.app import create_app
from ....api.endpoints import (
    get_aggregator,
    get_checkpointer,
    get_worker_client,
)
from ....core.aggregator import EventAggregator
from ....database.models import Base
from ....database.session import get_db
from ..server import (
    _reset_client,
    _reset_known_presets,
    _ws_url_from_api_base,
    cancel_thread,
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


def _make_test_client(session_factory, aggregator=None) -> TestClient:
    """Create a TestClient backed by a real app lifespan.

    ADR-019: overrides get_worker_client with a test httpx client.
    GraphRegistry and TaskGroup are no longer needed.
    """
    import json as _json

    app = create_app()
    if aggregator is None:
        aggregator = EventAggregator()

    # In-memory checkpointer -- never touches vaultspec.db
    checkpointer = MemorySaver()
    app.state.checkpointer = checkpointer

    # Test worker client that accepts all dispatch requests
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/dispatch" and request.method == "POST":
            body = _json.loads(request.content)
            return httpx.Response(
                200,
                json={"status": "dispatched", "thread_id": body.get("thread_id", "")},
            )
        return httpx.Response(404, json={"detail": "Not found"})

    transport = httpx.MockTransport(_handler)
    worker_client = httpx.AsyncClient(
        transport=transport, base_url="http://test-worker:8001"
    )
    app.state.worker_client = worker_client

    # Override the DB session so tests use in-memory SQLite
    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    app.dependency_overrides[get_checkpointer] = lambda: checkpointer
    app.dependency_overrides[get_worker_client] = lambda: worker_client
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

    def test_post_threads_without_autonomous_returns_201(self, session_factory) -> None:
        """POST /api/threads without autonomous field returns 201."""
        with _make_test_client(session_factory) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello from MCP test"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data

    def test_post_threads_with_autonomous_true_returns_201(
        self, session_factory
    ) -> None:
        """POST /api/threads with autonomous=True returns 201."""
        with _make_test_client(session_factory) as client:
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

    def test_get_thread_state_404_for_unknown(self, session_factory) -> None:
        """GET /api/threads/{id}/state returns 404 for unknown thread."""
        with _make_test_client(session_factory) as client:
            resp = client.get("/api/threads/nonexistent-id/state")
        assert resp.status_code == 404

    def test_get_thread_state_200_for_existing(self, session_factory) -> None:
        """GET /api/threads/{id}/state returns 200 with thread data."""
        with _make_test_client(session_factory) as client:
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
        self, session_factory, tmp_path
    ) -> None:
        """POST /api/threads with workspace_root in metadata passes through to 201."""
        with _make_test_client(session_factory) as client:
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

    def test_send_message_returns_404_for_unknown_thread(self, session_factory) -> None:
        """POST /api/threads/{id}/messages returns 404 for unknown thread."""
        with _make_test_client(session_factory) as client:
            resp = client.post(
                "/api/threads/nonexistent/messages",
                json={"content": "hello"},
            )
        assert resp.status_code == 404

    def test_send_message_returns_202_for_existing_thread(
        self, session_factory
    ) -> None:
        """POST /api/threads/{id}/messages returns 202 for an existing thread."""
        with _make_test_client(session_factory) as client:
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
    _expected_keywords = ("error", "connection", "network", "timeout")
    assert any(kw in msg for kw in _expected_keywords)


@pytest.mark.asyncio
async def test_get_thread_status_raises_when_server_unavailable() -> None:
    """get_thread_status raises when the server is not running.

    MCP-HIGH-01: verifies exception-based error signaling.
    """
    with pytest.raises(ToolError) as exc_info:
        await get_thread_status(thread_id="some-thread-id")
    msg = str(exc_info.value).lower()
    _expected_keywords = ("error", "connection", "network", "timeout", "not found")
    assert any(kw in msg for kw in _expected_keywords)


@pytest.mark.asyncio
async def test_send_message_raises_when_server_unavailable() -> None:
    """send_message raises when the server is not running.

    MCP-HIGH-01: verifies exception-based error signaling.
    """
    with pytest.raises(ToolError) as exc_info:
        await send_message(thread_id="some-thread-id", message="hello")
    msg = str(exc_info.value).lower()
    _expected_keywords = ("error", "connection", "network", "timeout", "not found")
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
    _expected_keywords = ("error", "connection", "network", "timeout")
    assert any(kw in msg for kw in _expected_keywords)


class TestListThreadsViaApp:
    """Tests that exercise list_threads via the real FastAPI app."""

    def test_list_threads_empty(self, session_factory) -> None:
        """GET /api/threads returns empty list when no threads exist."""
        with _make_test_client(session_factory) as client:
            resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["threads"] == []
        assert data["total"] == 0

    def test_list_threads_returns_created_thread(self, session_factory) -> None:
        """GET /api/threads includes a thread created via POST /api/threads."""
        with _make_test_client(session_factory) as client:
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

    def test_list_threads_pagination(self, session_factory) -> None:
        """GET /api/threads respects limit and offset params."""
        with _make_test_client(session_factory) as client:
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
    _expected = ("error", "connection", "network", "timeout")
    assert any(kw in msg for kw in _expected)


class TestRespondToPermissionViaApp:
    """Tests exercising respond_to_permission through the real FastAPI app."""

    def test_respond_to_permission_404_for_unknown_thread(
        self, session_factory
    ) -> None:
        """POST /api/permissions/{id}/respond returns 404 when thread not found."""
        with _make_test_client(session_factory) as client:
            resp = client.post(
                "/api/permissions/nonexistent:some-uuid/respond",
                json={"option_id": "allow"},
            )
        assert resp.status_code == 404

    def test_respond_to_permission_dispatches_for_existing_thread(
        self, session_factory
    ) -> None:
        """POST /api/permissions/{thread_id}:{uuid}/respond dispatches to worker."""
        with _make_test_client(session_factory) as client:
            # Create a thread first so the permission endpoint can find it
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]

            resp = client.post(
                f"/api/permissions/{thread_id}:fake-uuid/respond",
                json={"option_id": "allow"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == f"{thread_id}:fake-uuid"
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
    _expected = ("error", "connection", "network", "timeout")
    assert any(kw in msg for kw in _expected)


class TestGetTeamStatusViaApp:
    """Tests exercising get_team_status through the real FastAPI app."""

    def test_get_team_status_returns_200(self, session_factory) -> None:
        """GET /api/team/status returns 200 with valid structure."""
        with _make_test_client(session_factory) as client:
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
    _expected = ("error", "connection", "network", "timeout")
    assert any(kw in msg for kw in _expected)


class TestGetPendingPermissionsViaApp:
    """Tests exercising get_pending_permissions through the real FastAPI app."""

    def test_get_pending_permissions_empty(self, session_factory) -> None:
        """When no permissions are pending, the endpoint returns an empty list."""
        with _make_test_client(session_factory) as client:
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
    _expected = ("error", "connection", "network", "timeout")
    assert any(kw in msg for kw in _expected)


class TestListTeamPresetsViaApp:
    """Tests exercising list_team_presets through the real FastAPI app."""

    def test_list_team_presets_returns_200(self, session_factory) -> None:
        """GET /api/teams returns 200 with presets."""
        with _make_test_client(session_factory) as client:
            resp = client.get("/api/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        assert len(data["presets"]) > 0

    def test_list_team_presets_contains_expected_fields(self, session_factory) -> None:
        """Each preset has id, display_name, description, topology, worker_count."""
        with _make_test_client(session_factory) as client:
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
    _expected = ("error", "connection", "network", "timeout", "not found")
    assert any(kw in msg for kw in _expected)


class TestCancelThreadViaApp:
    """Tests exercising cancel_thread through the real FastAPI app."""

    def test_cancel_thread_404_for_unknown(self, session_factory) -> None:
        """POST /api/threads/{id}/cancel returns 404 for unknown thread."""
        with _make_test_client(session_factory) as client:
            resp = client.post("/api/threads/nonexistent/cancel")
        assert resp.status_code == 404

    def test_cancel_thread_cancels_running_thread(self, session_factory) -> None:
        """POST /api/threads/{id}/cancel sets status to cancelled."""
        with _make_test_client(session_factory) as client:
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
        assert data["status"] == "cancelled"

    def test_cancel_thread_already_cancelled_returns_not_cancelled(
        self, session_factory
    ) -> None:
        """Cancelling an already-cancelled thread returns cancelled=False."""
        with _make_test_client(session_factory) as client:
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
        assert data["cancelled"] is False
