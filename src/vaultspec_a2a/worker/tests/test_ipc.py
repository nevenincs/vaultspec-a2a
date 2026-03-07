"""Tests for src/vaultspec_a2a/worker/ipc.py -- WorkerBridge IPC layer (ADR-019).

Validates thread tracking, event relay, heartbeat sending, and the
resilient error-swallowing behaviour of the bridge.

Uses ``httpx.MockTransport`` (httpx's built-in test transport) to
intercept HTTP calls without any mock libraries.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from ..ipc import WorkerBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge_with_transport(
    handler,
    *,
    api_url: str = "http://control:8000",
    worker_id: str = "test-worker-001",
) -> WorkerBridge:
    """Create a WorkerBridge and replace its internal client with a mock transport."""
    bridge = WorkerBridge(api_url=api_url, worker_id=worker_id)
    # Replace the real client with one backed by the test transport.
    bridge._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=bridge._api_url,
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
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        try:
            await bridge.send_event("thread-42", {"key": "value"})
            # Explicit flush to avoid waiting for deferred flush task
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert len(captured) == 1
        body = captured[0]
        assert "events" in body
        assert len(body["events"]) == 1
        evt = body["events"][0]
        assert evt["thread_id"] == "thread-42"
        assert evt["payload"] == {"key": "value"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_batches_multiple_events(self) -> None:
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        try:
            await bridge.send_event("t1", {"a": 1})
            await bridge.send_event("t2", {"b": 2})
            await bridge.send_event("t1", {"c": 3})
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert len(captured) == 1
        events = captured[0]["events"]
        assert len(events) == 3
        assert events[0]["thread_id"] == "t1"
        assert events[1]["thread_id"] == "t2"
        assert events[2]["thread_id"] == "t1"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_posts_to_batch_events_path(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        try:
            await bridge.send_event("t1", {"a": 1})
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert "/internal/events/batch" in paths

    @pytest.mark.asyncio(loop_scope="function")
    async def test_non_200_response_logs_warning_but_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Service Unavailable")

        bridge = _make_bridge_with_transport(handler)
        try:
            with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.worker.ipc"):
                await bridge.send_event("thread-fail", {"x": 1})
                await bridge.flush_events()

            assert any(
                "Batch event relay failed" in rec.message for rec in caplog.records
            )
        finally:
            await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_http_error_is_swallowed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        bridge = _make_bridge_with_transport(handler)
        try:
            with caplog.at_level(logging.WARNING, logger="vaultspec_a2a.worker.ipc"):
                await bridge.send_event("t-err", {"data": True})
                await bridge.flush_events()

            assert any("Failed to send" in rec.message for rec in caplog.records)
        finally:
            await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_flushes_pending_events(self) -> None:
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        await bridge.send_event("t1", {"flush": "on_close"})
        await bridge.close()

        assert len(captured) == 1
        assert captured[0]["events"][0]["thread_id"] == "t1"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_flush_empty_buffer_is_noop(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        try:
            await bridge.flush_events()
        finally:
            await bridge.close()

        assert call_count == 0


# ---------------------------------------------------------------------------
# send_heartbeat
# ---------------------------------------------------------------------------


class TestSendHeartbeat:
    """Verify that send_heartbeat POSTs the correct JSON to /internal/heartbeat."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_sends_correct_json(self) -> None:
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler, worker_id="worker-xyz")
        bridge.track_thread("t-1")
        bridge.track_thread("t-2")
        try:
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

        assert len(captured) == 1
        body = captured[0]
        assert body["type"] == "heartbeat"
        assert body["worker_id"] == "worker-xyz"
        # active_threads must be sorted
        assert body["active_threads"] == ["t-1", "t-2"]
        # uptime_seconds must be a non-negative integer (WPA-004)
        assert isinstance(body["uptime_seconds"], int)
        assert body["uptime_seconds"] >= 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_posts_to_internal_heartbeat_path(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        try:
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

        assert paths == ["/internal/heartbeat"]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_http_error_is_swallowed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        bridge = _make_bridge_with_transport(handler)
        try:
            # Must not raise
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_empty_active_threads(self) -> None:
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        try:
            await bridge.send_heartbeat()
        finally:
            await bridge.close()

        assert captured[0]["active_threads"] == []


# ---------------------------------------------------------------------------
# heartbeat_loop
# ---------------------------------------------------------------------------


class TestHeartbeatLoop:
    """Verify the periodic heartbeat loop."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_loop_sends_multiple_heartbeats(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
        try:
            # Run the loop for a short window with a tiny interval
            async def run_loop() -> None:
                await bridge.heartbeat_loop(interval=0.05)

            task = asyncio.create_task(run_loop())
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Should have fired at least 2 heartbeats in 0.2s with 0.05s interval
            assert call_count >= 2
        finally:
            await bridge.close()


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    """Verify that close() shuts down the underlying client."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_close_shuts_down_client(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok"})

        bridge = _make_bridge_with_transport(handler)
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
