"""Tests for the REST endpoints (ADR-019 refactored).

Uses FastAPI TestClient with a real in-memory SQLite database and a real
EventAggregator (no mocks).  Dispatch requests to the worker are captured
by a real in-process FastAPI ASGI app (ASGITransport) — no MockTransport,
no unittest.mock.

ADR-019: Graph compilation and ingest no longer run in the gateway.
All work is dispatched to the worker via HTTP POST to /dispatch.  Tests
verify that the correct dispatch requests are sent.

API-C1: all injected test dependencies are applied via the shared `make_app()`
helper in `conftest.py` so tests never touch the production `vaultspec.db`.
"""

import asyncio
import hashlib
import logging

import httpx
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Interrupt
from sqlalchemy import select

from ...control.config import settings
from ...database import (
    create_control_action,
    create_thread,
    record_permission_request,
    record_permission_response_submission,
)
from ...database.models import (
    PermissionRequestModel,
    ThreadExecutionStateModel,
    ThreadModel,
)
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ControlActionResultStatus, ControlActionType
from .conftest import make_app

# ---------------------------------------------------------------------------
# POST /threads
# ---------------------------------------------------------------------------


class TestCreateThread:
    """Tests for POST /api/threads."""

    def test_creates_thread_without_preset(self, session_factory, checkpointer) -> None:
        """Creating a thread without team_preset returns 201 with thread_id."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello", "title": "Test thread"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        assert data["status"] == "submitted"

    def test_creates_thread_with_preset_dispatches_to_worker(
        self, session_factory, checkpointer
    ) -> None:
        """Creating a thread with a valid preset dispatches ingest to worker."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello",
                    "team_preset": "vaultspec-structured-coder",
                },
            )
        assert resp.status_code == 201
        thread_id = resp.json()["thread_id"]

        # Verify dispatch was sent to worker
        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "ingest"
        assert dispatch["thread_id"] == thread_id
        assert dispatch["team_preset"] == "vaultspec-structured-coder"
        assert dispatch["content"] == "Hello"

    def test_dispatch_includes_internal_token_when_configured(
        self, session_factory, checkpointer
    ) -> None:
        """Gateway dispatch should keep working when worker auth is enabled."""
        original_token = settings.internal_token
        settings.internal_token = "test-internal-token"
        try:
            app, _agg, worker, _cp = make_app(session_factory, checkpointer)
            with TestClient(app, raise_server_exceptions=True) as client:
                resp = client.post(
                    "/api/threads",
                    json={
                        "initial_message": "Hello",
                        "team_preset": "vaultspec-structured-coder",
                    },
                )
            assert resp.status_code == 201
            assert len(worker.dispatches) == 1
            assert worker.dispatches[0]["action"] == "ingest"
        finally:
            settings.internal_token = original_token

    def test_initial_message_length_limit(self, session_factory, checkpointer) -> None:
        """initial_message exceeding 64KB is rejected with validation error."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
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

    def test_empty_list(self, session_factory, checkpointer) -> None:
        """Returns an empty list when no threads exist."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")
        assert resp.status_code == 200
        data = resp.json()
        assert data["threads"] == []
        assert data["total"] == 0

    def test_lists_created_threads(self, session_factory, checkpointer) -> None:
        """Returns threads that were created."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

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

    def test_list_threads_hides_unreadable_plan_approval_metadata(
        self, session_factory, checkpointer
    ) -> None:
        """Thread summaries must not expose corrupt plan-approval state."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_corrupt_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-list-corrupt-plan",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-list-corrupt-plan"
                await record_permission_request(
                    session,
                    request_id="perm-list-corrupt-plan",
                    thread_id="thread-list-corrupt-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call="plan_approval",
                )
                permission = await session.get(
                    PermissionRequestModel,
                    "perm-list-corrupt-plan",
                )
                assert permission is not None
                permission.allowed_options_json = '{"broken":'
                await session.commit()

        asyncio.run(_seed_corrupt_plan_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-corrupt-plan"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_hides_optionless_plan_approval_metadata(
        self, session_factory, checkpointer
    ) -> None:
        """Thread summaries must not expose optionless plan-approval state."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_optionless_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-list-optionless-plan",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-list-optionless-plan"
                await record_permission_request(
                    session,
                    request_id="perm-list-optionless-plan",
                    thread_id="thread-list-optionless-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve plan?",
                    allowed_options=[],
                    tool_call="plan_approval",
                )
                await session.commit()

        asyncio.run(_seed_optionless_plan_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-optionless-plan"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_clears_stale_missing_plan_approval_pointer(
        self, session_factory, checkpointer
    ) -> None:
        """Thread summaries must not expose a missing pending plan approval."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_missing_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-list-missing-plan",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-list-missing-plan"
                await session.commit()

        asyncio.run(_seed_missing_plan_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-missing-plan"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_prefers_live_plan_approval_over_stale_thread_pointer(
        self, session_factory, checkpointer
    ) -> None:
        """Thread summaries must resolve pending approval from live durable rows."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_live_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-list-live-plan",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-list-stale-plan"
                await record_permission_request(
                    session,
                    request_id="perm-list-live-plan",
                    thread_id="thread-list-live-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve live plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call="plan_approval",
                )
                await session.commit()

        asyncio.run(_seed_live_plan_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-live-plan"
        )
        assert thread["approval_status"] == "pending"
        assert thread["approval_request_id"] == "perm-list-live-plan"

    def test_list_threads_clears_terminal_thread_pending_approval(
        self, session_factory, checkpointer
    ) -> None:
        """Thread summaries must not keep pending approval on terminal threads."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_terminal_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-list-terminal-plan",
                    status="completed",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-list-terminal-plan"
                await record_permission_request(
                    session,
                    request_id="perm-list-terminal-plan",
                    thread_id="thread-list-terminal-plan",
                    pause_reason_type="plan_approval_request",
                    description="Approve stale terminal plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call="plan_approval",
                )
                await session.commit()

        asyncio.run(_seed_terminal_plan_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-terminal-plan"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_hides_answered_pending_apply_plan_approval(
        self, session_factory, checkpointer
    ) -> None:
        """List summaries must not expose already-answered approvals as pending."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_answered_plan_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-list-answered-pending-apply",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-list-answered-pending-apply"
                await record_permission_request(
                    session,
                    request_id="perm-list-answered-pending-apply",
                    thread_id="thread-list-answered-pending-apply",
                    pause_reason_type="plan_approval_request",
                    description="Already answered plan approval",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await record_permission_response_submission(
                    session,
                    request_id="perm-list-answered-pending-apply",
                    option_id="approve",
                    idempotency_key="idem-list-answered-pending-apply",
                )
                await session.commit()

        asyncio.run(_seed_answered_plan_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-answered-pending-apply"
        )
        assert thread["approval_status"] is None
        assert thread["approval_request_id"] is None

    def test_list_threads_degrades_stale_execution_state_lineage(
        self, session_factory, checkpointer
    ) -> None:
        """Thread summaries must not keep healthy readiness on stale lineage."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_stale_execution_state() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-list-stale-state",
                    status="running",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.recovery_epoch = 5
                session.add(
                    ThreadExecutionStateModel(
                        thread_id="thread-list-stale-state",
                        checkpoint_id="cp-list-stale-state",
                        parent_checkpoint_id=None,
                        recovery_epoch=2,
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

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-stale-state"
        )
        assert thread["repair_status"] == "needs_reconciliation"
        assert thread["execution_readiness"] == "needs_reconciliation"

    def test_list_threads_degrades_checkpoint_mismatched_execution_state(
        self, session_factory, checkpointer
    ) -> None:
        """Thread summaries must not stay healthy when checkpoint ids drift."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_checkpoint_mismatch() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-list-current"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-list-checkpoint-drift",
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
                    thread_id="thread-list-checkpoint-drift",
                    status="running",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                session.add(
                    ThreadExecutionStateModel(
                        thread_id="thread-list-checkpoint-drift",
                        checkpoint_id="cp-list-stale",
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

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-checkpoint-drift"
        )
        assert thread["repair_status"] == "needs_reconciliation"
        assert thread["execution_readiness"] == "needs_reconciliation"

    def test_list_threads_degrades_when_checkpoint_probe_is_unverified(
        self, session_factory, tmp_path
    ) -> None:
        """Thread summaries must fail closed when checkpoint probing fails."""
        checkpoints_file = tmp_path / "closed-list-threads-checkpoints.db"

        async def _closed_checkpointer() -> AsyncSqliteSaver:
            async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as cp:
                await cp.setup()
                return cp

        closed_checkpointer = asyncio.run(_closed_checkpointer())
        app, _agg, _worker, _cp = make_app(session_factory, closed_checkpointer)

        async def _seed_thread() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="thread-list-checkpoint-unverified",
                    status="running",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads")

        assert resp.status_code == 200
        data = resp.json()
        thread = next(
            item
            for item in data["threads"]
            if item["thread_id"] == "thread-list-checkpoint-unverified"
        )
        assert thread["repair_status"] == "checkpoint_unavailable"
        assert thread["execution_readiness"] == "checkpoint_unavailable"


class TestHealth:
    """Tests for GET /health."""

    def test_reports_sqlite_fallback_diagnostics(
        self, session_factory, checkpointer
    ) -> None:
        """Public health should expose explicit SQLite fallback diagnostics."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
        app.state.sqlite_fallback_diagnostics = {
            "active": True,
            "busy_timeout_ms": 5000,
            "production_certifying": False,
            "limitations": ["sqlite_fallback_not_production_certifying"],
            "database": {"path": "test.db", "wal_enabled": True, "journal_mode": "wal"},
        }

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sqlite_fallback"]["active"] is True
        assert data["sqlite_fallback"]["database"]["journal_mode"] == "wal"


# ---------------------------------------------------------------------------
# GET /threads/{id}/state
# ---------------------------------------------------------------------------


class TestThreadState:
    """Tests for GET /api/threads/{id}/state."""

    def test_404_for_unknown_thread(self, session_factory, checkpointer) -> None:
        """Returns 404 for a thread that does not exist."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/nonexistent/state")
        assert resp.status_code == 404

    def test_returns_snapshot_for_existing_thread(
        self, session_factory, checkpointer
    ) -> None:
        """Returns a ThreadStateSnapshot for a known thread."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

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
        assert "checkpoint_parent_id" in data
        assert "checkpoint_source" in data
        assert "checkpoint_step" in data
        assert data["checkpoint_updated_channels"] == []
        assert data["pending_write_channels"] == []
        assert data["pending_write_count"] == 0
        assert data["next_nodes"] == []
        assert data["task_count"] == 0
        assert data["pending_interrupt_count"] == 0
        assert data["execution_tasks"] == []

    def test_state_handles_unreadable_durable_permission_rows(
        self, session_factory, checkpointer
    ) -> None:
        """Corrupted durable permission rows must not crash the state endpoint."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _corrupt_permission() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-corrupt-permission-state"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-corrupt-permission-state",
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
                    thread_id="thread-corrupt-permission-state",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await record_permission_request(
                    session,
                    request_id="perm-corrupt",
                    thread_id="thread-corrupt-permission-state",
                    pause_reason_type="permission_request",
                    description="Allow file write?",
                    allowed_options=[{"option_id": "allow_once", "name": "Allow Once"}],
                    tool_call="bash",
                )
                permission = await session.get(
                    PermissionRequestModel,
                    "perm-corrupt",
                )
                assert permission is not None
                permission.allowed_options_json = '{"broken":'
                await session.commit()

        asyncio.run(_corrupt_permission())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/thread-corrupt-permission-state/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert data["snapshot_complete"] is False
        assert "permission_projection_unreadable" in data["degraded_reasons"]
        assert data["repair_status"] == "operator_intervention_required"
        assert data["execution_readiness"] == "operator_intervention_required"

    def test_state_degrades_stale_execution_state_lineage(
        self, session_factory, checkpointer
    ) -> None:
        """Stale durable execution-state rows must not leave `/state` healthy."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_stale_execution_state() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-fresh-state-endpoint"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-stale-state-endpoint",
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
                    thread_id="thread-stale-state-endpoint",
                    status="running",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread = await session.get(ThreadModel, "thread-stale-state-endpoint")
                assert thread is not None
                thread.recovery_epoch = 4
                session.add(
                    ThreadExecutionStateModel(
                        thread_id="thread-stale-state-endpoint",
                        checkpoint_id="cp-fresh-state-endpoint",
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

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/thread-stale-state-endpoint/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshot_complete"] is False
        assert "execution_state_projection_stale" in data["degraded_reasons"]
        assert data["repair_status"] == "needs_reconciliation"
        assert data["execution_readiness"] == "needs_reconciliation"
        assert data["next_nodes"] == []
        assert data["task_count"] == 0
        assert data["pending_interrupt_count"] == 0
        assert data["execution_tasks"] == []

    def test_state_preserves_plan_approval_without_tool_call(
        self, session_factory, checkpointer
    ) -> None:
        """A durable plan approval remains visible even if tool_call is null."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_plan_without_tool_call() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-plan-no-tool-call-endpoint"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-plan-no-tool-call-endpoint",
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
                    thread_id="thread-plan-no-tool-call-endpoint",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-plan-no-tool-call-endpoint"
                await record_permission_request(
                    session,
                    request_id="perm-plan-no-tool-call-endpoint",
                    thread_id="thread-plan-no-tool-call-endpoint",
                    pause_reason_type="plan_approval_request",
                    description="Approve plan?",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_plan_without_tool_call())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/thread-plan-no-tool-call-endpoint/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_status"] == "pending"
        assert data["approval_request_id"] == "perm-plan-no-tool-call-endpoint"
        assert len(data["pending_permissions"]) == 1
        assert data["pending_permissions"][0]["tool_call"] == "plan_approval"

    def test_state_excludes_aggregator_only_pending_permission(
        self, session_factory, checkpointer
    ) -> None:
        """Thread state must not expose permissions without durable backing."""
        import time

        from ...graph.events import PermissionRequest

        agg = EventAggregator()
        event = PermissionRequest(
            thread_id="thread-state-aggregator-only",
            agent_id="vaultspec-coder",
            timestamp=time.time(),
            request_id="thread-state-aggregator-only:perm-1",
            description="Allow file write?",
            options=[],
        )
        agg._emitters._pending_permissions["thread-state-aggregator-only:perm-1"] = (
            event,
            0.0,
        )

        app, _agg, _worker, _cp = make_app(
            session_factory,
            checkpointer,
            aggregator=agg,
        )

        async def _seed_thread() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-thread-state-aggregator-only"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-state-aggregator-only",
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
                    thread_id="thread-state-aggregator-only",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/thread-state-aggregator-only/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert data["approval_status"] is None
        assert data["approval_request_id"] is None
        assert data["pause_cause"] is None

    def test_state_hides_pending_approval_when_checkpoint_is_unavailable(
        self, session_factory, tmp_path
    ) -> None:
        """Thread state must not expose approvals without checkpoint access."""
        checkpoints_file = tmp_path / "missing-thread-state-permission-checkpoints.db"

        async def _open_checkpointer() -> AsyncSqliteSaver:
            return await AsyncSqliteSaver.from_conn_string(
                str(checkpoints_file)
            ).__aenter__()

        missing_checkpointer = asyncio.run(_open_checkpointer())
        app, _agg, _worker, _cp = make_app(
            session_factory,
            missing_checkpointer,
        )

        async def _seed_thread() -> None:
            async with session_factory() as session:
                thread = await create_thread(
                    session,
                    thread_id="thread-state-missing-checkpoint-permission",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = (
                    "perm-thread-state-missing-checkpoint-permission"
                )
                await record_permission_request(
                    session,
                    request_id="perm-thread-state-missing-checkpoint-permission",
                    thread_id="thread-state-missing-checkpoint-permission",
                    pause_reason_type="plan_approval_request",
                    description="Approve missing-checkpoint plan",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get(
                "/api/threads/thread-state-missing-checkpoint-permission/state"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert data["approval_status"] is None
        assert data["approval_request_id"] is None
        assert data["pause_cause"] is None
        assert data["repair_status"] == "checkpoint_unavailable"
        assert data["execution_readiness"] == "checkpoint_unavailable"
        assert "checkpoint_unavailable" in data["degraded_reasons"]
        assert "pending_permission_without_checkpoint_truth" in data["degraded_reasons"]

    def test_state_excludes_terminal_thread_pending_permission_residue(
        self, session_factory, checkpointer
    ) -> None:
        """Thread state must not expose stale pending approvals on terminal threads."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_terminal_thread() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-thread-state-terminal-permission-residue"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-state-terminal-permission-residue",
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
                    thread_id="thread-state-terminal-permission-residue",
                    status="completed",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = (
                    "perm-thread-state-terminal-permission-residue"
                )
                await record_permission_request(
                    session,
                    request_id="perm-thread-state-terminal-permission-residue",
                    thread_id="thread-state-terminal-permission-residue",
                    pause_reason_type="plan_approval_request",
                    description="Stale terminal plan approval",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await session.commit()

        asyncio.run(_seed_terminal_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get(
                "/api/threads/thread-state-terminal-permission-residue/state"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert data["approval_status"] is None
        assert data["approval_request_id"] is None
        assert "terminal_thread_pending_permission_residue" in data["degraded_reasons"]
        assert data["repair_status"] == "needs_reconciliation"
        assert data["execution_readiness"] == "needs_reconciliation"

    def test_state_excludes_answered_pending_apply_permission(
        self, session_factory, checkpointer
    ) -> None:
        """Thread state must not expose already-answered permissions as pending."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_answered_permission() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-thread-state-answered-pending-apply"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-state-answered-pending-apply",
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
                    thread_id="thread-state-answered-pending-apply",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                thread.approval_status = "pending"
                thread.approval_request_id = "perm-thread-state-answered-pending-apply"
                await record_permission_request(
                    session,
                    request_id="perm-thread-state-answered-pending-apply",
                    thread_id="thread-state-answered-pending-apply",
                    pause_reason_type="plan_approval_request",
                    description="Already answered plan approval",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await record_permission_response_submission(
                    session,
                    request_id="perm-thread-state-answered-pending-apply",
                    option_id="approve",
                    idempotency_key="idem-thread-state-answered-pending-apply",
                )
                await session.commit()

        asyncio.run(_seed_answered_permission())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/thread-state-answered-pending-apply/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert data["approval_status"] is None
        assert data["approval_request_id"] is None
        assert data["pause_cause"] is None

    def test_state_excludes_checkpoint_only_pending_permission(
        self, session_factory, checkpointer
    ) -> None:
        """Thread state must not expose checkpoint-only actionable permissions."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_thread() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-thread-state-checkpoint-only"
            config = await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-state-checkpoint-only",
                        "checkpoint_ns": "",
                    }
                },
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                {},
            )
            await checkpointer.aput_writes(
                config,
                [
                    (
                        "__interrupt__",
                        [
                            Interrupt(
                                value={
                                    "type": "permission_request",
                                    "tool_name": "bash",
                                    "options": [
                                        {
                                            "optionId": "allow_once",
                                            "name": "Allow Once",
                                        }
                                    ],
                                },
                                id="perm-thread-state-checkpoint-only",
                            )
                        ],
                    )
                ],
                task_id="task-thread-state-checkpoint-only",
            )
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="thread-state-checkpoint-only",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/threads/thread-state-checkpoint-only/state")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert data["approval_status"] is None
        assert data["approval_request_id"] is None
        assert "checkpoint_permission_without_durable_row" in data["degraded_reasons"]
        assert data["repair_status"] == "needs_reconciliation"
        assert data["execution_readiness"] == "needs_reconciliation"


# ---------------------------------------------------------------------------
# POST /threads/{id}/messages
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Tests for POST /api/threads/{id}/messages."""

    def test_404_for_unknown_thread(self, session_factory, checkpointer) -> None:
        """Returns 404 when the thread does not exist."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads/nonexistent/messages",
                json={"content": "Hello"},
            )
        assert resp.status_code == 404

    def test_202_accepted_dispatches_to_worker(
        self, session_factory, checkpointer
    ) -> None:
        """Returns 202 and dispatches ingest to worker."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            thread_id = create_resp.json()["thread_id"]
            worker.clear()  # Clear the create dispatch if any

            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"content": "Follow-up message"},
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["thread_id"] == thread_id

        # Verify dispatch was sent to worker
        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "ingest"
        assert dispatch["thread_id"] == thread_id
        assert dispatch["content"] == "Follow-up message"
        assert dispatch["agent_id"] == "vaultspec-supervisor"

    def test_followup_dispatch_marks_message_followup_as_applied(
        self, session_factory, checkpointer
    ) -> None:
        """Successful follow-up dispatch must stamp the applied action correctly."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            worker.clear()

            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"content": "Follow-up message"},
            )

        assert resp.status_code == 202
        assert len(worker.dispatches) == 1

        async def _assert_state() -> None:
            async with session_factory() as session:
                thread = await session.get(ThreadModel, thread_id)
                assert thread is not None
                assert thread.repair_status == "healthy"
                assert thread.execution_readiness == "healthy"
                assert (
                    thread.last_requested_action
                    == ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value
                )
                assert (
                    thread.last_applied_action
                    == ControlActionType.MESSAGE_FOLLOWUP_APPLIED.value
                )

        asyncio.run(_assert_state())

    def test_dispatch_includes_team_preset(self, session_factory, checkpointer) -> None:
        """Ingest DispatchRequest includes team_preset from DB for lazy recompile."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello",
                    "team_preset": "vaultspec-structured-coder",
                },
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            worker.dispatches.clear()

            resp = client.post(
                f"/api/threads/{thread_id}/messages",
                json={"content": "Follow-up"},
            )

        assert resp.status_code == 202
        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "ingest"
        assert dispatch["team_preset"] == "vaultspec-structured-coder"

    def test_content_length_limit(self, session_factory, checkpointer) -> None:
        """content exceeding 64KB is rejected with 422."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
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


# ---------------------------------------------------------------------------
# GET /api/teams
# ---------------------------------------------------------------------------


class TestListTeamPresets:
    """Tests for GET /api/teams."""

    def test_returns_bundled_presets(self, session_factory, checkpointer) -> None:
        """Returns all bundled team presets."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/teams")

        assert resp.status_code == 200
        data = resp.json()
        assert "presets" in data
        preset_ids = [p["id"] for p in data["presets"]]
        # At minimum the bundled pipeline preset should be present
        assert "vaultspec-structured-coder" in preset_ids

    def test_preset_has_required_fields(self, session_factory, checkpointer) -> None:
        """Each preset has id, display_name, description, topology, worker_count."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

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

    def test_returns_team_status(self, session_factory, checkpointer) -> None:
        """Returns a TeamStatusResponse with agents and active_threads."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "active_threads" in data
        assert "pending_permissions" in data

    def test_team_status_excludes_answered_pending_apply_permission(
        self, session_factory, checkpointer
    ) -> None:
        """Team status must not advertise answered permissions as pending."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_answered_permission() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="team-status-answered-pending-apply",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await record_permission_request(
                    session,
                    request_id="team-status-answered-pending-apply:perm-1",
                    thread_id="team-status-answered-pending-apply",
                    pause_reason_type="plan_approval_request",
                    description="Already answered plan approval",
                    allowed_options=[{"option_id": "approve", "name": "Approve"}],
                    tool_call=None,
                )
                await record_permission_response_submission(
                    session,
                    request_id="team-status-answered-pending-apply:perm-1",
                    option_id="approve",
                    idempotency_key="idem-team-status-answered-pending-apply",
                )
                await session.commit()

        asyncio.run(_seed_answered_permission())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []
        assert isinstance(data["agents"], list)
        assert isinstance(data["active_threads"], list)
        assert isinstance(data["pending_permissions"], list)

    def test_returns_empty_lists_when_no_activity(
        self, session_factory, checkpointer
    ) -> None:
        """All lists are empty when no agents registered and no threads active."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["agents"] == []
        assert data["active_threads"] == []
        assert data["pending_permissions"] == []

    def test_pending_permissions_do_not_surface_from_aggregator_without_durable_row(
        self, session_factory, checkpointer
    ) -> None:
        """Aggregator-only pending permissions must not appear in team status."""
        import time

        from ...graph.events import PermissionRequest

        agg = EventAggregator()
        # Inject a pending permission via the emitters sub-component
        event = PermissionRequest(
            thread_id="thread-abc",
            agent_id="vaultspec-coder",
            timestamp=time.time(),
            request_id="thread-abc:perm-001",
            description="Allow file write?",
            options=[],
        )
        agg._emitters._pending_permissions["thread-abc:perm-001"] = (
            event,
            0.0,
        )

        app, _agg, _worker, _cp = make_app(
            session_factory, checkpointer, aggregator=agg
        )

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_permissions"] == []

    def test_pending_permissions_hide_malformed_durable_rows(
        self, session_factory, checkpointer
    ) -> None:
        """Team status must not advertise durable rows the respond path rejects."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_malformed_permission() -> None:
            async with session_factory() as session:
                await create_thread(
                    session,
                    thread_id="team-status-malformed-durable",
                    status="input_required",
                    repair_status="healthy",
                    execution_readiness="healthy",
                )
                await record_permission_request(
                    session,
                    request_id="team-status-malformed-durable:perm-1",
                    thread_id="team-status-malformed-durable",
                    pause_reason_type="permission_request",
                    description="Malformed durable permission",
                    allowed_options=[{"option_id": "allow_once", "name": "Allow"}],
                    tool_call="bash",
                )
                permission = await session.get(
                    PermissionRequestModel,
                    "team-status-malformed-durable:perm-1",
                )
                assert permission is not None
                permission.allowed_options_json = '{"broken":'
                await session.commit()

        asyncio.run(_seed_malformed_permission())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "team-status-malformed-durable" in data["active_threads"]
        assert data["pending_permissions"] == []

    def test_node_summaries_surface_as_agents(
        self, session_factory, checkpointer
    ) -> None:
        """Agents registered via aggregator node metadata appear in response."""
        agg = EventAggregator()
        agg._subscribers_mgr.set_node_metadata(
            {
                "vaultspec-coder": {
                    "role": "coder",
                    "display_name": "Coder Agent",
                    "description": "Writes code",
                },
            }
        )

        app, _agg, _worker, _cp = make_app(
            session_factory, checkpointer, aggregator=agg
        )

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/api/team/status")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["agents"]) == 1
        agent = data["agents"][0]
        assert agent["agent_id"] == "vaultspec-coder"
        assert agent["node_name"] == "vaultspec-coder"
        assert agent["role"] == "coder"
        assert agent["display_name"] == "Coder Agent"
        assert agent["state"] == "idle"


# ---------------------------------------------------------------------------
# POST /api/permissions/{id}/respond
# ---------------------------------------------------------------------------


class TestPermissionRespond:
    """Tests for POST /api/permissions/{request_id}/respond."""

    @staticmethod
    def _seed_permission(
        session_factory, *, thread_id: str, request_id: str, tool_call: str = "bash"
    ) -> None:
        async def _run() -> None:
            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=thread_id,
                    pause_reason_type=tool_call,
                    description="Allow action?",
                    allowed_options=[
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
                    ],
                    tool_call=tool_call,
                )
                await session.commit()

        asyncio.run(_run())

    def test_responds_dispatches_resume_to_worker(
        self, session_factory, checkpointer, caplog
    ) -> None:
        """Dispatches a resume to the worker and returns accepted=True."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with (
            caplog.at_level(
                logging.INFO,
                logger="vaultspec_a2a.api.routes.permissions",
            ),
            TestClient(app, raise_server_exceptions=True) as client,
        ):
            # Create a thread first so the permission endpoint can find it.
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-456"
            self._seed_permission(
                session_factory, thread_id=thread_id, request_id=request_id
            )

            # The create dispatch is captured; clear it so we only check resume.
            worker.dispatches.clear()

            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == request_id
        assert data["accepted"] is True
        assert data["thread_id"] == thread_id

        # Verify resume dispatch was sent to worker
        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "resume"
        assert dispatch["thread_id"] == thread_id
        assert dispatch["option_id"] == "allow_once"
        record = next(
            rec
            for rec in caplog.records
            if "Dispatching resume dispatch_id=" in rec.message
        )
        assert record.thread_id == thread_id
        assert record.request_id == request_id
        assert record.dispatch_id == dispatch["dispatch_id"]
        assert record.action == "resume"
        assert record.option_id == "allow_once"

    def test_respond_success_marks_permission_response_submitted_as_applied(
        self, session_factory, checkpointer
    ) -> None:
        """Successful resume dispatch must stamp the repair row as applied."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-applied-state"
            self._seed_permission(
                session_factory, thread_id=thread_id, request_id=request_id
            )

            worker.dispatches.clear()
            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 200
        assert len(worker.dispatches) == 1

        async def _assert_state() -> None:
            async with session_factory() as session:
                thread = await session.get(ThreadModel, thread_id)
                assert thread is not None
                assert thread.repair_status == "healthy"
                assert thread.execution_readiness == "healthy"
                assert (
                    thread.last_requested_action
                    == ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value
                )
                assert (
                    thread.last_applied_action
                    == ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value
                )

        asyncio.run(_assert_state())

    def test_resume_dispatch_includes_team_preset(
        self, session_factory, checkpointer
    ) -> None:
        """Resume DispatchRequest includes team_preset from DB for lazy recompile."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            # First create a thread with a team_preset so it's stored in DB.
            create_resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Hello",
                    "team_preset": "vaultspec-structured-coder",
                },
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-001"
            self._seed_permission(
                session_factory, thread_id=thread_id, request_id=request_id
            )

            # Now respond to a permission for that thread.
            worker.dispatches.clear()
            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 200
        assert resp.json()["accepted"] is True

        # The resume dispatch must carry team_preset for lazy recompile.
        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "resume"
        assert dispatch["team_preset"] == "vaultspec-structured-coder"

    def test_responds_without_thread_id_returns_not_accepted(
        self, session_factory, checkpointer
    ) -> None:
        """Returns accepted=False when request_id has no thread_id component."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/permissions/no-colon-here/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is False

    def test_rejects_unknown_option_id_without_dispatching(
        self, session_factory, checkpointer
    ) -> None:
        """Hostile option ids must be rejected before they reach the worker."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-invalid"
            self._seed_permission(
                session_factory, thread_id=thread_id, request_id=request_id
            )

            worker.dispatches.clear()
            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "hostile-option"},
            )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Unknown permission option for this request"
        assert worker.dispatches == []

        async def _assert_state() -> None:
            from ...database.models import PermissionRequestModel

            async with session_factory() as session:
                permission = await session.get(PermissionRequestModel, request_id)
                assert permission is not None
                assert permission.request_status == "pending"
                assert permission.response_option_id is None
                assert permission.idempotency_key is None

        asyncio.run(_assert_state())

    def test_replays_rejected_invalid_option_as_conflict(
        self, session_factory, checkpointer
    ) -> None:
        """Idempotent retries of rejected responses must preserve the conflict."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-invalid-replay"
            self._seed_permission(
                session_factory, thread_id=thread_id, request_id=request_id
            )

            worker.dispatches.clear()
            headers = {"Idempotency-Key": "same-invalid-response"}
            first = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "hostile-option"},
                headers=headers,
            )
            second = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "hostile-option"},
                headers=headers,
            )

        assert first.status_code == 409
        assert second.status_code == 409
        assert second.json()["detail"] == "Unknown permission option for this request"
        assert worker.dispatches == []

    def test_replays_rejected_invalid_option_with_malformed_stored_payload(
        self, session_factory, checkpointer
    ) -> None:
        """Malformed stored rejection payloads must fall back to durable state."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_rejected_action() -> None:
            from ...database.models import ControlActionModel

            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow action?",
                    allowed_options=[
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
                    ],
                    tool_call="bash",
                )
                action = await create_control_action(
                    session,
                    thread_id=thread_id,
                    action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
                    request_id=request_id,
                    idempotency_key="same-invalid-response",
                    payload={"option_id": "hostile-option"},
                    result_status=ControlActionResultStatus.REJECTED_INVALID_STATE,
                )
                stored = await session.get(ControlActionModel, action.id)
                assert stored is not None
                stored.payload_json = '{"broken":'
                await session.commit()

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-invalid-replay-malformed-payload"
            asyncio.run(_seed_rejected_action())

            worker.dispatches.clear()
            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "hostile-option"},
                headers={"Idempotency-Key": "same-invalid-response"},
            )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Unknown permission option for this request"
        assert worker.dispatches == []

    def test_replays_rejected_invalid_option_after_valid_response(
        self, session_factory, checkpointer
    ) -> None:
        """Rejected idempotent replays must preserve the original conflict reason."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_permission() -> None:
            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow action?",
                    allowed_options=[
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
                    ],
                    tool_call="bash",
                )
                await session.commit()

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-invalid-then-valid"
            asyncio.run(_seed_permission())

            worker.dispatches.clear()
            invalid_headers = {"Idempotency-Key": "same-invalid-response"}
            invalid = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "hostile-option"},
                headers=invalid_headers,
            )
            valid = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )
            replayed_invalid = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "hostile-option"},
                headers=invalid_headers,
            )

        assert invalid.status_code == 409
        assert valid.status_code == 200
        assert replayed_invalid.status_code == 409
        assert (
            replayed_invalid.json()["detail"]
            == "Unknown permission option for this request"
        )
        assert len(worker.dispatches) == 1

    def test_rejects_stale_permission_request_when_newer_interrupt_exists(
        self, session_factory, checkpointer
    ) -> None:
        """Only the active pending interrupt for a thread may be resumed."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_permissions() -> None:
            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=old_request_id,
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow old action?",
                    allowed_options=[
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
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
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
                    ],
                    tool_call="bash",
                )
                await session.commit()

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            old_request_id = f"{thread_id}:req-old"
            new_request_id = f"{thread_id}:req-new"
            asyncio.run(_seed_permissions())

            worker.dispatches.clear()
            stale = client.post(
                f"/api/permissions/{old_request_id}/respond",
                json={"option_id": "allow_once"},
            )
            active = client.post(
                f"/api/permissions/{new_request_id}/respond",
                json={"option_id": "allow_once"},
            )

        assert stale.status_code == 409
        assert stale.json()["detail"] == "Permission request is no longer pending"
        assert active.status_code == 200
        assert len(worker.dispatches) == 1
        assert worker.dispatches[0]["option_id"] == "allow_once"

    def test_plan_approval_uses_live_pending_request_over_stale_thread_pointer(
        self, session_factory, checkpointer
    ) -> None:
        """Plan approval should not trust a stale thread approval_request_id."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_plan_approval() -> None:
            async with session_factory() as session:
                thread = await session.get(ThreadModel, thread_id)
                assert thread is not None
                thread.approval_status = "pending"
                thread.approval_request_id = stale_request_id
                await record_permission_request(
                    session,
                    request_id=live_request_id,
                    thread_id=thread_id,
                    pause_reason_type="plan_approval_request",
                    description="Approve plan?",
                    allowed_options=[
                        {
                            "option_id": "approve",
                            "name": "Approve",
                            "kind": "allow_once",
                        },
                        {
                            "option_id": "reject",
                            "name": "Reject",
                            "kind": "reject_once",
                        },
                    ],
                    tool_call="plan_approval",
                )
                await session.commit()

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "plan approval test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            stale_request_id = f"{thread_id}:req-stale-plan"
            live_request_id = f"{thread_id}:req-live-plan"
            asyncio.run(_seed_plan_approval())

            worker.dispatches.clear()
            live = client.post(
                f"/api/permissions/{live_request_id}/respond",
                json={"option_id": "approve"},
            )

        assert live.status_code == 200
        assert len(worker.dispatches) == 1
        assert worker.dispatches[0]["option_id"] == {"approved": True}


class TestDeleteThread:
    """Tests for DELETE /api/threads/{thread_id}."""

    def test_rejects_input_required_thread_with_pending_permission(
        self, session_factory, checkpointer
    ) -> None:
        """Hard delete must not destroy paused, resumable work."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_thread() -> None:
            await checkpointer.setup()
            from langgraph.checkpoint.base import empty_checkpoint

            checkpoint = empty_checkpoint()
            checkpoint["id"] = "cp-delete-input-required"
            await checkpointer.aput(
                {
                    "configurable": {
                        "thread_id": "thread-delete-input-required",
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
                    thread_id="thread-delete-input-required",
                    status="input_required",
                    repair_status="paused_resumable",
                    execution_readiness="paused_resumable",
                )
                await record_permission_request(
                    session,
                    request_id="perm-delete-input-required",
                    thread_id="thread-delete-input-required",
                    pause_reason_type="bash",
                    description="Allow resumable action?",
                    allowed_options=[{"option_id": "allow_once", "name": "Allow Once"}],
                    tool_call="bash",
                )
                await session.commit()

        asyncio.run(_seed_thread())

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.delete("/api/threads/thread-delete-input-required")

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Cannot delete thread in 'input_required' state"

    def test_plan_approval_response_succeeds_after_real_event_relay(
        self, session_factory, checkpointer
    ) -> None:
        """Supervisor plan approvals must be respondable after internal relay."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "plan approval relay test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-plan-relay"

            relay = client.post(
                "/internal/events",
                json={
                    "thread_id": thread_id,
                    "payload": {
                        "type": "plan_approval_request",
                        "request_id": request_id,
                        "description": "Approve plan for feature 'audit-5'",
                        "options": [
                            {
                                "option_id": "approve",
                                "name": "Approve plan",
                                "kind": "allow_once",
                            },
                            {
                                "option_id": "reject",
                                "name": "Reject plan",
                                "kind": "reject_once",
                            },
                        ],
                        "tool_call": "plan_approval",
                        "feature": "audit-5",
                        "plan_paths": [".vault/plan/audit-5.md"],
                        "exec_worker": "vaultspec-coder",
                    },
                },
            )
            assert relay.status_code == 200

            worker.dispatches.clear()
            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "approve"},
            )

        assert resp.status_code == 200
        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "resume"
        assert dispatch["thread_id"] == thread_id
        assert dispatch["option_id"] == {"approved": True}

    def test_rejects_stale_second_response_after_submission(
        self, session_factory, checkpointer
    ) -> None:
        """A second non-idempotent response must fail once the request is answered."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_permission() -> None:
            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow action?",
                    allowed_options=[
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        },
                        {
                            "option_id": "deny_once",
                            "name": "Deny once",
                            "kind": "deny_once",
                        },
                    ],
                    tool_call="bash",
                )
                await session.commit()

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-stale"
            asyncio.run(_seed_permission())

            worker.dispatches.clear()
            first = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )
            second = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "deny_once"},
                headers={"Idempotency-Key": "different-response"},
            )

        assert first.status_code == 200
        assert second.status_code == 409
        assert second.json()["detail"] == "Permission request is no longer pending"
        assert len(worker.dispatches) == 1
        assert worker.dispatches[0]["option_id"] == "allow_once"

    def test_failed_resume_dispatch_restores_permission_to_pending(
        self, session_factory, checkpointer
    ) -> None:
        """Failed resume dispatch must leave the durable permission re-actionable."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_permission() -> None:
            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow action?",
                    allowed_options=[
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
                    ],
                    tool_call="bash",
                )
                await session.commit()

        failing_client = httpx.AsyncClient(base_url="http://127.0.0.1:9")
        original_client = app.state.worker_client

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission dispatch failure"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-dispatch-fail"
            expected_idempotency_key = hashlib.sha256(
                f"{request_id}:allow_once".encode()
            ).hexdigest()
            asyncio.run(_seed_permission())

            worker.dispatches.clear()
            app.state.worker_client = failing_client
            first = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

            async def _assert_reset() -> None:
                from ...database.models import (
                    ControlActionModel,
                    PermissionRequestModel,
                    ThreadModel,
                )

                async with session_factory() as session:
                    permission = await session.get(PermissionRequestModel, request_id)
                    thread = await session.get(ThreadModel, thread_id)
                    assert permission is not None
                    assert thread is not None
                    assert thread.status == "input_required"
                    assert permission.request_status == "pending"
                    assert permission.response_option_id is None
                    assert permission.idempotency_key is None
                    action = (
                        await session.execute(
                            select(ControlActionModel).where(
                                ControlActionModel.request_id == request_id
                            )
                        )
                    ).scalar_one()
                    assert action.idempotency_key != expected_idempotency_key
                    assert ":dispatch-failed:" in action.idempotency_key

            asyncio.run(_assert_reset())

            app.state.worker_client = original_client
            second = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

        asyncio.run(failing_client.aclose())

        assert first.status_code == 502
        assert second.status_code == 200
        assert len(worker.dispatches) == 1
        assert worker.dispatches[0]["option_id"] == "allow_once"

    def test_rejects_permission_request_without_valid_durable_options(
        self, session_factory, checkpointer
    ) -> None:
        """A malformed durable permission row must fail closed."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_permission() -> None:
            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow action?",
                    allowed_options=[],
                    tool_call="bash",
                )
                await session.commit()

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-empty"
            asyncio.run(_seed_permission())

            worker.dispatches.clear()
            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Permission request has no valid options"
        assert worker.dispatches == []

    def test_rejects_permission_request_with_malformed_durable_option_json(
        self, session_factory, checkpointer
    ) -> None:
        """Corrupted durable option payloads must also fail closed."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async def _seed_permission() -> None:
            from ...database.models import PermissionRequestModel

            async with session_factory() as session:
                await record_permission_request(
                    session,
                    request_id=request_id,
                    thread_id=thread_id,
                    pause_reason_type="bash",
                    description="Allow action?",
                    allowed_options=[
                        {
                            "option_id": "allow_once",
                            "name": "Allow once",
                            "kind": "allow_once",
                        }
                    ],
                    tool_call="bash",
                )
                permission = await session.get(PermissionRequestModel, request_id)
                assert permission is not None
                permission.allowed_options_json = '{"broken":'
                await session.commit()

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "permission test"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]
            request_id = f"{thread_id}:req-malformed"
            asyncio.run(_seed_permission())

            worker.dispatches.clear()
            resp = client.post(
                f"/api/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Permission request has no valid options"
        assert worker.dispatches == []


# ---------------------------------------------------------------------------
# POST /threads -- autonomous mode
# ---------------------------------------------------------------------------


class TestCreateThreadAutonomous:
    """Tests for the autonomous field on POST /api/threads."""

    def test_create_thread_autonomous_defaults_false(
        self, session_factory, checkpointer
    ) -> None:
        """Creating a thread without autonomous field defaults to False (supervised)."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={"initial_message": "Hello, supervised mode"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        # No crash = autonomous=False default accepted correctly

    def test_create_thread_autonomous_true_accepted(
        self, session_factory, checkpointer
    ) -> None:
        """Creating a thread with autonomous=True returns 201 successfully."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)

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

    def test_create_thread_with_preset_autonomous_dispatches(
        self, session_factory, checkpointer
    ) -> None:
        """Creating a thread with a preset and autonomous=True dispatches to worker."""
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Run autonomously",
                    "team_preset": "vaultspec-structured-coder",
                    "autonomous": True,
                },
            )
        assert resp.status_code == 201

        # Verify dispatch was sent with autonomous flag
        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["action"] == "ingest"
        assert dispatch["team_preset"] == "vaultspec-structured-coder"
        assert dispatch["autonomous"] is True

    def test_create_thread_autonomous_inherits_team_auto_approve(
        self, session_factory, checkpointer
    ) -> None:
        """When autonomous is not set, team auto_approve=True
        makes dispatch autonomous.
        """
        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/threads",
                json={
                    "initial_message": "Run with team default",
                    "team_preset": "vaultspec-solo-coder",
                    # autonomous not set — should inherit auto_approve=True from preset
                },
            )
        assert resp.status_code == 201

        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["autonomous"] is True


# ---------------------------------------------------------------------------
# POST /threads/{thread_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelThread:
    """Tests for POST /api/threads/{thread_id}/cancel."""

    def test_failed_cancel_dispatch_restores_repair_state(
        self, session_factory, checkpointer
    ) -> None:
        """A failed cancel dispatch must not leave a ghost cancel_pending state."""
        app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
        failing_client = httpx.AsyncClient(base_url="http://127.0.0.1:9")
        original_client = app.state.worker_client

        with TestClient(app, raise_server_exceptions=True) as client:
            create_resp = client.post(
                "/api/threads",
                json={"initial_message": "cancel dispatch failure"},
            )
            assert create_resp.status_code == 201
            thread_id = create_resp.json()["thread_id"]

            async def _assert_initial() -> None:
                async with session_factory() as session:
                    thread = await session.get(ThreadModel, thread_id)
                    assert thread is not None
                    assert thread.last_requested_action == "ingest"

            asyncio.run(_assert_initial())

            app.state.worker_client = failing_client
            cancel_resp = client.post(f"/api/threads/{thread_id}/cancel")

            async def _assert_reset() -> None:
                async with session_factory() as session:
                    thread = await session.get(ThreadModel, thread_id)
                    assert thread is not None
                    assert thread.status == "submitted"
                    assert thread.repair_status == "healthy"
                    assert thread.execution_readiness == "healthy"
                    assert thread.repair_reason is None
                    assert thread.last_requested_action == "ingest"

            asyncio.run(_assert_reset())
            app.state.worker_client = original_client

        asyncio.run(failing_client.aclose())

        assert cancel_resp.status_code == 502
        assert cancel_resp.json()["detail"] == "Cancel dispatch failed"
