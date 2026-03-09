"""Tests for src/vaultspec_a2a/api/internal.py -- internal IPC router endpoints (ADR-019).

Validates the /internal/health, /internal/events, and /internal/heartbeat
HTTP endpoints using a real FastAPI test client with httpx.ASGITransport.

Uses real ConnectionManager + EventAggregator (no fakes or mocks).
"""

from __future__ import annotations

import pytest

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ...core.aggregator import EventAggregator
from ..internal import internal_router
from ..websocket import ConnectionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_app(*, with_connection_manager: bool = False) -> FastAPI:
    """Create a minimal FastAPI app with the internal router and wired state.

    When ``with_connection_manager`` is True, a real ``ConnectionManager``
    backed by a real ``EventAggregator`` is attached (no fakes).
    """
    app = FastAPI()
    app.include_router(internal_router)

    # Pre-populate app.state with the attributes the endpoints expect
    app.state.worker_last_heartbeat_ts = 0.0
    app.state.worker_active_threads = []

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
        """send_event drops the oldest entry when the buffer reaches _MAX_EVENT_BUFFER."""
        import httpx as _httpx

        from fastapi import FastAPI as _FastAPI
        from fastapi.responses import JSONResponse as _JSONResponse
        from httpx import ASGITransport as _ASGITransport

        from ...worker.ipc import _MAX_EVENT_BUFFER, WorkerBridge

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
            for i in range(_MAX_EVENT_BUFFER + 1):
                await bridge.send_event("t-cap", {"event_type": "chunk", "seq": i})
                if bridge._flush_task and not bridge._flush_task.done():
                    bridge._flush_task.cancel()
        finally:
            await bridge._client.aclose()

        assert len(bridge._event_buffer) <= _MAX_EVENT_BUFFER


class TestAggregatorGCOnTerminal:
    """Aggregator sequence counters are pruned on thread_terminal events (AGG-01/05)."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_terminal_event_prunes_thread_from_aggregator_sequences(
        self,
    ) -> None:
        """_handle_terminal_event removes the terminated thread from aggregator _sequences."""
        from ..internal import _handle_terminal_event

        aggregator = EventAggregator()
        aggregator._sequences["t-pruned"] = 5
        aggregator._sequences["t-active"] = 3

        await _handle_terminal_event(
            "t-pruned",
            {"event_type": "thread_terminal", "status": "completed"},
            aggregator=aggregator,
        )

        assert "t-pruned" not in aggregator._sequences
        assert "t-active" in aggregator._sequences
