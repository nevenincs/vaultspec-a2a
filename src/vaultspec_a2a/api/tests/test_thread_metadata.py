"""Integration tests for ADR-014 Thread Metadata & Context Injection.

Uses FastAPI TestClient with a real in-memory SQLite database and real
fixtures. No mocks, no monkeypatching.

ADR-019: uses shared make_app() from conftest.py which overrides
get_checkpointer and get_worker_client so tests never touch vaultspec.db.
"""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import make_app as _make_app_4


def _make_app(session_factory, checkpointer, aggregator=None):
    """Shim: forwards to shared make_app(), dropping extra returns."""
    app, agg, _worker, _cp = _make_app_4(
        session_factory, checkpointer, aggregator=aggregator
    )
    return app, agg


# ---------------------------------------------------------------------------
# POST /threads with metadata
# ---------------------------------------------------------------------------


class TestCreateThreadWithMetadata:
    """Tests for POST /api/threads with metadata (ADR-014)."""

    def test_create_thread_with_metadata_stores_in_db(
        self, session_factory, checkpointer
    ) -> None:
        """Thread created with metadata stores it in the DB."""
        with tempfile.TemporaryDirectory() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
                "source_repo": "github.com/org/repo",
                "source_branch": "feat/auth",
                "callee": "claude-cli",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/threads",
                    json={
                        "initial_message": "Implement auth flow",
                        "metadata": metadata,
                    },
                )

            assert resp.status_code == 201
            data = resp.json()
            assert "thread_id" in data
            assert data["nickname"] is not None

    def test_create_thread_invalid_workspace_422(
        self, session_factory, checkpointer
    ) -> None:
        """Non-existent workspace_root returns 422."""
        app, _agg = _make_app(session_factory, checkpointer)
        metadata = {
            "workspace_root": "Y:/nonexistent/path/that/does/not/exist",
        }

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello",
                    "metadata": metadata,
                },
            )
        assert resp.status_code == 422

    def test_create_thread_auto_generates_nickname(
        self, session_factory, checkpointer
    ) -> None:
        """When no nickname is provided, one is auto-generated."""
        with tempfile.TemporaryDirectory() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/threads",
                    json={
                        "initial_message": "Hello",
                        "metadata": metadata,
                    },
                )

            assert resp.status_code == 201
            nick = resp.json()["nickname"]
            assert nick is not None
            assert "auth-flow" in nick

    def test_nickname_conflict_409(self, session_factory, checkpointer) -> None:
        """Duplicate nicknames return 409."""
        with tempfile.TemporaryDirectory() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "nickname": "unique-test-nick",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                resp1 = client.post(
                    "/api/threads",
                    json={
                        "initial_message": "First",
                        "metadata": metadata,
                    },
                )
                assert resp1.status_code == 201

                resp2 = client.post(
                    "/api/threads",
                    json={
                        "initial_message": "Second",
                        "metadata": metadata,
                    },
                )
                assert resp2.status_code == 409

    def test_legacy_thread_backward_compat(self, session_factory, checkpointer) -> None:
        """Threads without metadata work exactly as before."""
        app, _agg = _make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello", "title": "Legacy"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["nickname"] is None


# ---------------------------------------------------------------------------
# GET /threads — list with metadata fields
# ---------------------------------------------------------------------------


class TestListThreadsWithMetadata:
    """Tests for GET /api/threads with ADR-014 metadata fields."""

    def test_list_threads_includes_metadata_fields(
        self, session_factory, checkpointer
    ) -> None:
        """Thread list includes nickname, feature_tag, etc. from metadata."""
        with tempfile.TemporaryDirectory() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
                "source_branch": "feat/auth",
                "callee": "claude-cli",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                client.post(
                    "/api/threads",
                    json={
                        "initial_message": "Hello",
                        "metadata": metadata,
                    },
                )
                resp = client.get("/api/threads")

            assert resp.status_code == 200
            threads = resp.json()["threads"]
            assert len(threads) == 1
            t = threads[0]
            assert t["nickname"] is not None
            assert t["feature_tag"] == "auth-flow"
            assert t["source_branch"] == "feat/auth"
            assert t["callee"] == "claude-cli"

    def test_list_threads_legacy_without_metadata(
        self, session_factory, checkpointer
    ) -> None:
        """Legacy threads without metadata omit metadata fields gracefully."""
        app, _agg = _make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            client.post(
                "/api/threads",
                json={"initial_message": "Hello", "title": "Legacy"},
            )
            resp = client.get("/api/threads")

        threads = resp.json()["threads"]
        assert len(threads) == 1
        t = threads[0]
        assert t["nickname"] is None
        assert t["feature_tag"] is None
        assert t["source_branch"] is None
        assert t["callee"] is None


# ---------------------------------------------------------------------------
# GET /threads/{id}/metadata
# ---------------------------------------------------------------------------


class TestGetMetadataEndpoint:
    """Tests for GET /api/threads/{id}/metadata."""

    def test_get_metadata_endpoint(self, session_factory, checkpointer) -> None:
        """Returns full ThreadMetadata for a thread with metadata."""
        with tempfile.TemporaryDirectory() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
                "source_repo": "github.com/org/repo",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                create_resp = client.post(
                    "/api/threads",
                    json={
                        "initial_message": "Hello",
                        "metadata": metadata,
                    },
                )
                thread_id = create_resp.json()["thread_id"]
                resp = client.get(f"/api/threads/{thread_id}/metadata")

            assert resp.status_code == 200
            data = resp.json()
            assert data["workspace_root"] == ws
            assert data["feature_tag"] == "auth-flow"
            assert data["source_repo"] == "github.com/org/repo"

    def test_get_metadata_404_no_metadata(self, session_factory, checkpointer) -> None:
        """Returns 404 for a thread without metadata."""
        app, _agg = _make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]
            resp = client.get(f"/api/threads/{thread_id}/metadata")

        assert resp.status_code == 404

    def test_get_metadata_404_nonexistent_thread(
        self, session_factory, checkpointer
    ) -> None:
        """Returns 404 for a nonexistent thread."""
        app, _agg = _make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/nonexistent-id/metadata")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auto-discovery integration
# ---------------------------------------------------------------------------


class TestAutoDiscovery:
    """Tests for .vault/ auto-discovery via metadata."""

    def test_auto_discovery_populates_context_refs(
        self, session_factory, checkpointer
    ) -> None:
        """Auto-discovery populates context_refs when feature_tag is set."""
        with tempfile.TemporaryDirectory() as ws:
            # Create matching .vault/ documents
            research_dir = Path(ws) / ".vault" / "research"
            research_dir.mkdir(parents=True)
            (research_dir / "2026-02-28-auth-flow-research.md").write_text("# Research")

            plan_dir = Path(ws) / ".vault" / "plan"
            plan_dir.mkdir(parents=True)
            (plan_dir / "2026-02-28-auth-flow-plan.md").write_text("# Plan")

            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                create_resp = client.post(
                    "/api/threads",
                    json={
                        "initial_message": "Hello",
                        "metadata": metadata,
                    },
                )
                thread_id = create_resp.json()["thread_id"]
                meta_resp = client.get(f"/api/threads/{thread_id}/metadata")

            assert meta_resp.status_code == 200
            meta_data = meta_resp.json()
            refs = meta_data["context_refs"]
            assert len(refs) >= 2
            stages = {r["stage"] for r in refs}
            assert "research" in stages
            assert "plan" in stages
