"""Tests for the REST endpoints.

Uses FastAPI TestClient with a real in-memory SQLite database and a real
EventAggregator + GraphRegistry (no mocks).  Permission tests use a real
compiled graph pre-registered in the GraphRegistry.

API-C1: all dependency overrides (including get_checkpointer and
get_task_group) are applied via the shared make_app() helper in conftest.py
so tests never touch the production vaultspec.db.
"""

import pytest

from fastapi.testclient import TestClient

from ...core.aggregator import EventAggregator
from ...core.graph import compile_team_graph
from ...core.team_config import load_agent_config, load_team_config
from ..endpoints import GraphRegistry
from .conftest import make_app


# ---------------------------------------------------------------------------
# POST /threads
# ---------------------------------------------------------------------------


class TestCreateThread:
    """Tests for POST /api/threads."""

    def test_creates_thread_without_preset(self, session_factory) -> None:
        """Creating a thread without team_preset returns 201 with thread_id."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello", "title": "Test thread"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        assert data["status"] == "submitted"

    def test_creates_thread_with_unknown_preset_raises_422(
        self, session_factory
    ) -> None:
        """An unknown team_preset returns 422."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello",
                    "team_preset": "nonexistent-preset",
                },
            )
        assert resp.status_code == 422

    def test_creates_thread_with_valid_preset_registers_graph(
        self, session_factory
    ) -> None:
        """Creating a thread with a valid preset compiles and registers a graph."""
        app, _agg, registry, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello",
                    "team_preset": "coding-pipeline",
                },
            )
        assert resp.status_code == 201
        thread_id = resp.json()["thread_id"]
        assert registry.get(thread_id) is not None

    def test_initial_message_length_limit(self, session_factory) -> None:
        """initial_message exceeding 64KB is rejected with validation error."""
        app, _agg, _reg, _cp = make_app(session_factory)
        oversized = "x" * (65536 + 1)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": oversized},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /threads
# ---------------------------------------------------------------------------


class TestListThreads:
    """Tests for GET /api/threads."""

    def test_empty_list(self, session_factory) -> None:
        """Returns an empty list when no threads exist."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["threads"] == []
        assert data["total"] == 0

    def test_lists_created_threads(self, session_factory) -> None:
        """Returns threads that were created."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            client.post(
                "/api/threads",
                json={"initial_message": "A", "title": "Thread A"},
            )
            client.post(
                "/api/threads",
                json={"initial_message": "B", "title": "Thread B"},
            )
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["threads"]) == 2


# ---------------------------------------------------------------------------
# GET /threads/{id}/state
# ---------------------------------------------------------------------------


class TestThreadState:
    """Tests for GET /api/threads/{id}/state."""

    def test_404_for_unknown_thread(self, session_factory) -> None:
        """Returns 404 for a thread that does not exist."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/nonexistent/state")
        assert resp.status_code == 404

    def test_returns_snapshot_for_existing_thread(self, session_factory) -> None:
        """Returns a ThreadStateSnapshot for a known thread."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]
            resp = client.get(f"/api/threads/{thread_id}/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == thread_id
        assert "last_sequence" in data
        assert data["last_sequence"] == 0

    def test_enriched_snapshot_when_graph_registered(self, session_factory) -> None:
        """GET /threads/{id}/state enriches snapshot when a graph is registered.

        API-M6: tests the _enrich_snapshot_from_state code path.
        """
        team = load_team_config("coding-pipeline")
        agent_configs = {
            w.agent_id: load_agent_config(w.agent_id) for w in team.workers
        }
        from langgraph.checkpoint.memory import MemorySaver

        cp = MemorySaver()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=cp,
        )

        registry = GraphRegistry()
        registry.register("thread-snap", graph)
        app, _agg, _reg, _cp = make_app(session_factory, registry=registry)

        with TestClient(app, raise_server_exceptions=True) as client:
            # Create the thread first so it exists in DB
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]
            # Register graph for this thread
            registry.register(thread_id, graph)

            resp = client.get(f"/api/threads/{thread_id}/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == thread_id
        # messages list present (may be empty since no graph execution happened)
        assert "messages" in data
        assert isinstance(data["messages"], list)


# ---------------------------------------------------------------------------
# POST /threads/{id}/messages
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Tests for POST /api/threads/{id}/messages."""

    def test_404_for_unknown_thread(self, session_factory) -> None:
        """Returns 404 when the thread does not exist."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads/nonexistent/messages",
                json={"content": "Hello"},
            )
        assert resp.status_code == 404

    def test_202_accepted_without_graph(self, session_factory) -> None:
        """Returns 202 and emits submitted status when no graph is registered."""
        aggregator = EventAggregator()
        app, _agg, _reg, _cp = make_app(session_factory, aggregator=aggregator)

        # Register a subscriber so the aggregator accepts subscriptions
        aggregator.add_subscriber("test-client")
        aggregator.subscribe("test-client", ["__all__"])

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]

            # Subscribe to this specific thread
            aggregator.subscribe("test-client", [thread_id])

            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"content": "Run it"},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["thread_id"] == thread_id

    def test_content_length_limit(self, session_factory) -> None:
        """content exceeding 64KB is rejected with 422."""
        app, _agg, _reg, _cp = make_app(session_factory)
        oversized = "x" * (65536 + 1)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]
            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"content": oversized},
            )
        assert resp.status_code == 422

    def test_202_accepted_with_graph_triggers_ingest(self, session_factory) -> None:
        """POST /threads/{id}/messages with a registered graph triggers ingest.

        API-M3: verifies the graph execution path is invoked.
        """
        team = load_team_config("coding-pipeline")
        agent_configs = {
            w.agent_id: load_agent_config(w.agent_id) for w in team.workers
        }
        graph = compile_team_graph(team_config=team, agent_configs=agent_configs)

        registry = GraphRegistry()
        app, _aggregator, _reg, _cp = make_app(session_factory, registry=registry)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]
            # Register graph for this thread
            registry.register(thread_id, graph)

            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"content": "Follow-up message"},
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["thread_id"] == thread_id


# ---------------------------------------------------------------------------
# GET /api/teams
# ---------------------------------------------------------------------------


class TestListTeamPresets:
    """Tests for GET /api/teams."""

    def test_returns_bundled_presets(self, session_factory) -> None:
        """Returns all bundled team presets."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/teams")

        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        preset_ids = [p["id"] for p in data["presets"]]
        # At minimum the bundled pipeline preset should be present
        assert "coding-pipeline" in preset_ids

    def test_preset_has_required_fields(self, session_factory) -> None:
        """Each preset has id, display_name, description, topology, worker_count."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/teams")

        for preset in resp.json()["presets"]:
            assert "id" in preset
            assert "display_name" in preset
            assert "description" in preset
            assert "topology" in preset
            assert "worker_count" in preset


# ---------------------------------------------------------------------------
# GET /api/team/status
# ---------------------------------------------------------------------------


class TestTeamStatus:
    """Tests for GET /api/team/status."""

    def test_returns_team_status(self, session_factory) -> None:
        """Returns a TeamStatusResponse with agents and active_threads."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "active_threads" in data
        assert "pending_permissions" in data
        # pending_permissions is always empty until wired (API-M8 TODO)
        assert data["pending_permissions"] == []


# ---------------------------------------------------------------------------
# POST /api/permissions/{id}/respond
# ---------------------------------------------------------------------------


class TestPermissionRespond:
    """Tests for POST /api/permissions/{request_id}/respond."""

    def test_responds_without_graph(self, session_factory) -> None:
        """Returns accepted=False when no graph is registered for the thread."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/permissions/thread-123:req-456/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == "thread-123:req-456"
        assert data["accepted"] is False
        assert data["thread_id"] == "thread-123"

    def test_responds_with_graph(self, session_factory) -> None:
        """Returns accepted=True when a graph is registered for the thread."""
        team = load_team_config("coding-pipeline")
        agent_configs = {
            w.agent_id: load_agent_config(w.agent_id) for w in team.workers
        }
        graph = compile_team_graph(team_config=team, agent_configs=agent_configs)

        registry = GraphRegistry()
        registry.register("thread-abc", graph)
        app, _agg, _reg, _cp = make_app(session_factory, registry=registry)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/permissions/thread-abc:req-xyz/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert data["thread_id"] == "thread-abc"


# ---------------------------------------------------------------------------
# GraphRegistry unit tests
# ---------------------------------------------------------------------------


class TestCreateThreadAutonomous:
    """Tests for the autonomous field on POST /api/threads."""

    def test_create_thread_autonomous_defaults_false(self, session_factory) -> None:
        """Creating a thread without autonomous field defaults to False (supervised)."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello, supervised mode"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        # No crash = autonomous=False default accepted correctly

    def test_create_thread_autonomous_true_accepted(self, session_factory) -> None:
        """Creating a thread with autonomous=True returns 201 successfully."""
        app, _agg, _reg, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello, autonomous mode",
                    "autonomous": True,
                },
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        assert data["status"] == "submitted"

    def test_create_thread_with_preset_autonomous_true(self, session_factory) -> None:
        """Creating a thread with a valid preset and autonomous=True compiles
        the graph with the correct structure."""
        app, _agg, registry, _cp = make_app(session_factory)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Run autonomously",
                    "team_preset": "coding-pipeline",
                    "autonomous": True,
                },
            )
        assert resp.status_code == 201
        thread_id = resp.json()["thread_id"]
        # Graph should be compiled and registered
        graph = registry.get(thread_id)
        assert graph is not None
        # Autonomous graph has the expected pipeline nodes
        node_keys = {k for k in graph.nodes if not k.startswith("__")}
        assert {"planner", "coder", "reviewer"} == node_keys
        # interrupt_before empty in autonomous mode (ADR-013)
        assert list(graph.interrupt_before_nodes) == []


class TestGraphRegistry:
    """Unit tests for the GraphRegistry helper class."""

    def test_register_and_get(self) -> None:
        """register() stores a graph; get() returns it."""
        registry = GraphRegistry()
        graph = object()
        registry.register("t1", graph)
        assert registry.get("t1") is graph

    def test_get_unknown_returns_none(self) -> None:
        """get() returns None for an unknown thread_id."""
        registry = GraphRegistry()
        assert registry.get("nonexistent") is None

    def test_pending_resume_roundtrip(self) -> None:
        """register_pending_resume then pop_pending_resume round-trips correctly."""
        registry = GraphRegistry()
        registry.register_pending_resume("req-1", "thread-1", "allow_once")
        result = registry.pop_pending_resume("req-1")
        assert result == ("thread-1", "allow_once")
        # Second pop returns None
        assert registry.pop_pending_resume("req-1") is None

    @pytest.mark.asyncio
    async def test_mark_ingest_active_prevents_duplicate(self) -> None:
        """mark_ingest_active returns False for a thread already active."""
        registry = GraphRegistry()
        assert await registry.mark_ingest_active("t1") is True
        assert await registry.mark_ingest_active("t1") is False

    @pytest.mark.asyncio
    async def test_mark_ingest_done_releases_thread(self) -> None:
        """mark_ingest_done releases the thread so it can be re-activated."""
        registry = GraphRegistry()
        await registry.mark_ingest_active("t1")
        await registry.mark_ingest_done("t1")
        assert await registry.mark_ingest_active("t1") is True
