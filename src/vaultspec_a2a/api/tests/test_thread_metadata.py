"""Integration tests for Thread Metadata & Context Injection.

Uses FastAPI TestClient with a real in-memory SQLite database and real
fixtures. No mocks, no monkeypatching.

Uses shared make_app() from conftest.py which overrides
get_checkpointer and get_worker_client so tests never touch vaultspec.db.
"""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from .conftest import catalog_run_fields
from .conftest import make_app as _make_app_4


def _run_workspace():
    """A throwaway workspace whose REMOVAL is not part of any assertion here.

    Resolving a selection for a brand-new workspace is a genuinely cold catalog
    read, and a cold read spawns a real provider CLI per external lane with this
    directory as its working directory. Discovery reaps each child before it
    returns, but Windows releases a dead process's working-directory handle
    asynchronously, so an immediate ``rmdir`` races that release and raises
    ``PermissionError`` (WinError 32) - after every assertion in the test has
    already run and passed.

    Cleanup is therefore best-effort. Nothing under test is relaxed: the tests
    below assert on stored metadata and discovered context refs, and a leftover
    temp directory is the OS's business, not theirs.
    """
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def _make_app(session_factory, checkpointer, aggregator=None):
    """Shim: forwards to shared make_app(), dropping extra returns."""
    app, agg, _worker, _cp = _make_app_4(
        session_factory, checkpointer, aggregator=aggregator
    )
    return app, agg


# A preset that declares no required roles, so a run starts without the
# engine-minted actor-token bundle the versioned verb demands of every
# production preset.
_BUNDLE_FREE_PRESET = "mock-success-single"


def _list_summaries(session_factory, checkpointer) -> tuple[dict[str, dict], int]:
    """Return the history reading of the run listing, keyed by run id.

    The nickname, branch and callee these cases are about are carried on the
    wire by the history reading, so they are asserted against the route a client
    actually consumes. ``state=all`` is explicit because the default reading is
    capped active-run discovery and answers with a narrower record.
    """
    app, _agg = _make_app(session_factory, checkpointer)
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.get("/v1/runs", params={"state": "all"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {run["run_id"]: run for run in body["runs"]}, body["total"]


# ---------------------------------------------------------------------------
# POST /v1/runs with metadata
# ---------------------------------------------------------------------------


class TestCreateThreadWithMetadata:
    """Tests for POST /v1/runs with metadata."""

    def test_create_thread_with_metadata_stores_in_db(
        self, session_factory, checkpointer
    ) -> None:
        """Thread created with metadata stores it in the DB."""
        with _run_workspace() as ws:
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
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": "Implement auth flow",
                        "metadata": metadata,
                        "run_id": "thread-meta-01",
                        "selection": catalog_run_fields(client, workspace_root=ws)[
                            "selection"
                        ],
                    },
                )

            assert resp.status_code == 201
            data = resp.json()
            assert "run_id" in data
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
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "Hello",
                    "metadata": metadata,
                    "run_id": "thread-meta-02",
                    # Resolved against a REAL workspace on purpose: this test's
                    # workspace_root is deliberately bogus, and the refusal
                    # under test is the run's. The catalog verb refuses a
                    # nonexistent workspace with its own 422, so deriving the
                    # selection from the bad path would fail earlier, inside
                    # the fixture, for a different reason.
                    "selection": catalog_run_fields(client)["selection"],
                },
            )
        assert resp.status_code == 422
        assert "existing directory" in resp.text

    def test_create_thread_auto_generates_nickname(
        self, session_factory, checkpointer
    ) -> None:
        """When no nickname is provided, one is auto-generated."""
        with _run_workspace() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": "Hello",
                        "metadata": metadata,
                        "run_id": "thread-meta-03",
                        "selection": catalog_run_fields(
                            client, workspace_root=metadata["workspace_root"]
                        )["selection"],
                    },
                )

            assert resp.status_code == 201
            nick = resp.json()["nickname"]
            assert nick is not None
            assert "auth-flow" in nick

    def test_nickname_conflict_409(self, session_factory, checkpointer) -> None:
        """Duplicate nicknames return 409."""
        with _run_workspace() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "nickname": "unique-test-nick",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                resp1 = client.post(
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": "First",
                        "metadata": metadata,
                        "run_id": "thread-meta-04",
                        "selection": catalog_run_fields(
                            client, workspace_root=metadata["workspace_root"]
                        )["selection"],
                    },
                )
                assert resp1.status_code == 201

                resp2 = client.post(
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": "Second",
                        "metadata": metadata,
                        "run_id": "thread-meta-05",
                        "selection": catalog_run_fields(
                            client, workspace_root=metadata["workspace_root"]
                        )["selection"],
                    },
                )
                assert resp2.status_code == 409

    def test_legacy_thread_backward_compat(self, session_factory, checkpointer) -> None:
        """A run that declares no nickname is auto-named rather than left null.

        This asserted a null nickname, which described a run carrying no
        metadata at all. That state is no longer reachable: run-start requires
        an explicit catalog selection, a selection is revalidated against the
        catalog served for its workspace, and the workspace is carried in
        metadata - so every run now has metadata whether or not the caller
        cared about it. The gateway names such a run itself, which is the
        behaviour worth pinning here.
        """
        app, _agg = _make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "Hello",
                    "title": "Legacy",
                    "run_id": "thread-meta-06",
                    **catalog_run_fields(client),
                },
            )

        assert resp.status_code == 201
        data = resp.json()
        assert isinstance(data["nickname"], str) and data["nickname"], (
            "a run with no caller-supplied nickname must still be named"
        )


# ---------------------------------------------------------------------------
# The run listing projection's metadata fields
# ---------------------------------------------------------------------------


class TestListThreadsWithMetadata:
    """Tests for the run listing projection's metadata fields."""

    def test_list_threads_includes_metadata_fields(
        self, session_factory, checkpointer
    ) -> None:
        """Thread list includes nickname, feature_tag, etc. from metadata."""
        with _run_workspace() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
                "source_branch": "feat/auth",
                "callee": "claude-cli",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                client.post(
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": "Hello",
                        "metadata": metadata,
                        "run_id": "thread-meta-07",
                        "selection": catalog_run_fields(
                            client, workspace_root=metadata["workspace_root"]
                        )["selection"],
                    },
                )
            summaries, _total = _list_summaries(session_factory, checkpointer)
            assert len(summaries) == 1
            t = next(iter(summaries.values()))
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
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "Hello",
                    "title": "Legacy",
                    "run_id": "thread-meta-08",
                    **catalog_run_fields(client),
                },
            )
        summaries, _total = _list_summaries(session_factory, checkpointer)
        assert len(summaries) == 1
        t = next(iter(summaries.values()))
        # The gateway names every run, so the listing's nickname is populated
        # even when the caller supplied none. The fields the caller genuinely
        # did not declare are the ones that stay empty, and they are what this
        # row is asserting.
        assert t["nickname"]
        assert not t["feature_tag"]
        assert not t["source_branch"]
        assert not t["callee"]


# ---------------------------------------------------------------------------
# GET /v1/runs/{id}/history — metadata
# ---------------------------------------------------------------------------


class TestGetMetadataEndpoint:
    """Tests for the metadata the versioned history verb carries."""

    def test_get_metadata_endpoint(self, session_factory, checkpointer) -> None:
        """Returns full ThreadMetadata for a thread with metadata."""
        with _run_workspace() as ws:
            app, _agg = _make_app(session_factory, checkpointer)
            metadata = {
                "workspace_root": ws,
                "feature_tag": "auth-flow",
                "source_repo": "github.com/org/repo",
            }

            with TestClient(app, raise_server_exceptions=True) as client:
                create_resp = client.post(
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": "Hello",
                        "metadata": metadata,
                        "run_id": "thread-meta-09",
                        "selection": catalog_run_fields(
                            client, workspace_root=metadata["workspace_root"]
                        )["selection"],
                    },
                )
                thread_id = create_resp.json()["run_id"]
                resp = client.get(f"/v1/runs/{thread_id}/history")

            assert resp.status_code == 200
            data = resp.json()["metadata"]
            assert data["workspace_root"] == ws
            assert data["feature_tag"] == "auth-flow"
            assert data["source_repo"] == "github.com/org/repo"

    def test_metadata_reads_back_minted_for_a_run_that_declared_none(
        self, session_factory, checkpointer
    ) -> None:
        """A run that declared nothing of its own reads back what was minted.

        This once asserted null metadata for a metadata-less run. That state is
        unreachable now: the selection is revalidated against the catalog
        served for its workspace, the workspace rides in metadata, and a run
        without it is refused before anything durable exists - so every run has
        metadata whether or not the caller cared. What the history verb must
        therefore serve for a minimal run is the MINTED envelope: the admitted
        workspace and the gateway-assigned nickname present, and the source
        fields the caller genuinely never declared empty rather than invented.
        """
        app, _agg = _make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            fields = catalog_run_fields(client)
            create_resp = client.post(
                "/v1/runs",
                json={
                    "team_preset": _BUNDLE_FREE_PRESET,
                    "message": "Hello",
                    "run_id": "thread-meta-10",
                    **fields,
                },
            )
            assert create_resp.status_code == 201, create_resp.text
            thread_id = create_resp.json()["run_id"]
            resp = client.get(f"/v1/runs/{thread_id}/history")

        assert resp.status_code == 200
        data = resp.json()["metadata"]
        assert data is not None, "every admitted run carries minted metadata"
        assert (
            Path(data["workspace_root"]).resolve()
            == Path(fields["metadata"]["workspace_root"]).resolve()
        )
        assert data["nickname"]
        assert not data["feature_tag"]
        assert not data["source_repo"]
        assert not data["source_branch"]
        assert not data["callee"]

    def test_history_404_nonexistent_thread(
        self, session_factory, checkpointer
    ) -> None:
        """Returns 404 when the run itself does not exist."""
        app, _agg = _make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/v1/runs/nonexistent-id/history")

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
        with _run_workspace() as ws:
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
                    "/v1/runs",
                    json={
                        "team_preset": _BUNDLE_FREE_PRESET,
                        "message": "Hello",
                        "metadata": metadata,
                        "run_id": "thread-meta-11",
                        "selection": catalog_run_fields(
                            client, workspace_root=metadata["workspace_root"]
                        )["selection"],
                    },
                )
                thread_id = create_resp.json()["run_id"]
                meta_resp = client.get(f"/v1/runs/{thread_id}/history")

            assert meta_resp.status_code == 200
            meta_data = meta_resp.json()["metadata"]
            refs = meta_data["context_refs"]
            assert len(refs) >= 2
            stages = {r["stage"] for r in refs}
            assert "research" in stages
            assert "plan" in stages
