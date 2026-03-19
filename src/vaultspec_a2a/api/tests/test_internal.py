"""Tests for src/vaultspec_a2a/api/internal.py -- internal IPC router endpoints
(ADR-019).

Validates the /internal/health, /internal/events, and /internal/heartbeat
HTTP endpoints using a real FastAPI test client with httpx.ASGITransport.

Uses real ConnectionManager + EventAggregator (no fakes or mocks).
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from ...core.aggregator import EventAggregator
from ...database.crud import create_thread, get_thread_execution_state
from ..internal import internal_router
from ..websocket import ConnectionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_app(
    *,
    with_connection_manager: bool = False,
    session_factory=None,
) -> FastAPI:
    """Create a minimal FastAPI app with the internal router and wired state.

    When ``with_connection_manager`` is True, a real ``ConnectionManager``
    backed by a real ``EventAggregator`` is attached (no fakes).
    """
    app = FastAPI()
    app.include_router(internal_router)

    # Pre-populate app.state with the attributes the endpoints expect
    app.state.worker_last_heartbeat_ts = 0.0
    app.state.worker_active_threads = []
    if session_factory is not None:
        app.state.db_session_factory = session_factory

    if with_connection_manager:
        aggregator = EventAggregator()
        cm = ConnectionManager(aggregator)
        app.state.connection_manager = cm
    else:
        app.state.connection_manager = None

    return app


# ---------------------------------------------------------------------------
# /internal/health
# ---------------------------------------------------------------------------


class TestInternalHealth:
    """Verify the /internal/health readiness probe."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_200(self) -> None:
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/internal/health")
            assert resp.status_code == 200

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_correct_body(self) -> None:
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/internal/health")
            data = resp.json()
            assert data["status"] == "ok"
            assert data["service"] == "gateway"


# ---------------------------------------------------------------------------
# /internal/heartbeat
# ---------------------------------------------------------------------------


class TestInternalHeartbeat:
    """Verify the /internal/heartbeat endpoint updates app.state."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_returns_200(self) -> None:
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/heartbeat",
                json={
                    "type": "heartbeat",
                    "worker_id": "w1",
                    "active_threads": ["t-1"],
                    "timestamp": "2026-03-01T12:00:00Z",
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_updates_app_state_timestamp(self) -> None:
        app = _make_test_app()
        before_ts = app.state.worker_last_heartbeat_ts
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/internal/heartbeat",
                json={
                    "type": "heartbeat",
                    "worker_id": "w1",
                    "active_threads": [],
                    "timestamp": "2026-03-01T12:00:00Z",
                },
            )
        # The heartbeat should have updated the timestamp
        assert app.state.worker_last_heartbeat_ts > before_ts

    @pytest.mark.asyncio(loop_scope="function")
    async def test_updates_app_state_active_threads(self) -> None:
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/internal/heartbeat",
                json={
                    "type": "heartbeat",
                    "worker_id": "w1",
                    "active_threads": ["t-aaa", "t-bbb"],
                    "timestamp": "2026-03-01T12:00:00Z",
                },
            )
        assert app.state.worker_active_threads == ["t-aaa", "t-bbb"]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_replaces_old_active_threads(self) -> None:
        """A new heartbeat fully replaces the previous active_threads list."""
        app = _make_test_app()
        app.state.worker_active_threads = ["old-thread"]
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/internal/heartbeat",
                json={
                    "type": "heartbeat",
                    "worker_id": "w1",
                    "active_threads": [],
                    "timestamp": "2026-03-01T12:00:00Z",
                },
            )
        assert app.state.worker_active_threads == []

    @pytest.mark.asyncio(loop_scope="function")
    async def test_heartbeat_log_includes_runtime_fields(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """HTTP heartbeat logs should carry active-thread count and transport."""
        app = _make_test_app()
        with caplog.at_level(logging.DEBUG, logger="vaultspec_a2a.api.internal"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/internal/heartbeat",
                    json={
                        "type": "heartbeat",
                        "worker_id": "w1",
                        "active_threads": ["t-aaa", "t-bbb"],
                        "timestamp": "2026-03-01T12:00:00Z",
                    },
                )

        assert resp.status_code == 200
        record = next(
            rec for rec in caplog.records if "Worker heartbeat (HTTP)" in rec.message
        )
        assert record.__dict__["message_type"] == "heartbeat"
        assert record.__dict__["active_thread_count"] == 2
        assert record.__dict__["transport"] == "http"


# ---------------------------------------------------------------------------
# /internal/events
# ---------------------------------------------------------------------------


class TestInternalEvents:
    """Verify the /internal/events endpoint.

    When no connection_manager is present, the endpoint returns 503 so the
    worker can detect the unready gateway and retry or backoff.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_valid_event_returns_ok(self) -> None:
        app = _make_test_app(with_connection_manager=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-42",
                    "payload": {"event_type": "chunk", "data": "hello"},
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_event_without_connection_manager_returns_503(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When connection_manager is None, /internal/events returns 503."""
        app = _make_test_app()
        assert app.state.connection_manager is None
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-42",
                    "payload": {"event_type": "chunk", "data": "hello"},
                },
            )
            assert resp.status_code == 503

    @pytest.mark.asyncio(loop_scope="function")
    async def test_event_with_real_connection_manager_calls_broadcast(self) -> None:
        """When a real ConnectionManager is present, broadcast_to_thread runs.

        Since no WebSocket clients are connected, the broadcast is a no-op
        in terms of external effects, but the code path executes fully.
        We verify that the endpoint completes successfully with a real CM.
        """
        app = _make_test_app(with_connection_manager=True)
        _cm: ConnectionManager = app.state.connection_manager

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-42",
                    "payload": {"event_type": "chunk", "data": "hello"},
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_missing_thread_id_is_malformed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed event without thread_id is rejected."""
        app = _make_test_app(with_connection_manager=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "payload": {"data": "hello"},
                },
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio(loop_scope="function")
    async def test_execution_state_projection_persists_without_broadcasting(
        self,
        session_factory,
    ) -> None:
        """Execution-state projection events should persist via the internal path."""
        app = _make_test_app(
            with_connection_manager=True,
            session_factory=session_factory,
        )

        async with session_factory() as session:
            await create_thread(session, thread_id="t-84")
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-84",
                    "payload": {
                        "type": "execution_state_projection",
                        "checkpoint_id": "cp-1",
                        "parent_checkpoint_id": "cp-0",
                        "snapshot_created_at": "2026-03-10T12:00:00+00:00",
                        "next_nodes": ["supervisor"],
                        "interrupt_types": ["permission_request"],
                        "interrupt_count": 1,
                        "task_count": 1,
                        "tasks": [
                            {
                                "task_id": "task-1",
                                "name": "supervisor",
                                "path": ["supervisor"],
                                "has_error": False,
                                "error_type": None,
                                "interrupt_ids": ["interrupt-1"],
                                "interrupt_types": ["permission_request"],
                                "has_nested_state": False,
                                "has_result": False,
                            }
                        ],
                        "degraded_reasons": [],
                    },
                },
            )

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        async with session_factory() as session:
            projection = await get_thread_execution_state(session, "t-84")

        assert projection is not None
        assert projection.checkpoint_id == "cp-1"
        assert projection.parent_checkpoint_id == "cp-0"
        assert projection.task_count == 1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_degraded_execution_state_projection_preserves_last_good_state(
        self,
        session_factory,
    ) -> None:
        """A degraded-only update must not erase the last good execution-state row."""
        app = _make_test_app(
            with_connection_manager=True,
            session_factory=session_factory,
        )

        async with session_factory() as session:
            await create_thread(session, thread_id="t-84-degraded")
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            good = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-84-degraded",
                    "payload": {
                        "type": "execution_state_projection",
                        "checkpoint_id": "cp-good",
                        "parent_checkpoint_id": "cp-parent",
                        "snapshot_created_at": "2026-03-10T12:00:00+00:00",
                        "next_nodes": ["supervisor"],
                        "interrupt_types": ["permission_request"],
                        "interrupt_count": 1,
                        "task_count": 1,
                        "tasks": [
                            {
                                "task_id": "task-1",
                                "name": "supervisor",
                                "path": ["supervisor"],
                                "has_error": False,
                                "error_type": None,
                                "interrupt_ids": ["interrupt-1"],
                                "interrupt_types": ["permission_request"],
                                "has_nested_state": False,
                                "has_result": False,
                            }
                        ],
                        "degraded_reasons": [],
                    },
                },
            )
            degraded = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-84-degraded",
                    "payload": {
                        "type": "execution_state_projection",
                        "degraded_reasons": ["execution_state_projection_unavailable"],
                    },
                },
            )

        assert good.status_code == 200
        assert degraded.status_code == 200

        async with session_factory() as session:
            projection = await get_thread_execution_state(session, "t-84-degraded")

        assert projection is not None
        assert projection.checkpoint_id == "cp-good"
        assert projection.parent_checkpoint_id == "cp-parent"
        assert projection.task_count == 1
        assert projection.degraded_reasons_json == (
            '["execution_state_projection_unavailable"]'
        )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_missing_payload_is_malformed(self) -> None:
        """A malformed event without payload is rejected."""
        app = _make_test_app(with_connection_manager=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-42",
                },
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_thread_id_is_treated_as_malformed(self) -> None:
        """An empty string thread_id is treated as missing (falsy)."""
        app = _make_test_app(with_connection_manager=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "",
                    "payload": {"data": "hello"},
                },
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_payload_is_treated_as_malformed(self) -> None:
        """An empty dict payload is treated as missing (falsy)."""
        app = _make_test_app(with_connection_manager=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-42",
                    "payload": {},
                },
            )
            assert resp.status_code == 422

    @pytest.mark.asyncio(loop_scope="function")
    async def test_batch_with_malformed_event_is_rejected(self) -> None:
        """Malformed entries in /internal/events/batch fail the whole batch."""
        app = _make_test_app(with_connection_manager=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events/batch",
                json={
                    "events": [
                        {"thread_id": "t-1", "payload": {"event_type": "chunk"}},
                        {"thread_id": "", "payload": {"event_type": "chunk"}},
                    ]
                },
            )
            assert resp.status_code == 422


class TestInternalWebSocketLogging:
    """Verify structured logging on the internal worker WebSocket path."""

    def test_malformed_event_log_includes_runtime_fields(self, caplog) -> None:
        """Malformed event envelopes should log bounded WS metadata."""
        app = _make_test_app()

        with (
            caplog.at_level(logging.WARNING, logger="vaultspec_a2a.api.internal"),
            TestClient(app) as client,
            client.websocket_connect("/internal/ws") as ws,
        ):
            ws.send_json({"type": "event", "thread_id": "", "payload": {}})

        record = next(
            rec
            for rec in caplog.records
            if "Malformed worker event envelope" in rec.message
        )
        assert record.__dict__["thread_id"] == ""
        assert record.__dict__["event_type"] == ""
        assert record.__dict__["message_type"] == "event"
        assert record.__dict__["transport"] == "ws"
        assert record.__dict__["frame_size"] > 0

    def test_missing_connection_manager_log_includes_runtime_fields(
        self, caplog
    ) -> None:
        """Dropped relay events should log thread and event correlation fields."""
        app = _make_test_app()

        with (
            caplog.at_level(logging.WARNING, logger="vaultspec_a2a.api.internal"),
            TestClient(app) as client,
            client.websocket_connect("/internal/ws") as ws,
        ):
            ws.send_json(
                {
                    "type": "event",
                    "thread_id": "t-drop",
                    "payload": {"event_type": "chunk", "data": "hello"},
                }
            )

        record = next(
            rec
            for rec in caplog.records
            if "ConnectionManager not available -- dropping event" in rec.message
        )
        assert record.__dict__["thread_id"] == "t-drop"
        assert record.__dict__["event_type"] == "chunk"
        assert record.__dict__["transport"] == "ws"
        assert record.__dict__["action"] == "relay_drop_event"

    def test_ws_heartbeat_log_includes_runtime_fields(self, caplog) -> None:
        """Internal WS heartbeat logs should carry count and transport metadata."""
        app = _make_test_app()

        with (
            caplog.at_level(logging.DEBUG, logger="vaultspec_a2a.api.internal"),
            TestClient(app) as client,
            client.websocket_connect("/internal/ws") as ws,
        ):
            ws.send_json(
                {
                    "type": "heartbeat",
                    "active_threads": ["t-1", "t-2"],
                }
            )

        record = next(
            rec for rec in caplog.records if "Worker heartbeat:" in rec.message
        )
        assert record.__dict__["message_type"] == "heartbeat"
        assert record.__dict__["active_thread_count"] == 2
        assert record.__dict__["transport"] == "ws"

    def test_unknown_ws_message_log_includes_runtime_fields(self, caplog) -> None:
        """Unknown WS message types should log bounded frame metadata."""
        app = _make_test_app()

        with (
            caplog.at_level(logging.WARNING, logger="vaultspec_a2a.api.internal"),
            TestClient(app) as client,
            client.websocket_connect("/internal/ws") as ws,
        ):
            ws.send_json({"type": "mystery", "payload": {"ignored": True}})

        record = next(
            rec
            for rec in caplog.records
            if "Unknown internal WS message type" in rec.message
        )
        assert record.__dict__["message_type"] == "mystery"
        assert record.__dict__["transport"] == "ws"
        assert record.__dict__["frame_size"] > 0


# ---------------------------------------------------------------------------
# WorkerBridge IPC reliability (TESTING-03)
# ---------------------------------------------------------------------------


class TestWorkerBridgeRetry:
    """WorkerBridge retries batch flush on gateway failures (IPC-03)."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_flush_retries_on_http_500_then_succeeds(self) -> None:
        """flush_events retries on 500; succeeds when the gateway recovers."""
        import httpx as _httpx
        from fastapi import FastAPI as _FastAPI
        from fastapi.responses import JSONResponse as _JSONResponse
        from httpx import ASGITransport as _ASGITransport

        from ...worker.ipc import WorkerBridge

        fail_count = 0
        retry_app = _FastAPI()

        @retry_app.post("/internal/events/batch")
        async def batch_endpoint():
            nonlocal fail_count
            if fail_count < 2:
                fail_count += 1
                return _JSONResponse({"error": "temporary"}, status_code=500)
            return _JSONResponse({"status": "ok"})

        bridge = WorkerBridge(api_url="http://test", worker_id="w-retry")
        bridge._client = _httpx.AsyncClient(
            transport=_ASGITransport(app=retry_app),
            base_url="http://test",
        )
        try:
            await bridge.send_event("t-1", {"event_type": "chunk"})
            if bridge._flush_task and not bridge._flush_task.done():
                bridge._flush_task.cancel()
            await bridge.flush_events()
        finally:
            await bridge._client.aclose()

        # Successful flush clears the buffer
        assert bridge._event_buffer == []

    @pytest.mark.asyncio(loop_scope="function")
    async def test_buffer_cap_drops_oldest_event(self) -> None:
        """send_event drops the oldest entry when buffer reaches _MAX_EVENT_BUFFER."""
        import httpx as _httpx
        from fastapi import FastAPI as _FastAPI
        from fastapi.responses import JSONResponse as _JSONResponse
        from httpx import ASGITransport as _ASGITransport

        from ...core.config import settings
        from ...worker.ipc import WorkerBridge

        noop_app = _FastAPI()

        @noop_app.post("/internal/events/batch")
        async def noop_batch():
            return _JSONResponse({"status": "ok"})

        bridge = WorkerBridge(api_url="http://test", worker_id="w-cap")
        bridge._client = _httpx.AsyncClient(
            transport=_ASGITransport(app=noop_app),
            base_url="http://test",
        )
        try:
            for i in range(settings.ipc_max_event_buffer + 1):
                await bridge.send_event("t-cap", {"event_type": "chunk", "seq": i})
                if bridge._flush_task and not bridge._flush_task.done():
                    bridge._flush_task.cancel()
        finally:
            await bridge._client.aclose()

        assert len(bridge._event_buffer) <= settings.ipc_max_event_buffer


class TestAggregatorGCOnTerminal:
    """Aggregator sequence counters are pruned on thread_terminal events (AGG-01/05)."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_terminal_event_prunes_thread_from_aggregator_sequences(
        self,
        session_factory,
    ) -> None:
        """_handle_terminal_event removes the terminated thread from
        aggregator _sequences.
        """
        from ..internal import _handle_terminal_event

        aggregator = EventAggregator()
        aggregator._sequences["t-pruned"] = 5
        aggregator._sequences["t-active"] = 3
        async with session_factory() as session:
            await create_thread(session, thread_id="t-pruned")
            await session.commit()

        await _handle_terminal_event(
            "t-pruned",
            {"event_type": "thread_terminal", "status": "completed"},
            aggregator=aggregator,
            session_factory=session_factory,
        )

        assert "t-pruned" not in aggregator._sequences
        assert "t-active" in aggregator._sequences

    @pytest.mark.asyncio(loop_scope="function")
    async def test_terminal_event_log_includes_runtime_fields(
        self,
        session_factory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Terminal update logs should carry thread/status/event metadata."""
        from ...database.crud import ThreadStatus, update_thread_status
        from ..internal import _handle_terminal_event

        aggregator = EventAggregator()
        async with session_factory() as session:
            thread = await create_thread(session, thread_id="t-logged")
            await update_thread_status(session, thread.id, ThreadStatus.RUNNING)
            await session.commit()

        with caplog.at_level(logging.INFO, logger="vaultspec_a2a.api.internal"):
            await _handle_terminal_event(
                "t-logged",
                {"event_type": "thread_terminal", "status": "completed"},
                aggregator=aggregator,
                session_factory=session_factory,
            )

        record = next(
            rec for rec in caplog.records if "status updated to" in rec.message
        )
        assert record.__dict__["thread_id"] == "t-logged"
        assert record.__dict__["status"] == "completed"
        assert record.__dict__["event_type"] == "thread_terminal"
        assert record.__dict__["action"] == "thread_terminal_status_updated"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_terminal_transition_skip_log_includes_runtime_fields(
        self,
        session_factory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Repeated terminal updates should log a structured skip record."""
        from ..internal import _handle_terminal_event

        aggregator = EventAggregator()
        async with session_factory() as session:
            await create_thread(session, thread_id="t-terminal-skip")
            await session.commit()

        await _handle_terminal_event(
            "t-terminal-skip",
            {"event_type": "thread_terminal", "status": "completed"},
            aggregator=aggregator,
            session_factory=session_factory,
        )

        with caplog.at_level(logging.INFO, logger="vaultspec_a2a.api.internal"):
            await _handle_terminal_event(
                "t-terminal-skip",
                {"event_type": "thread_terminal", "status": "completed"},
                aggregator=aggregator,
                session_factory=session_factory,
            )

        record = next(rec for rec in caplog.records if "transition to" in rec.message)
        assert record.__dict__["thread_id"] == "t-terminal-skip"
        assert record.__dict__["status"] == "completed"
        assert record.__dict__["event_type"] == "thread_terminal"
        assert record.__dict__["action"] == "thread_terminal_status_skipped"
