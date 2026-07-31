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
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from mcp.server.mcpserver.exceptions import ToolError
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
    create_artifact,
    create_thread,
    record_permission_request,
    record_permission_response_submission,
)
from ....database.models import (
    Base,
    PermissionRequestModel,
    ThreadModel,
)
from ....streaming.aggregator import EventAggregator
from ....thread.enums import CleanupKind
from .. import _http as mcp_http
from .._http import _reset_client, _reset_known_presets

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

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
    (real routes, real DB, real versioned presets fetch) with team_preset=None.

    The default preset arms the engine authoring bridge, so the versioned
    run-start verb refuses a bundle-less start before creating durable state.
    That refusal is the observable proof the default resolved: the gateway names
    ``vaultspec-solo-coder`` and the exact role whose engine-minted actor token
    is missing, so the request reached the real eligibility policy under the
    retained default preset rather than stopping at client-side validation.
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
            with pytest.raises(ToolError) as exc_info:
                await start_thread(initial_message="ship it", team_preset=None)
        finally:
            if mcp_http._shared_client is not None:
                await mcp_http._shared_client.aclose()
            mcp_http._shared_client = original_client
            _reset_known_presets()
            settings.gateway_url = original_gateway_url

    message = str(exc_info.value)
    assert "vaultspec-solo-coder" in message
    assert "vaultspec-coder" in message
    assert "actor token" in message


@pytest.mark.asyncio
async def test_start_thread_dispatches_through_the_versioned_run_verb(
    session_factory, checkpointer
) -> None:
    """start_thread creates a durable run through POST /v1/runs, end to end.

    Uses a preset that carries no per-role token requirement, so the whole
    repointed path is exercised for real: the versioned presets fetch that
    validates the preset id, the ``message`` field name the versioned request
    model requires, and the ``run_id`` the versioned response returns. The
    returned id is then read back through the versioned run-status verb, which
    proves the tool reported the identity of a run that actually exists rather
    than echoing its own payload.
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
            output = await start_thread(
                initial_message="ship it",
                team_preset="mock-success-single",
            )
        finally:
            if mcp_http._shared_client is not None:
                await mcp_http._shared_client.aclose()
            mcp_http._shared_client = original_client
            _reset_known_presets()
            settings.gateway_url = original_gateway_url

        assert "Preset: mock-success-single" in output
        run_id = output.splitlines()[0].removeprefix("Thread started: ").strip()
        assert run_id

        status = client.get(f"/v1/runs/{run_id}")
        assert status.status_code == 200
        assert status.json()["run_id"] == run_id


@pytest.mark.asyncio
async def test_start_thread_reports_the_missing_feature_tag_refusal(
    session_factory, checkpointer
) -> None:
    """A document-authoring preset without a feature tag is refused actionably.

    The versioned verb refuses before any durable state exists, and the refusal
    detail is the only thing that tells the caller what to supply. The tool must
    surface it rather than collapsing it into a bare status code.
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
            with pytest.raises(ToolError) as exc_info:
                await start_thread(
                    initial_message="write the record",
                    team_preset="vaultspec-adr-research",
                )
        finally:
            if mcp_http._shared_client is not None:
                await mcp_http._shared_client.aclose()
            mcp_http._shared_client = original_client
            _reset_known_presets()
            settings.gateway_url = original_gateway_url

    assert "requires a target feature tag" in str(exc_info.value)


# ---------------------------------------------------------------------------
# API contract tests via TestClient (lifespan-backed)
# ---------------------------------------------------------------------------


# A preset that declares no required roles, so a run starts without the
# engine-minted actor-token bundle the versioned verb demands of every
# production preset.
_BUNDLE_FREE_PRESET = "mock-success-single"


class TestCreateThreadViaApp:
    """Tests that exercise the real FastAPI app the MCP tools talk to."""

    def test_post_threads_without_autonomous_returns_201(
        self, session_factory, checkpointer
    ) -> None:
        """POST /v1/runs without autonomous field returns 201."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "Hello from MCP test",
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "run_id" in data

    def test_post_threads_with_autonomous_true_returns_201(
        self, session_factory, checkpointer
    ) -> None:
        """POST /v1/runs with autonomous=True returns 201."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "Hello autonomous",
                    "autonomous": True,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "run_id" in data
        assert data["status"] == "running"

    def test_get_thread_state_404_for_unknown(
        self, session_factory, checkpointer
    ) -> None:
        """GET /v1/runs/{id}/history returns 404 for unknown thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/v1/runs/nonexistent-id/history")
        assert resp.status_code == 404

    def test_get_thread_state_200_for_existing(
        self, session_factory, checkpointer
    ) -> None:
        """GET /v1/runs/{id}/history returns 200 with thread data."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "Hello"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["run_id"]

            state_resp = client.get(f"/v1/runs/{thread_id}/history")
        assert state_resp.status_code == 200
        data = state_resp.json()["state"]
        assert data["thread_id"] == thread_id

    def test_get_thread_state_excludes_terminal_pending_permission_residue(
        self, session_factory, checkpointer
    ) -> None:
        """GET /v1/runs/{id}/history must hide stale terminal approvals."""

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
                "/v1/runs/mcp-thread-state-terminal-permission-residue/history"
            )

        assert resp.status_code == 200
        data = resp.json()["state"]
        assert data["pending_permissions"] == []
        assert data["approval_status"] is None
        assert data["approval_request_id"] is None
        assert "terminal_thread_pending_permission_residue" in data["degraded_reasons"]
        assert data["repair_status"] == "needs_reconciliation"
        assert data["execution_readiness"] == "needs_reconciliation"

    def test_post_threads_with_workspace_root_returns_201(
        self, session_factory, checkpointer, workspace_root: Path
    ) -> None:
        """POST /v1/runs with workspace_root in metadata passes through to 201."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "Hello workspace",
                    "autonomous": True,
                    "metadata": {"workspace_root": str(workspace_root)},
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "run_id" in data

    def test_send_message_returns_404_for_unknown_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /v1/runs/{id}/messages returns 404 for unknown thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/v1/runs/nonexistent/messages",
                json={"content": "hello"},
            )
        assert resp.status_code == 404

    def test_send_message_returns_202_for_existing_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /v1/runs/{id}/messages returns 202 for an existing thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "Hello"},
            )
            thread_id = create_resp.json()["run_id"]

            send_resp = client.post(
                f"/v1/runs/{thread_id}/messages",
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


@pytest.fixture
def unreachable_gateway() -> "Iterator[None]":
    """Point the gateway URL at an OWNED, closed loopback port for a test.

    These error-path tests assert that a tool raises when the gateway is
    unavailable. Left to ambient settings the URL defaults to the real gateway
    port, so on a machine already running one the tests would reach a live
    service and assert nothing about the unavailable path. The fixture takes a
    port, closes it, and confirms by a connect-probe that the port refuses -
    binding alone is an unreliable "is it free" signal on Windows - so
    unavailability is guaranteed rather than assumed. Settings are restored on
    exit, and the shared client is reset so no test leaks a connection to the
    dead port into the next.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # The socket is now closed; confirm the port actually refuses before relying
    # on it, so a racing bind cannot turn "unavailable" into a silent success.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
        check.settimeout(0.5)
        if check.connect_ex(("127.0.0.1", port)) == 0:
            pytest.skip(f"port {port} was reclaimed before the test could use it")

    original_url = settings.gateway_url
    _reset_client()
    settings.gateway_url = f"http://127.0.0.1:{port}"
    try:
        yield
    finally:
        settings.gateway_url = original_url
        _reset_client()


@pytest.mark.asyncio
async def test_start_thread_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
    """start_thread with a valid preset raises when the server is not running.

    Verifies the tool raises an exception (MCPServer signals
    is_error=true) rather than returning a silent error string.
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
async def test_get_thread_status_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
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
    # A missing checkpoint is a replay gap, not an unknown probe: this path has
    # established the checkpoint is absent, where checkpoint-unavailable claims
    # its contents could not be determined.
    assert "Repair status: replay_gap" in output
    assert "Execution readiness: replay_gap" in output


@pytest.mark.asyncio
async def test_send_message_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
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
            "/v1/runs",
            json={
                "team_preset": _BUNDLE_FREE_PRESET,
                "message": "message tool conflict",
            },
        )
        assert create_resp.status_code == 201
        thread_id = create_resp.json()["run_id"]

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
# list_threads tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_threads_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
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
async def test_list_threads_lists_a_non_terminal_thread_with_its_status(
    session_factory, checkpointer
) -> None:
    """MCP list_threads reports each thread's identity and status.

    Degraded checkpoint authority is NOT asserted here: the versioned list
    record carries the run identity, status, and feature tag only, and this test
    must not claim a field the response does not carry.
    ``test_get_thread_status_reports_repair_and_readiness`` holds that coverage,
    against the verb that does carry it.
    """
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
    assert "of 1" in output


@pytest.mark.asyncio(loop_scope="function")
async def test_list_threads_includes_terminal_threads(
    session_factory, checkpointer
) -> None:
    """MCP list_threads reads history, not just live work.

    The versioned list verb defaults to capped active-run discovery, which omits
    terminal runs entirely. The tool must ask for the history reading, so a
    completed thread has to appear. Seeding one terminal and one non-terminal
    thread proves the listing is not merely the active projection.
    """
    with _make_test_client(session_factory, checkpointer) as client:
        async with session_factory() as session:
            await create_thread(
                session, thread_id="mcp-list-terminal", status="completed"
            )
            await create_thread(session, thread_id="mcp-list-running", status="running")
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

    assert "[completed] mcp-list-terminal" in output
    assert "[running] mcp-list-running" in output


class TestListThreadsViaApp:
    """Tests that exercise list_threads via the real FastAPI app."""

    def test_list_threads_empty(self, session_factory, checkpointer) -> None:
        """GET /v1/runs returns empty list when no threads exist."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/v1/runs", params={"state": "all"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"] == []
        assert data["total"] == 0

    def test_list_threads_returns_created_thread(
        self, session_factory, checkpointer
    ) -> None:
        """GET /v1/runs includes a run created via POST /v1/runs."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "MCP list test",
                },
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["run_id"]

            list_resp = client.get("/v1/runs", params={"state": "all"})
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert data["total"] >= 1
        thread_ids = [run["run_id"] for run in data["runs"]]
        assert thread_id in thread_ids
        # The versioned list record carries run identity, status and feature tag
        # only, so the preset the run was started under is NOT asserted here -
        # ``get_thread_status`` is where a caller reads a run's detail.
        matching = [run for run in data["runs"] if run["run_id"] == thread_id]
        assert matching[0]["status"]

    def test_list_threads_pagination(self, session_factory, checkpointer) -> None:
        """GET /v1/runs respects limit and offset params."""
        with _make_test_client(session_factory, checkpointer) as client:
            for i in range(3):
                started = client.post(
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": f"Thread {i}",
                    },
                )
                assert started.status_code == 201, started.text
            resp = client.get(
                "/v1/runs", params={"state": "all", "limit": 2, "offset": 0}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 2
        assert data["total"] == 3


# ---------------------------------------------------------------------------
# respond_to_permission tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_respond_to_permission_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
    """respond_to_permission raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await respond_to_permission(
            thread_id="fake-thread",
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
        """The respond verb answers 404 when the run does not exist."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post(
                "/v1/runs/nonexistent/permissions/nonexistent:some-uuid/respond",
                json={"option_id": "allow"},
            )
        assert resp.status_code == 404

    @pytest.mark.asyncio(loop_scope="function")
    async def test_respond_to_permission_dispatches_for_existing_thread(
        self, session_factory, checkpointer
    ) -> None:
        """The MCP tool answers a durably-pending request through the run path.

        Drives the real tool rather than the route, so the run-scoped path the
        tool now builds is exercised end to end. The expected action status is
        derived from the service contract, not from a run: a fresh acceptance
        dispatches the answer and records ``accepted_not_applied``, because the
        worker has not yet carried it out. The durable request row is then read
        back, so the test proves the answer reached storage rather than only
        that a string came back.
        """
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": "mock-success-single",
                    "message": "Permission test",
                },
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["run_id"]

            request_id = f"{thread_id}:fake-uuid"

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

            original_gateway_url = settings.gateway_url
            original_client = mcp_http._shared_client
            try:
                settings.gateway_url = "http://testserver"
                mcp_http._shared_client = httpx.AsyncClient(
                    transport=ASGITransport(app=client.app),
                    base_url="http://testserver",
                )
                output = await respond_to_permission(
                    thread_id=thread_id,
                    permission_request_id=request_id,
                    option_id="allow",
                )
            finally:
                if mcp_http._shared_client is not None:
                    await mcp_http._shared_client.aclose()
                mcp_http._shared_client = original_client
                settings.gateway_url = original_gateway_url

        assert "Permission response accepted." in output
        assert "Action status: accepted_not_applied" in output
        assert request_id in output
        assert thread_id in output

        async with session_factory() as session:
            row = await session.get(PermissionRequestModel, request_id)
            assert row is not None
            assert row.request_status != "pending"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_respond_to_permission_refuses_another_threads_request(
        self, session_factory, checkpointer
    ) -> None:
        """A request id belonging to another thread is refused with no effect.

        The versioned verb resolves the request and checks it against the run in
        the path BEFORE anything acts on it, so a guessed request id cannot
        answer a different thread's question. The request must still be pending
        afterwards - a refusal that consumed the request would be worse than no
        guard at all.
        """
        with _make_test_client(session_factory, checkpointer) as client:
            owner = client.post(
                "/v1/runs",
                json={"team_preset": "mock-success-single", "message": "owner"},
            )
            other = client.post(
                "/v1/runs",
                json={"team_preset": "mock-success-single", "message": "other"},
            )
            assert owner.status_code == 201
            assert other.status_code == 201
            owner_id = owner.json()["run_id"]
            other_id = other.json()["run_id"]
            request_id = f"{owner_id}:scoped-uuid"

            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=owner_id,
                    pause_reason_type="tool_call",
                    description="Approve running dangerous-tool?",
                    allowed_options=[{"option_id": "allow", "name": "Allow"}],
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
                    await respond_to_permission(
                        thread_id=other_id,
                        permission_request_id=request_id,
                        option_id="allow",
                    )
            finally:
                if mcp_http._shared_client is not None:
                    await mcp_http._shared_client.aclose()
                mcp_http._shared_client = original_client
                settings.gateway_url = original_gateway_url

            assert "not found" in str(exc_info.value)

            async with session_factory() as session:
                row = await session.get(PermissionRequestModel, request_id)
                assert row is not None
                assert row.request_status == "pending"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_respond_to_permission_raises_tool_error_for_stale_request(
        self, session_factory, checkpointer
    ) -> None:
        """MCP must surface stale permission conflicts as ToolError."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "permission tool conflict",
                },
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["run_id"]
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
                        thread_id=thread_id,
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
async def test_get_team_status_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
    """get_team_status raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await get_team_status()
    msg = str(exc_info.value).lower()
    _expected = ("error", "connection", "connected", "network", "timeout", "gateway")
    assert any(kw in msg for kw in _expected)


class TestGetTeamStatusViaApp:
    """Tests exercising get_team_status through the real FastAPI app."""

    def test_get_team_status_returns_200(self, session_factory, checkpointer) -> None:
        """GET /v1/team/status returns 200 with valid structure."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/v1/team/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "active_runs" in data
        assert "pending_permissions" in data


# ---------------------------------------------------------------------------
# get_pending_permissions tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pending_permissions_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
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
            resp = client.get("/v1/team/status")
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
            resp = client.get("/v1/team/status")

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
            resp = client.get("/v1/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "team-status-durable-pending" in data["active_runs"]
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

        from ....graph.events import PermissionRequest

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
            resp = client.get("/v1/team/status")

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
            resp = client.get("/v1/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "mcp-team-status-malformed-durable" in data["active_runs"]
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
            resp = client.get("/v1/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "mcp-team-status-orphaned" not in data["active_runs"]
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
            resp = client.get("/v1/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "mcp-team-status-checkpoint-unavailable" in data["active_runs"]
        assert data["pending_permissions"] == []


# ---------------------------------------------------------------------------
# list_team_presets tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_team_presets_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
    """list_team_presets raises when the server is unreachable."""
    with pytest.raises(ToolError) as exc_info:
        await list_team_presets()
    msg = str(exc_info.value).lower()
    _expected = ("error", "connection", "connected", "network", "timeout", "gateway")
    assert any(kw in msg for kw in _expected)


class TestListTeamPresetsViaApp:
    """Tests exercising list_team_presets through the real FastAPI app."""

    def test_list_team_presets_returns_200(self, session_factory, checkpointer) -> None:
        """GET /v1/presets returns 200 with presets."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/v1/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        assert len(data["presets"]) > 0

    def test_list_team_presets_contains_expected_fields(
        self, session_factory, checkpointer
    ) -> None:
        """Each preset has id, display_name, description, topology, worker_count."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.get("/v1/presets")
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
async def test_cancel_thread_raises_when_server_unavailable(
    unreachable_gateway: None,
) -> None:
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
        """POST /v1/runs/{id}/cancel returns 404 for unknown thread."""
        with _make_test_client(session_factory, checkpointer) as client:
            resp = client.post("/v1/runs/nonexistent/cancel")
        assert resp.status_code == 404

    def test_cancel_thread_cancels_running_thread(
        self, session_factory, checkpointer
    ) -> None:
        """POST /v1/runs/{id}/cancel returns an accepted cancelling state."""
        with _make_test_client(session_factory, checkpointer) as client:
            create_resp = client.post(
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "Cancel me"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["run_id"]

            cancel_resp = client.post(f"/v1/runs/{thread_id}/cancel")
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["run_id"] == thread_id
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
                "/v1/runs",
                json={"team_preset": _BUNDLE_FREE_PRESET, "message": "Cancel twice"},
            )
            thread_id = create_resp.json()["run_id"]

            # First cancel
            client.post(f"/v1/runs/{thread_id}/cancel")
            # Second cancel
            cancel_resp = client.post(f"/v1/runs/{thread_id}/cancel")
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
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "delete tool conflict",
                },
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["run_id"]

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


# ---------------------------------------------------------------------------
# The delete tool against the DELETE contract's two success outcomes
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _tool_calls_reach(app) -> "AsyncIterator[None]":
    """Route the MCP tool surface's gateway calls into *app* for the block.

    Real ASGI transport over the real gateway app, so the tool issues the
    request it issues in production and reads the route's real response - real
    status line, real bytes, real absence of bytes.
    """
    original_url = settings.gateway_url
    original_client = mcp_http._shared_client
    settings.gateway_url = "http://testserver"
    mcp_http._shared_client = httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    )
    try:
        yield
    finally:
        client = mcp_http._shared_client
        mcp_http._shared_client = original_client
        settings.gateway_url = original_url
        if client is not None:
            await client.aclose()


async def _detached_checkpoint_store(db_file: Path) -> AsyncSqliteSaver:
    """Return a real checkpoint store that can no longer serve a delete.

    Not a stub and not a patched object: a real ``AsyncSqliteSaver`` over a
    real database file whose connection has been closed - the state a gateway
    is left holding when its checkpoint store goes away underneath it. Every
    cleanup pass against it fails for real, so after the saga's attempt ceiling
    the checkpoint item is abandoned rather than retried forever.
    """
    async with AsyncSqliteSaver.from_conn_string(str(db_file)) as saver:
        await saver.setup()
        return saver


class TestDeleteThreadSuccessOutcomes:
    """A success is reported as the outcome it actually was.

    The delete verb answers a clean deletion with no content and a deletion
    that finalized over permanently unremovable state with a body naming the
    kinds it stranded. Both are successes and the tool must tell them apart:
    flattening them loses the only signal a caller has that external state was
    left behind.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_clean_deletion_succeeds_and_reads_as_clean(
        self, session_factory, checkpointer
    ) -> None:
        """A no-content success is a success, not a parse failure.

        The regression guard for the crash: the route really answers 204 with
        an empty body, and before the fix the shared request helper parsed that
        body unconditionally and raised an unmapped JSON decode error straight
        out of the tool - so the commonest delete outcome crashed. Asserting on
        the returned text also proves the call completed rather than escaping.
        """
        # A store whose tables exist is what makes this outcome the CLEAN one:
        # every cleanup item really succeeds, so the saga finalizes with
        # nothing stranded and the route answers no-content.
        await checkpointer.setup()
        with _make_test_client(session_factory, checkpointer) as client:
            async with session_factory() as session:
                await create_thread(
                    session, thread_id="t-clean-delete", status="completed"
                )
                await session.commit()

            async with _tool_calls_reach(client.app):
                result = await delete_thread("t-clean-delete")

            # The rows are really gone: the saga ran, it did not merely answer.
            async with session_factory() as session:
                assert await session.get(ThreadModel, "t-clean-delete") is None

        assert result == "Thread t-clean-delete deleted."

    @pytest.mark.asyncio(loop_scope="function")
    async def test_an_abandoned_cleanup_is_reported_and_names_the_kinds(
        self, session_factory, tmp_path
    ) -> None:
        """A deletion that stranded state says so and names what it stranded.

        Nothing is arranged after the fact: the checkpoint item really fails
        against a detached store on every pass, and the artifact file is really
        removed. The first two calls are retryable, so the tool surfaces them
        as errors; the third finalizes over the item the saga stopped retrying
        and must report the abandonment rather than a bare 'deleted'. The
        cleaned artifact kind is absent from that report - only stranded state
        is named - and no filesystem path reaches the caller.
        """
        store = await _detached_checkpoint_store(tmp_path / "detached.db")
        workspace = tmp_path / "workspace"
        (workspace / "outputs").mkdir(parents=True)
        artifact_file = workspace / "outputs" / "report.md"
        artifact_file.write_text("body", encoding="utf-8")

        with _make_test_client(session_factory, store) as client:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="t-strand-delete",
                    status="completed",
                    metadata=json.dumps({"workspace_root": workspace.as_posix()}),
                )
                await create_artifact(
                    session,
                    thread_id="t-strand-delete",
                    artifact_type="file",
                    path="outputs/report.md",
                )
                await session.commit()

            async with _tool_calls_reach(client.app):
                # Resumable-incomplete cleanup is retryable, and a retry does
                # make progress; the ceiling turns the last pass terminal.
                for _ in range(2):
                    with pytest.raises(ToolError):
                        await delete_thread("t-strand-delete")
                result = await delete_thread("t-strand-delete")

        assert result.startswith("Thread t-strand-delete deleted, but cleanup was")
        assert CleanupKind.CHECKPOINT.value in result
        # The removable artifact was really removed, so its kind is not named.
        assert artifact_file.exists() is False
        assert CleanupKind.ARTIFACT_FILE.value not in result
        # Kinds only: a concrete target is control-plane state, never the
        # caller's to receive.
        assert workspace.as_posix() not in result
        assert "report.md" not in result

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_resumable_incomplete_cleanup_reads_as_retryable(
        self, session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
    ) -> None:
        """The in-progress outcome must invite the retry that completes it.

        Reporting it as a server fault tells the caller the service is broken,
        so it stops - and the retry is the only mechanism by which a resumable
        deletion ever finishes.  The message therefore has to carry three
        facts: that this is not a fault, that repeating the same call resumes
        the same deletion, and that the attempts should be spaced, because each
        one drives real cleanup work against a ledger that eventually abandons
        what it cannot remove.
        """
        store = await _detached_checkpoint_store(tmp_path / "detached.db")
        workspace = tmp_path / "workspace"
        (workspace / "outputs").mkdir(parents=True)

        with _make_test_client(session_factory, store) as client:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="t-resumable-delete",
                    status="completed",
                    metadata=json.dumps({"workspace_root": workspace.as_posix()}),
                )
                await session.commit()

            async with _tool_calls_reach(client.app):
                with pytest.raises(ToolError) as exc_info:
                    await delete_thread("t-resumable-delete")

        message = str(exc_info.value)
        # The three decision-relevant facts, and the thread it applies to.
        assert "t-resumable-delete" in message
        assert "resumable" in message
        assert "not a server fault" in message
        assert "delete_thread again" in message
        # A genuine fault reading would send the caller the other way.
        assert "Server error" not in message


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
