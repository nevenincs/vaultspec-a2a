"""Tests for src/vaultspec_a2a/worker/ipc.py -- WorkerBridge IPC layer (ADR-019).

Validates thread tracking, event relay, heartbeat sending, and the
resilient error-swallowing behaviour of the bridge.

Uses a real FastAPI ASGI app served via ``httpx.ASGITransport`` so real
HTTP serialisation and routing are exercised.  No MockTransport, no mock
libraries.  Connection-error swallowing is tested by pointing the bridge
at an address that refuses connections (localhost:1).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport

from ..ipc import WorkerBridge

# ---------------------------------------------------------------------------
# In-process gateway — real ASGI, no mock transport
# ---------------------------------------------------------------------------


class _InProcessGateway:
    """Minimal real FastAPI ASGI gateway that accepts IPC requests.

    Records all batches and heartbeats received.  The ``batch_status``
    parameter controls the HTTP status returned by the batch endpoint,
    allowing error-path tests to exercise non-200 responses.
    """

    def __init__(self, *, batch_status: int = 200) -> None:
        self.batches: list[dict] = []
        self.heartbeats: list[dict] = []
        self.paths: list[str] = []

        _app = FastAPI()
        _self = self
        _batch_status = batch_status

        @_app.post("/internal/events/batch")
        async def _batch(request: Request) -> Response:
            _self.paths.append(request.url.path)
            if _batch_status != 200:
                return Response(status_code=_batch_status)
            body = await request.json()
            _self.batches.append(body)
            return Response(content='{"status":"ok"}', media_type="application/json")

        @_app.post("/internal/heartbeat")
        async def _heartbeat(request: Request) -> Response:
            _self.paths.append(request.url.path)
            body = await request.json()
            _self.heartbeats.append(body)
            return Response(content='{"status":"ok"}', media_type="application/json")

        self._transport = ASGITransport(app=_app)

    def make_bridge(self, *, worker_id: str = "test-worker-001") -> WorkerBridge:
        """Return a WorkerBridge backed by this in-process gateway."""
        bridge = WorkerBridge(api_url="http://control:8000", worker_id=worker_id)
        bridge._client = httpx.AsyncClient(
            transport=self._transport,
            base_url="http://control:8000",
        )
        return bridge


def _make_unreachable_bridge(*, worker_id: str = "test-worker-001") -> WorkerBridge:
    """Return a WorkerBridge pointed at a port that refuses connections.

    Port 1 (tcpmux) is reserved and never in use — the OS returns an
    immediate connection-refused error, exercising the error-swallowing
    paths without needing a mock transport.
    """
    bridge = WorkerBridge(api_url="http://localhost:1", worker_id=worker_id)
    bridge._client = httpx.AsyncClient(
        base_url="http://localhost:1",
        timeout=httpx.Timeout(2.0),
    )
    return bridge


# ---------------------------------------------------------------------------
# Thread tracking
# ---------------------------------------------------------------------------


class TestThreadTracking:
    """Verify add/remove/snapshot behaviour of the active-thread set."""

    def test_active_threads_starts_empty(self) -> None:
        bridge = WorkerBridge(api_url="http://localhost:8000", worker_id="w1")
        assert bridge.active_threads == frozenset()

    def test_track_adds_thread(self) -> None:
        bridge = WorkerBridge(api_url="http://localhost:8000", worker_id="w1")
        bridge.track_thread("t-aaa")
        assert "t-aaa" in bridge.active_threads

    def test_track_multiple_threads(self) -> None:
        bridge = WorkerBridge(api_url="http://localhost:8000", worker_id="w1")
        bridge.track_thread("t-aaa")
        bridge.track_thread("t-bbb")
        assert bridge.active_threads == frozenset({"t-aaa", "t-bbb"})

    def test_track_same_thread_twice_is_idempotent(self) -> None:
        bridge = WorkerBridge(api_url="http://localhost:8000", worker_id="w1")
        bridge.track_thread("t-aaa")
        bridge.track_thread("t-aaa")
        assert bridge.active_threads == frozenset({"t-aaa"})

    def test_untrack_removes_thread(self) -> None:
        bridge = WorkerBridge(api_url="http://localhost:8000", worker_id="w1")
        bridge.track_thread("t-aaa")
        bridge.track_thread("t-bbb")
        bridge.untrack_thread("t-aaa")
        assert bridge.active_threads == frozenset({"t-bbb"})

    def test_untrack_nonexistent_is_safe(self) -> None:
        bridge = WorkerBridge(api_url="http://localhost:8000", worker_id="w1")
        # discard on an empty set should not raise
        bridge.untrack_thread("does-not-exist")
        assert bridge.active_threads == frozenset()

    def test_active_threads_returns_frozen_snapshot(self) -> None:
        bridge = WorkerBridge(api_url="http://localhost:8000", worker_id="w1")
        bridge.track_thread("t-aaa")
        snapshot = bridge.active_threads
        # Mutating the bridge does not affect the snapshot
        bridge.track_thread("t-bbb")
        assert "t-bbb" not in snapshot


# ---------------------------------------------------------------------------
# send_event
# ---------------------------------------------------------------------------


class TestSendEvent:
    """Verify that send_event buffers and flush_events POSTs the batch."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sends_correct_json_via_batch(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        try:
            await bridge.send_event("thread-42", {"key": "value"})
            # Explicit flush to avoid waiting for deferred flush task
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert len(gw.batches) == 1
        body = gw.batches[0]
        assert "events" in body
        assert len(body["events"]) == 1
        evt = body["events"][0]
        assert evt["thread_id"] == "thread-42"
        assert evt["payload"] == {"key": "value"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_batches_multiple_events(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        try:
            await bridge.send_event("t1", {"a": 1})
            await bridge.send_event("t2", {"b": 2})
            await bridge.send_event("t1", {"c": 3})
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert len(gw.batches) == 1
        events = gw.batches[0]["events"]
        assert len(events) == 3
        assert events[0]["thread_id"] == "t1"
        assert events[1]["thread_id"] == "t2"
        assert events[2]["thread_id"] == "t1"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_posts_to_batch_events_path(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        try:
            await bridge.send_event("t1", {"a": 1})
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert "/internal/events/batch" in gw.paths

    @pytest.mark.asyncio(loop_scope="function")
    async def test_json_encodes_datetime_payloads(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        timestamp = datetime(2026, 3, 9, 12, 30, tzinfo=UTC)
        try:
            await bridge.send_event("t-json", {"timestamp": timestamp})
            await bridge.flush_events()
        finally:
            await bridge.close()

        payload = gw.batches[0]["events"][0]["payload"]
        assert payload["timestamp"] == "2026-03-09T12:30:00+00:00"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_200_response_logs_warning_but_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        gw = _InProcessGateway(batch_status=503)
        bridge = gw.make_bridge()
        try:
            with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.worker.ipc"):
                await bridge.send_event("thread-fail", {"x": 1})
                await bridge.flush_events()

            assert any(
                "Batch event relay failed" in rec.message for rec in caplog.records
            )
            record = next(
                rec
                for rec in caplog.records
                if "Batch event relay failed" in rec.message
            )
            assert record.__dict__["worker_id"] == "test-worker-001"
            assert record.__dict__["action"] == "flush_events"
            assert record.__dict__["batch_size"] == 1
            assert record.__dict__["flush_attempt"] == 1
            assert record.__dict__["flush_attempt_limit"] >= 1
            assert record.__dict__["http_status_code"] == 503
        finally:
            await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_http_error_is_swallowed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        bridge = _make_unreachable_bridge()
        try:
            with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.worker.ipc"):
                await bridge.send_event("t-err", {"data": True})
                await bridge.flush_events()

            assert any("Failed to send" in rec.message for rec in caplog.records)
            record = next(
                rec for rec in caplog.records if "Failed to send" in rec.message
            )
            assert record.__dict__["worker_id"] == "test-worker-001"
            assert record.__dict__["action"] == "flush_events"
            assert record.__dict__["batch_size"] == 1
            assert record.__dict__["flush_attempt"] == 1
        finally:
            await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_flushes_pending_events(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        await bridge.send_event("t1", {"flush": "on_close"})
        await bridge.close()

        assert len(gw.batches) == 1
        assert gw.batches[0]["events"][0]["thread_id"] == "t1"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_flush_empty_buffer_is_noop(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        try:
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert len(gw.batches) == 0


# ---------------------------------------------------------------------------
# send_heartbeat
# ---------------------------------------------------------------------------


class TestSendHeartbeat:
    """Verify that send_heartbeat POSTs the correct JSON to /internal/heartbeat."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sends_correct_json(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge(worker_id="worker-xyz")
        bridge.track_thread("t-1")
        bridge.track_thread("t-2")
        try:
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

        assert len(gw.heartbeats) == 1
        body = gw.heartbeats[0]
        assert body["type"] == "heartbeat"
        assert body["worker_id"] == "worker-xyz"
        # active_threads must be sorted
        assert body["active_threads"] == ["t-1", "t-2"]
        # uptime_seconds must be a non-negative integer (WPA-004)
        assert isinstance(body["uptime_seconds"], int)
        assert body["uptime_seconds"] >= 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_posts_to_internal_heartbeat_path(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        try:
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

        assert "/internal/heartbeat" in gw.paths

    @pytest.mark.asyncio(loop_scope="function")
    async def test_http_error_is_swallowed(self) -> None:
        bridge = _make_unreachable_bridge()
        try:
            # Must not raise
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_active_threads(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        try:
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

        assert gw.heartbeats[0]["active_threads"] == []


# ---------------------------------------------------------------------------
# heartbeat_loop
# ---------------------------------------------------------------------------


class TestHeartbeatLoop:
    """Verify the periodic heartbeat loop."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_loop_sends_multiple_heartbeats(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        try:
            # Run the loop for a short window with a tiny interval
            async def run_loop() -> None:
                await bridge.heartbeat_loop(interval=0.05)

            task = asyncio.create_task(run_loop())
            await asyncio.sleep(0.2)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            # Should have fired at least 2 heartbeats in 0.2s with 0.05s interval
            assert len(gw.heartbeats) >= 2
        finally:
            await bridge.close()


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    """Verify that close() shuts down the underlying client."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_shuts_down_client(self) -> None:
        gw = _InProcessGateway()
        bridge = gw.make_bridge()
        await bridge.close()

        # After close, the client should be closed
        assert bridge._client.is_closed


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    """Verify constructor normalises the API URL."""

    def test_strips_trailing_slash(self) -> None:
        bridge = WorkerBridge(api_url="http://host:8000/", worker_id="w")
        assert bridge._api_url == "http://host:8000"

    def test_preserves_url_without_trailing_slash(self) -> None:
        bridge = WorkerBridge(api_url="http://host:8000", worker_id="w")
        assert bridge._api_url == "http://host:8000"
