"""Tests for the MCP server tool implementations.

Tests use direct function calls and the real FastAPI TestClient (which
triggers the app lifespan) to verify MCP tool error paths and the API
contract expected by the MCP tools.

Per CLAUDE.md: no mocks, no monkeypatching.  The TestClient path runs
the full lifespan (checkpointer, task group) using real in-memory SQLite.

Error-path tests (unknown preset, connection error) call MCP tool
functions directly and rely on the known unreachable ``localhost:8000``
default to exercise the ``httpx.RequestError`` branch.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ....api.app import create_app
from ....api.endpoints import GraphRegistry, get_aggregator, get_graph_registry
from ....core.aggregator import EventAggregator
from ....database.models import Base
from ....database.session import get_db
from ..server import get_thread_status, send_message, start_thread


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


def _make_test_client(session_factory, aggregator=None, registry=None) -> TestClient:
    """Create a TestClient backed by a real app lifespan (checkpointer + task_group)."""
    app = create_app()
    if aggregator is None:
        aggregator = EventAggregator()
    if registry is None:
        registry = GraphRegistry()

    # Override the DB session so tests use in-memory SQLite
    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_aggregator] = lambda: aggregator
    app.dependency_overrides[get_graph_registry] = lambda: registry
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Error-path tests (no HTTP server needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_thread_unknown_preset_returns_error() -> None:
    """start_thread with an unknown preset returns an error string immediately."""
    result = await start_thread(
        initial_message="do something", team_preset="nonexistent-preset"
    )
    assert "Error" in result
    assert "nonexistent-preset" in result
    # Should list valid presets in the error message
    assert "coding-star" in result


@pytest.mark.asyncio
async def test_start_thread_default_preset_not_unknown() -> None:
    """start_thread with team_preset=None uses 'coding-star' — not an unknown preset."""
    # With no server running this hits a connection error — but must NOT hit
    # the unknown-preset early-return.
    result = await start_thread(initial_message="test", team_preset=None)
    # Must not mention the unknown preset error
    assert "Unknown preset" not in result


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
# Tool function connectivity tests (server may or may not be running)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_thread_returns_string() -> None:
    """start_thread always returns a string regardless of server state."""
    result = await start_thread(
        initial_message="do something",
        team_preset="coding-star",
    )
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_get_thread_status_returns_string() -> None:
    """get_thread_status always returns a string regardless of server state."""
    result = await get_thread_status(thread_id="some-thread-id")
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_send_message_returns_string() -> None:
    """send_message always returns a string regardless of server state."""
    result = await send_message(thread_id="some-thread-id", message="hello")
    assert isinstance(result, str)
    assert len(result) > 0
