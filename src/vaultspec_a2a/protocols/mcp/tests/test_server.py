"""Tests for the MCP server tool implementations.

Tests use direct function calls and the real FastAPI TestClient (which
triggers the app lifespan) to verify MCP tool error paths and the API
contract expected by the MCP tools.

Per CLAUDE.md: no mocks, no monkeypatching.  The TestClient path runs
the full lifespan using real in-memory SQLite and a real AsyncSqliteSaver
checkpointer so the production vaultspec.db is never created.

GraphRegistry has moved to the worker process.  The gateway
test app uses a real in-process FastAPI ASGI app (via ASGITransport)
for worker dispatch — no MockTransport, no fake responses.

Error-path tests (unknown preset, connection error) call MCP tool
functions directly against an unreachable gateway URL (an ASGI
``http://testserver`` base with no live transport) to exercise the
``httpx.RequestError`` branch — never a hardcoded live-service port, so a
resident gateway on its real port can never accidentally satisfy them.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

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

from ....api.app import create_app
from ....control.circuit_breaker import WorkerCircuitBreaker
from ....control.config import settings
from ....control.worker_management import LazyWorkerSpawner
from ....database import (
    create_thread,
    record_permission_request,
    record_permission_response_submission,
)
from ....database.models import (
    Base,
    PermissionRequestModel,
    ThreadExecutionStateModel,
    ThreadModel,
)
from ....streaming.aggregator import EventAggregator
from .. import _http as mcp_http
from .._http import _reset_client, _reset_known_presets
from ..tools.discovery import (
    get_pending_permissions,
    get_team_status,
    list_team_presets,
    respond_to_permission,
)
from ..tools.messaging import send_message
from ..tools.thread_lifecycle import (
    archive_thread,
    cancel_thread,
    delete_thread,
    start_thread,
)
from ..tools.thread_query import (
    _ws_url_from_api_base,
    get_thread_status,
    list_threads,
)

_GATEWAY_TOKEN = "mcp-gateway-attach-token-0123456789abcdef"

# ---------------------------------------------------------------------------
# Shared client reset — the module-level httpx.AsyncClient is bound to a
# single event loop.  Between test functions the loop is recycled, so the
# stale client must be discarded to avoid "Event loop is closed" errors.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_shared_state():
    """Seat real gateway auth and discard shared MCP state around each test."""
    original_gateway_token = settings.gateway_service_token
    settings.gateway_service_token = _GATEWAY_TOKEN
    _reset_client()
    _reset_known_presets()
    try:
        yield
    finally:
        _reset_client()
        _reset_known_presets()
        settings.gateway_service_token = original_gateway_token


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
async def checkpointer(tmp_path_factory: pytest.TempPathFactory):
    """Real AsyncSqliteSaver backed by a temporary SQLite file per test.

    Replaces MemorySaver so the real checkpointer implementation is exercised.
    """
    case_dir = tmp_path_factory.mktemp("mcp-test-checkpoints")
    db_file = case_dir / "test_checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(db_file)) as cp:
        yield cp


@pytest.fixture
def workspace_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a pytest-managed workspace path for MCP test operations."""
    return tmp_path_factory.mktemp("mcp-test-workspaces")


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

    Wires a real in-process dispatch receiver (ASGITransport over a
    minimal FastAPI app) for the worker client, and injects the real
    AsyncSqliteSaver checkpointer from the calling fixture.

    The production lifespan is replaced with a no-op so that tests never
    touch the on-disk ``vaultspec.db`` or run Alembic migrations.  All
    required app state is set directly on ``app.state`` before the client
    context manager is entered.

    The app is created with the sanctioned ``allow_unauthenticated_v1_for_testing``
    escape hatch (the same seam ``api/tests/conftest.py`` uses) because the MCP
    tool surface carries no gateway bearer; these are route-behaviour tests, not
    tests of the ``/api`` attach gate, which is covered in ``api/tests``.
    """

    @asynccontextmanager
    async def _test_lifespan(_app):
        yield

    app = create_app(lifespan=_test_lifespan)
    app.state.v1_service_token = _GATEWAY_TOKEN

    if aggregator is None:
        aggregator = EventAggregator()

    # Real in-process worker — real ASGI, no mock
    worker = _InProcessWorker()
    app.state.checkpointer = checkpointer
    app.state.aggregator = aggregator
    app.state.worker_client = worker.client

    # Circuit breaker starts CLOSED — dispatch succeeds with in-process worker
    cb = WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
    app.state.circuit_breaker = cb

    # Mark the worker as already available via the public spawner API.
    spawner = LazyWorkerSpawner(
        worker_url="http://test-worker:8001",
        worker_port=8001,
        auto_spawn=False,
    )
    spawner.replace_process(None)
    app.state.worker_spawner = spawner

    app.state.db_session_factory = session_factory
    return TestClient(
        app,
        headers={"Authorization": f"Bearer {_GATEWAY_TOKEN}"},
        raise_server_exceptions=True,
    )


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
    """start_thread with team_preset=None uses 'vaultspec-solo-coder'
    -- not unknown.
    """
    # With no server running this hits a connection error -- but must NOT raise
    # an "Unknown preset" error.
    with pytest.raises(ToolError) as exc_info:
        await start_thread(initial_message="test", team_preset=None)
    assert "Unknown preset" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_start_thread_no_preset_defaults_to_solo_coder_live(
    session_factory, checkpointer
) -> None:
    """No-arg start_thread resolves the default preset to solo-coder end-to-end.

    Drives the real MCP start_thread tool against the in-process FastAPI app
    (real routes, real DB, real known-presets fetch) with team_preset=None and
    asserts the created thread is dispatched under vaultspec-solo-coder -- the
    retained default after the adaptive-coder preset was retired.
    """
    with _make_test_client(session_factory, checkpointer) as client:
        original_gateway_url = settings.gateway_url
        original_client = mcp_http._shared_client
        _reset_known_presets()
        try:
            settings.gateway_url = "http://testserver"
            mcp_http._shared_client = httpx.AsyncClient(
                transport=ASGITransport(app=client.app),
                base_url="http://testserver",
            )
            output = await start_thread(initial_message="ship it", team_preset=None)
        finally:
            if mcp_http._shared_client is not None:
                await mcp_http._shared_client.aclose()
            mcp_http._shared_client = original_client
            _reset_known_presets()
            settings.gateway_url = original_gateway_url

    assert "Preset: vaultspec-solo-coder" in output


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

    def test_get_thread_state_excludes_terminal_pending_permission_residue(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads/{id}/state must hide stale terminal approvals."""

        async def _seed_terminal_thread() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-mcp-thread-state-terminal-permission-residue"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "mcp-thread-state-terminal-permission-residue",
                        "checkpoint_ns": "",
                    }
                },
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                {},
            )
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="mcp-thread-state-terminal-permission-residue",
                    status="failed",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = (
                    "mcp-thread-state-terminal-permission-residue:perm-1"
                )
                await record_permission_request(
                    session,
                    request_id="mcp-thread-state-terminal-permission-residue:perm-1",
                    thread_id="mcp-thread-state-terminal-permission-residue",
                    pause_reason_type="plan_approval_request",
                    description="Stale terminal plan approval",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_terminal_thread())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get(
                "/api/threads/mcp-thread-state-terminal-permission-residue/state"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert data["approval_status"] is None
        assert data["approval_request_id"] is None
        assert "terminal_thread_pending_permission_residue" in data["degraded_reasons"]
        assert data["repair_status"] == "needs_reconciliation"
        assert data["execution_readiness"] == "needs_reconciliation"

    def test_post_threads_with_workspace_root_returns_201(
        self, session_factory, checkpointer, workspace_root: Path
    ) -> None:
        """POST /api/threads with workspace_root in metadata passes through to 201."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello workspace",
                    "autonomous": True,
                    "metadata": {"workspace_root": str(workspace_root)},
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
# Tool function error-path tests
#
# These tests verify error-handling behaviour when the server is unavailable.
# The success path is covered by TestCreateThreadViaApp above.
# Test names are honest about what they test.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_thread_raises_when_server_unavailable() -> None:
    """start_thread with a valid preset raises when the server is not running.

    Verifies the tool raises an exception (FastMCP signals
    isError=true) rather than returning a silent error string.
    """
    with pytest.raises(ToolError) as exc_info:
        await start_thread(
            initial_message="do something",
            team_preset="vaultspec-solo-coder",
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

    Verifies exception-based error signaling.
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


@pytest.mark.asyncio(loop_scope="function")
async def test_get_thread_status_reports_repair_and_readiness(
    session_factory, checkpointer
) -> None:
    """MCP thread status must surface degraded checkpoint authority explicitly."""
    with _make_test_client(session_factory, checkpointer) as client:
        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="mcp-get-thread-status-checkpoint-unavailable",
                status="input_required",
                repair_status="checkpoint_unavailable",
                execution_readiness="checkpoint_unavailable",
            )
            await session.commit()

        original_gateway_url = settings.gateway_url
        original_client = mcp_http._shared_client
        try:
            settings.gateway_url = "http://testserver"
            mcp_http._shared_client = httpx.AsyncClient(
                transport=ASGITransport(app=client.app),
                base_url="http://testserver",
            )
            output = await get_thread_status(
                thread_id="mcp-get-thread-status-checkpoint-unavailable"
            )
        finally:
            if mcp_http._shared_client is not None:
                await mcp_http._shared_client.aclose()
            mcp_http._shared_client = original_client
            settings.gateway_url = original_gateway_url

    assert "Status: input_required" in output
    assert "Repair status: checkpoint_unavailable" in output
    assert "Execution readiness: checkpoint_unavailable" in output


@pytest.mark.asyncio
async def test_send_message_raises_when_server_unavailable() -> None:
    """send_message raises when the server is not running.

    Verifies exception-based error signaling.
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


@pytest.mark.asyncio(loop_scope="function")
async def test_send_message_raises_tool_error_for_repair_needed_thread(
    session_factory, checkpointer
) -> None:
    """send_message must surface backend 409s for repair-state threads."""
    with _make_test_client(session_factory, checkpointer) as client:
        create_resp = client.post(
            "/api/threads",
            json={"initial_message": "message tool conflict"},
        )
        assert create_resp.status_code == 201
        thread_id = create_resp.json()["thread_id"]

        async with session_factory() as session:
            thread = await session.get(ThreadModel, thread_id)
            assert thread is not None
            thread.status = "repair_needed"
            thread.repair_status = "checkpoint_unavailable"
            thread.execution_readiness = "checkpoint_unavailable"
            await session.commit()

        original_gateway_url = settings.gateway_url
        original_client = mcp_http._shared_client
        try:
            settings.gateway_url = "http://testserver"
            mcp_http._shared_client = httpx.AsyncClient(
                transport=ASGITransport(app=client.app),
                base_url="http://testserver",
            )
            with pytest.raises(ToolError) as exc_info:
                await send_message(thread_id=thread_id, message="hello")
        finally:
            if mcp_http._shared_client is not None:
                await mcp_http._shared_client.aclose()
            mcp_http._shared_client = original_client
            settings.gateway_url = original_gateway_url

    assert "Cannot send message to thread" in str(exc_info.value)
    assert "repair_needed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _ws_url_from_api_base unit tests
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
# list_threads tests
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


@pytest.mark.asyncio(loop_scope="function")
async def test_list_threads_reports_repair_and_readiness(
    session_factory, checkpointer
) -> None:
    """MCP list_threads must surface degraded checkpoint authority explicitly."""
    with _make_test_client(session_factory, checkpointer) as client:
        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="mcp-list-threads-checkpoint-unavailable",
                status="input_required",
                repair_status="checkpoint_unavailable",
                execution_readiness="checkpoint_unavailable",
            )
            await session.commit()

        original_gateway_url = settings.gateway_url
        original_client = mcp_http._shared_client
        try:
            settings.gateway_url = "http://testserver"
            mcp_http._shared_client = httpx.AsyncClient(
                transport=ASGITransport(app=client.app),
                base_url="http://testserver",
            )
            output = await list_threads()
        finally:
            if mcp_http._shared_client is not None:
                await mcp_http._shared_client.aclose()
            mcp_http._shared_client = original_client
            settings.gateway_url = original_gateway_url

    assert "[input_required] mcp-list-threads-checkpoint-unavailable" in output
    assert "repair: checkpoint_unavailable" in output
    assert "readiness: checkpoint_unavailable" in output


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

    def test_list_threads_degrades_stale_execution_state_summary(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads must not report healthy readiness on stale lineage."""

        async def _seed_stale_execution_state() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="mcp-thread-list-stale-state",
                    status="running",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread = await session.get(ThreadModel, "mcp-thread-list-stale-state")
                assert thread is not None
                thread.recovery_epoch = 4
                session.add(
                    ThreadExecutionStateModel(
                        thread_id="mcp-thread-list-stale-state",
                        checkpoint_id="cp-mcp-stale",
                        parent_checkpoint_id=None,
                        recovery_epoch=1,
                        task_count=1,
                        interrupt_count=0,
                        next_nodes_json='["worker"]',
                        interrupt_types_json="[]",
                        tasks_json="[]",
                        degraded_reasons_json="[]",
                    )
                )
                await session.commit()

        asyncio.run(_seed_stale_execution_state())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-stale-state"
        )
        assert thread["repair_status"] == "needs_reconciliation"
        assert thread["execution_readiness"] == "needs_reconciliation"

    def test_list_threads_hides_optionless_plan_approval_summary(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads must not expose optionless plan approvals."""

        async def _seed_optionless_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="mcp-thread-list-optionless-plan",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "mcp-thread-list-optionless-plan:perm-1"
                await record_permission_request(
                    session,
                    request_id="mcp-thread-list-optionless-plan:perm-1",
                    thread_id="mcp-thread-list-optionless-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve optionless plan?",
                    allowed_options=[],
                    tool_call="plan_approval",
                )
                await session.commit()

        asyncio.run(_seed_optionless_plan_thread())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-optionless-plan"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_clears_terminal_pending_approval_summary(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads must not keep pending approval on terminal threads."""

        async def _seed_terminal_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="mcp-thread-list-terminal-plan",
                    status="failed",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "mcp-thread-list-terminal-plan:perm-1"
                await record_permission_request(
                    session,
                    request_id="mcp-thread-list-terminal-plan:perm-1",
                    thread_id="mcp-thread-list-terminal-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve terminal plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call="plan_approval",
                )
                await session.commit()

        asyncio.run(_seed_terminal_plan_thread())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-terminal-plan"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_hides_answered_pending_apply_summary(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads must not expose already-answered approvals."""

        async def _seed_answered_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="mcp-thread-list-answered-pending-apply",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = (
                    "mcp-thread-list-answered-pending-apply:perm-1"
                )
                await record_permission_request(
                    session,
                    request_id="mcp-thread-list-answered-pending-apply:perm-1",
                    thread_id="mcp-thread-list-answered-pending-apply",
                    pause_reason_type="plan_approval_request",
                    description="Already answered plan approval",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await record_permission_response_submission(
                    session,
                    request_id="mcp-thread-list-answered-pending-apply:perm-1",
                    option_id="approve",
                    idempotency_key="idem-mcp-thread-list-answered-pending-apply",
                )
                await session.commit()

        asyncio.run(_seed_answered_plan_thread())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-answered-pending-apply"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_prefers_live_plan_after_rejected_residue(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads must not let stale rejected state hide live approval."""

        async def _seed_live_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="mcp-thread-list-rejected-live-plan",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "rejected"
                thread.approval_request_id = (
                    "mcp-thread-list-stale-rejected-plan:perm-1"
                )
                await record_permission_request(
                    session,
                    request_id="mcp-thread-list-live-after-reject:perm-1",
                    thread_id="mcp-thread-list-rejected-live-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve revised plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_live_plan_thread())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-rejected-live-plan"
        )
        assert thread["approval_status"] == "pending"
        assert (
            thread["approval_request_id"] == "mcp-thread-list-live-after-reject:perm-1"
        )

    def test_list_threads_degrades_checkpoint_mismatched_summary(
        self, session_factory, checkpointer
    ) -> None:
        """GET /api/threads must not hide checkpoint-id drift in summaries."""

        async def _seed_checkpoint_mismatch() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-mcp-current"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "mcp-thread-list-checkpoint-drift",
                        "checkpoint_ns": "",
                    }
                },
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                {},
            )
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="mcp-thread-list-checkpoint-drift",
                    status="running",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                session.add(
                    ThreadExecutionStateModel(
                        thread_id="mcp-thread-list-checkpoint-drift",
                        checkpoint_id="cp-mcp-stale",
                        parent_checkpoint_id=None,
                        recovery_epoch=0,
                        task_count=1,
                        interrupt_count=0,
                        next_nodes_json='["worker"]',
                        interrupt_types_json="[]",
                        tasks_json="[]",
                        degraded_reasons_json="[]",
                    )
                )
                await session.commit()

        asyncio.run(_seed_checkpoint_mismatch())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-checkpoint-drift"
        )
        assert thread["repair_status"] == "needs_reconciliation"
        assert thread["execution_readiness"] == "needs_reconciliation"

    def test_list_threads_degrades_when_checkpoint_probe_is_unverified(
        self, session_factory, tmp_path
    ) -> None:
        """GET /api/threads must fail closed when checkpoint probing fails."""
        checkpoints_file = tmp_path / "closed-mcp-list-threads-checkpoints.db"

        async def _closed_checkpointer() -> AsyncSqliteSaver:
            async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as cp:
                await cp.setup()
                return cp

        closed_checkpointer = asyncio.run(_closed_checkpointer())

        async def _seed_thread() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="mcp-thread-list-checkpoint-unverified",
                    status="running",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with _make_test_client(session_factory, closed_checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-checkpoint-unverified"
        )
        assert thread["repair_status"] == "checkpoint_unavailable"
        assert thread["execution_readiness"] == "checkpoint_unavailable"

    def test_list_threads_hides_pending_approval_when_checkpoint_probe_is_unverified(
        self, session_factory, tmp_path
    ) -> None:
        """Checkpoint-unverified MCP summaries must not expose approvals."""
        checkpoints_file = tmp_path / "closed-mcp-list-threads-plan-approval.db"

        async def _closed_checkpointer() -> AsyncSqliteSaver:
            async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as cp:
                await cp.setup()
                return cp

        closed_checkpointer = asyncio.run(_closed_checkpointer())

        async def _seed_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="mcp-thread-list-checkpoint-unverified-plan",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = (
                    "mcp-thread-list-checkpoint-unverified-plan:perm-1"
                )
                await record_permission_request(
                    session,
                    request_id="mcp-thread-list-checkpoint-unverified-plan:perm-1",
                    thread_id="mcp-thread-list-checkpoint-unverified-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve MCP plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with _make_test_client(session_factory, closed_checkpointer) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "mcp-thread-list-checkpoint-unverified-plan"
        )
        assert thread["repair_status"] == "checkpoint_unavailable"
        assert thread["execution_readiness"] == "checkpoint_unavailable"
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None


# ---------------------------------------------------------------------------
# respond_to_permission tests
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

    @pytest.mark.asyncio(loop_scope="function")
    async def test_respond_to_permission_raises_tool_error_for_stale_request(
        self, session_factory, checkpointer
    ) -> None:
        """MCP must surface stale permission conflicts as ToolError."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission tool conflict"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            old_request_id = f"{thread_id}:req-old"
            new_request_id = f"{thread_id}:req-new"

            async def _seed_permissions() -> None:
                async with session_factory() as session:
                    await record_permission_request(
                        session,
                        request_id=old_request_id,
                        thread_id=thread_id,
                        pause_reason_type="bash",
                        description="Allow old action?",
                        allowed_options=[
                            {"option_id": "allow_once", "name": "Allow once"}
                        ],
                        tool_call="bash",
                    )
                    await record_permission_request(
                        session,
                        request_id=new_request_id,
                        thread_id=thread_id,
                        pause_reason_type="bash",
                        description="Allow new action?",
                        allowed_options=[
                            {"option_id": "allow_once", "name": "Allow once"}
                        ],
                        tool_call="bash",
                    )
                    await session.commit()

            await _seed_permissions()

            original_gateway_url = settings.gateway_url
            original_client = mcp_http._shared_client
            try:
                settings.gateway_url = "http://testserver"
                mcp_http._shared_client = httpx.AsyncClient(
                    transport=ASGITransport(app=client.app),
                    base_url="http://testserver",
                )
                with pytest.raises(ToolError) as exc_info:
                    await respond_to_permission(
                        permission_request_id=old_request_id,
                        option_id="allow_once",
                    )
            finally:
                if mcp_http._shared_client is not None:
                    await mcp_http._shared_client.aclose()
                mcp_http._shared_client = original_client
                settings.gateway_url = original_gateway_url

        assert "Cannot respond to permission" in str(exc_info.value)
        assert "no longer pending" in str(exc_info.value)


# ---------------------------------------------------------------------------
# get_team_status tests
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
# get_pending_permissions tests
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

    def test_get_pending_permissions_excludes_answered_pending_apply(
        self, session_factory, checkpointer
    ) -> None:
        """Team status must not expose already-answered permissions as pending."""

        async def _seed_answered_permission() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="mcp-team-status-answered-pending-apply",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await record_permission_request(
                    session,
                    request_id="mcp-team-status-answered-pending-apply:perm-1",
                    thread_id="mcp-team-status-answered-pending-apply",
                    pause_reason_type="plan_approval_request",
                    description="Already answered plan approval",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await record_permission_response_submission(
                    session,
                    request_id="mcp-team-status-answered-pending-apply:perm-1",
                    option_id="approve",
                    idempotency_key="idem-mcp-team-status-answered-pending-apply",
                )
                await session.commit()

        asyncio.run(_seed_answered_permission())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []

    def test_team_status_lists_durable_pending_permission_thread_as_active(
        self, session_factory, checkpointer
    ) -> None:
        """Durable paused threads must stay visible in team status.

        This must hold even after restart-like gaps in in-memory worker state.
        """

        async def _seed_durable_pending_permission() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="team-status-durable-pending",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await record_permission_request(
                    session,
                    request_id="team-status-durable-pending:perm-1",
                    thread_id="team-status-durable-pending",
                    pause_reason_type="plan_approval_request",
                    description="Approve durable plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_durable_pending_permission())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "team-status-durable-pending" in data["active_threads"]
        assert len(data["pending_permissions"]) == 1
        assert (
            data["pending_permissions"][0]["request_id"]
            == "team-status-durable-pending:perm-1"
        )

    def test_team_status_excludes_aggregator_only_pending_permission(
        self, session_factory, checkpointer
    ) -> None:
        """Aggregator-only permissions must not become public pending truth."""
        import time

        from vaultspec_a2a.graph.events import PermissionRequest

        agg = EventAggregator()
        event = PermissionRequest(
            thread_id="team-status-aggregator-only",
            agent_id="vaultspec-coder",
            timestamp=time.time(),
            request_id="team-status-aggregator-only:perm-1",
            description="Ghost permission",
            options=[],
        )
        agg._emitters._pending_permissions["team-status-aggregator-only:perm-1"] = (
            event,
            0.0,
        )

        with _make_test_client(
            session_factory,
            checkpointer,
            aggregator=agg,
        ) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []

    def test_team_status_hides_malformed_durable_pending_permission(
        self, session_factory, checkpointer
    ) -> None:
        """Malformed durable rows must not become MCP-visible pending actions."""

        async def _seed_malformed_permission() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="mcp-team-status-malformed-durable",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await record_permission_request(
                    session,
                    request_id="mcp-team-status-malformed-durable:perm-1",
                    thread_id="mcp-team-status-malformed-durable",
                    pause_reason_type="permission_request",
                    description="Malformed durable permission",
                    allowed_options=[{"option_id": "allow_once", "name": "Allow"}],
                    tool_call="bash",
                )
                permission = await session.get(
                    PermissionRequestModel,
                    "mcp-team-status-malformed-durable:perm-1",
                )
                assert permission is not None
                permission.allowed_options_json = '{"broken":'
                await session.commit()

        asyncio.run(_seed_malformed_permission())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "mcp-team-status-malformed-durable" in data["active_threads"]
        assert data["pending_permissions"] == []

    def test_team_status_excludes_orphaned_durable_permission_rows(
        self, session_factory, checkpointer
    ) -> None:
        """Orphaned durable permissions must not surface as MCP-visible work."""

        async def _seed_orphaned_permission() -> None:
            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id="mcp-team-status-orphaned:perm-1",
                    thread_id="mcp-team-status-orphaned",
                    pause_reason_type="plan_approval_request",
                    description="Orphaned durable permission",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_orphaned_permission())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "mcp-team-status-orphaned" not in data["active_threads"]
        assert data["pending_permissions"] == []

    def test_team_status_hides_checkpoint_unavailable_pending_permission(
        self, session_factory, checkpointer
    ) -> None:
        """MCP team status must not expose approvals without checkpoint truth."""

        async def _seed_thread() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="mcp-team-status-checkpoint-unavailable",
                    status="input_required",
                    repair_status="checkpoint_unavailable",
                    execution_readiness="checkpoint_unavailable",
                )
                await record_permission_request(
                    session,
                    request_id="mcp-team-status-checkpoint-unavailable:perm-1",
                    thread_id="mcp-team-status-checkpoint-unavailable",
                    pause_reason_type="plan_approval_request",
                    description="Approve stranded MCP plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "mcp-team-status-checkpoint-unavailable" in data["active_threads"]
        assert data["pending_permissions"] == []


# ---------------------------------------------------------------------------
# list_team_presets tests
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
# cancel_thread tests
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
        """Repeated cancel requests stay accepted until worker
        confirms terminal state.
        """
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

    @pytest.mark.asyncio(loop_scope="function")
    async def test_delete_thread_raises_tool_error_for_nonterminal_thread(
        self, session_factory, checkpointer
    ) -> None:
        """delete_thread must surface backend 409s as ToolError."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "delete tool conflict"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]

            async with session_factory() as session:
                thread = await session.get(ThreadModel, thread_id)
                assert thread is not None
                thread.status = "input_required"
                thread.repair_status = "paused_resumable"
                thread.execution_readiness = "paused_resumable"
                await record_permission_request(
                    session,
                    request_id=f"{thread_id}:perm-delete-conflict",
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow action?",
                    allowed_options=[{"option_id": "allow_once", "name": "Allow Once"}],
                    tool_call="bash",
                )
                await session.commit()

            original_gateway_url = settings.gateway_url
            original_client = mcp_http._shared_client
            try:
                settings.gateway_url = "http://testserver"
                mcp_http._shared_client = httpx.AsyncClient(
                    transport=ASGITransport(app=client.app),
                    base_url="http://testserver",
                )
                with pytest.raises(ToolError) as exc_info:
                    await delete_thread(thread_id)
            finally:
                if mcp_http._shared_client is not None:
                    await mcp_http._shared_client.aclose()
                mcp_http._shared_client = original_client
                settings.gateway_url = original_gateway_url

        assert "Cannot delete thread" in str(exc_info.value)
        assert "input_required" in str(exc_info.value)


class TestKnownPresetsCache:
    """_known_presets_cache is populated on first call and cleared by
    _reset_known_presets.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_reset_known_presets_clears_cache_after_population(self) -> None:
        """_reset_known_presets() sets _known_presets_cache back to None
        after it was set.
        """
        import sys

        from .._http import _get_known_presets

        # Locate the already-imported _http module via sys.modules
        srv_mod = next(
            m for k, m in sys.modules.items() if k.endswith("protocols.mcp._http")
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
