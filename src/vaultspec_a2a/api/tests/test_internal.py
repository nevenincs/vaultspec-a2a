"""Tests for src/vaultspec_a2a/api/internal.py -- internal IPC router endpoints.

Validates the /internal/health, /internal/events, and /internal/heartbeat
HTTP endpoints using a real FastAPI test client with httpx.ASGITransport.

Uses a real EventAggregator as the relay target (no fakes or mocks).
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.testclient import TestClient

from ...database import (
    create_thread,
    get_permission_request,
    get_thread_execution_state,
    set_thread_repair_state,
)
from ...database.models import ThreadExecutionStateModel
from ...streaming.aggregator import EventAggregator
from ...worker.ipc import WorkerBridge
from ..internal import internal_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_app(
    *,
    with_aggregator: bool = False,
    session_factory=None,
) -> FastAPI:
    """Create a minimal FastAPI app with the internal router and wired state.

    When ``with_aggregator`` is True, a real ``EventAggregator`` - the relay
    target the ingest paths write to - is attached (no fakes).
    """
    app = FastAPI()
    app.include_router(internal_router)

    # Pre-populate app.state with the attributes the endpoints expect
    app.state.worker_last_heartbeat_ts = 0.0
    app.state.worker_active_threads = []
    if session_factory is not None:
        app.state.db_session_factory = session_factory

    app.state.aggregator = None

    if with_aggregator:
        app.state.aggregator = EventAggregator()

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


@pytest.mark.asyncio(loop_scope="function")
async def test_dispatch_application_receipt_is_not_broadcast_to_progress(
    session_factory,
) -> None:
    """The private stable dispatch identity must stop at the gateway DB edge."""
    app = _make_test_app(with_aggregator=True, session_factory=session_factory)
    aggregator = app.state.aggregator
    queue = aggregator.add_subscriber("receipt-observer")
    aggregator.subscribe("receipt-observer", ["receipt-thread"])

    async with session_factory() as session:
        await create_thread(session, thread_id="receipt-thread", status="running")
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/events",
            json={
                "type": "event",
                "thread_id": "receipt-thread",
                "payload": {
                    "type": "dispatch_applied",
                    "dispatch_id": "private-stable-id",
                    "action": "ingest",
                },
            },
        )

    assert response.status_code == 200
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.05)


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

    When the relay target is present, the endpoint accepts the event. When it is
    absent, it returns 503 so the worker can detect the unready gateway and retry
    or backoff.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_valid_event_returns_ok(self) -> None:
        app = _make_test_app(with_aggregator=True)
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
    async def test_event_with_aggregator_only_returns_ok(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The HTTP path should accept events when the aggregator is available."""
        app = _make_test_app(with_aggregator=True)
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
    async def test_event_without_relay_target_returns_503(self) -> None:
        """With no relay target seated, /internal/events returns 503.

        The guard survives the collapse to a single relay: a gateway whose
        aggregator is not yet seated must tell the worker to back off rather
        than accept an event it will silently drop.
        """
        app = _make_test_app()
        assert app.state.aggregator is None
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
    async def test_missing_thread_id_is_malformed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed event without thread_id is rejected."""
        app = _make_test_app(with_aggregator=True)
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
            with_aggregator=True,
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
    async def test_invalid_projection_timestamp_persists_without_relay_state(
        self,
        session_factory,
    ) -> None:
        """The ASGI projection route stores malformed clock data as absent.

        Execution-state projection is a persistence-only worker report. It must
        not enter subscriber or sequence state while the durable boundary safely
        treats an invalid optional timestamp as unavailable.
        """
        aggregator = EventAggregator()
        app = _make_test_app(session_factory=session_factory)
        app.state.aggregator = aggregator

        async with session_factory() as session:
            await create_thread(session, thread_id="t-invalid-projection-clock")
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": "t-invalid-projection-clock",
                    "payload": {
                        "type": "execution_state_projection",
                        "checkpoint_id": "cp-invalid-clock",
                        "snapshot_created_at": "not-an-rfc3339-timestamp",
                    },
                },
            )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert aggregator.subscriber_count() == 0
        assert aggregator.subscription_count() == 0
        assert aggregator.sequence_count() == 0

        async with session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(ThreadExecutionStateModel).where(
                            ThreadExecutionStateModel.thread_id
                            == "t-invalid-projection-clock"
                        )
                    )
                ).all()
            )

        assert len(rows) == 1
        assert rows[0].checkpoint_id == "cp-invalid-clock"
        assert rows[0].snapshot_created_at is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_plan_approval_relay_creates_durable_permission_and_can_be_responded(
        self,
        session_factory,
        checkpointer,
    ) -> None:
        """A relayed plan approval must become durably respondable."""
        from .conftest import make_app

        app, _agg, worker, _cp = make_app(session_factory, checkpointer)

        async with session_factory() as session:
            thread = await create_thread(session, title="Relay plan approval")
            await session.commit()

        request_id = f"{thread.id}:plan-approval"
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            relay = await client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": thread.id,
                    "payload": {
                        "type": "plan_approval_request",
                        "request_id": request_id,
                        "description": "Approve plan before execution",
                        "options": [
                            {
                                "option_id": "approve",
                                "name": "Approve Plan",
                                "kind": "allow_once",
                            },
                            {
                                "option_id": "reject",
                                "name": "Reject Plan",
                                "kind": "reject_once",
                            },
                        ],
                    },
                },
            )

        assert relay.status_code == 200

        async with session_factory() as session:
            permission = await get_permission_request(session, request_id)

        assert permission is not None
        assert permission.pause_reason_type == "plan_approval_request"
        assert permission.request_status == "pending"

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                f"/v1/runs/{thread.id}/permissions/{request_id}/respond",
                json={"option_id": "approve"},
            )

        assert resp.status_code == 200
        assert len(worker.dispatches) == 1
        assert worker.dispatches[0]["option_id"] == {
            "verdict": "approved",
            "notes": None,
        }

    @pytest.mark.asyncio(loop_scope="function")
    async def test_degraded_execution_state_projection_preserves_last_good_state(
        self,
        session_factory,
    ) -> None:
        """A degraded-only update must not erase the last good execution-state row."""
        app = _make_test_app(
            with_aggregator=True,
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
        app = _make_test_app(with_aggregator=True)
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
        app = _make_test_app(with_aggregator=True)
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
        app = _make_test_app(with_aggregator=True)
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
        app = _make_test_app(with_aggregator=True)
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

    @pytest.mark.asyncio(loop_scope="function")
    async def test_batch_with_aggregator_only_returns_ok(self) -> None:
        """The batch HTTP path should accept events when only the aggregator exists."""
        app = _make_test_app(with_aggregator=True)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events/batch",
                json={
                    "events": [
                        {"thread_id": "t-1", "payload": {"event_type": "chunk"}},
                        {
                            "thread_id": "t-1",
                            "payload": {
                                "event_type": "thread_terminal",
                                "status": "completed",
                            },
                        },
                    ]
                },
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio(loop_scope="function")
    async def test_batch_without_relay_target_returns_503(self) -> None:
        """The batch HTTP path should fail fast when no relay target exists."""
        app = _make_test_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/internal/events/batch",
                json={
                    "events": [{"thread_id": "t-1", "payload": {"event_type": "chunk"}}]
                },
            )
            assert resp.status_code == 503


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

    def test_missing_relay_target_log_includes_runtime_fields(self, caplog) -> None:
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
            if "No relay target available -- dropping event" in rec.message
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
    """WorkerBridge retries batch flush on gateway failures."""

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

        from ...control.config import settings
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
    """Aggregator sequence counters are pruned on thread_terminal events."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_terminal_event_prunes_thread_from_aggregator_sequences(
        self,
        session_factory,
    ) -> None:
        """_handle_terminal_event removes the terminated thread from
        aggregator _sequences.
        """
        from ...control.event_handlers import _handle_terminal_event

        aggregator = EventAggregator()
        aggregator._emitters._sequences["t-pruned"] = 5
        aggregator._emitters._sequences["t-active"] = 3
        async with session_factory() as session:
            await create_thread(session, thread_id="t-pruned")
            await session.commit()

        await _handle_terminal_event(
            "t-pruned",
            {"event_type": "thread_terminal", "status": "completed"},
            aggregator=aggregator,
            session_factory=session_factory,
        )

        assert "t-pruned" not in aggregator._emitters._sequences
        assert "t-active" in aggregator._emitters._sequences

    @pytest.mark.asyncio(loop_scope="function")
    async def test_terminal_event_log_includes_runtime_fields(
        self,
        session_factory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Terminal update logs should carry thread/status/event metadata."""
        from ...control.event_handlers import _handle_terminal_event
        from ...database import update_thread_status
        from ...thread.enums import ThreadStatus

        aggregator = EventAggregator()
        async with session_factory() as session:
            thread = await create_thread(session, thread_id="t-logged")
            await update_thread_status(session, thread.id, ThreadStatus.RUNNING)
            await session.commit()

        with caplog.at_level(
            logging.INFO, logger="vaultspec_a2a.control.event_handlers"
        ):
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
        from ...control.event_handlers import _handle_terminal_event

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

        with caplog.at_level(
            logging.INFO, logger="vaultspec_a2a.control.event_handlers"
        ):
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


class TestTerminalEventFailureReasonPersistence:
    """S37 / failure-reason persistence: error_detail durably records on FAILED.

    012840a4 made the SSE relay surface the real exception text; these prove
    the durable counterpart — a reloaded panel (run-status alone, never the
    live stream) recovers the SAME reason, not a bare "failed".
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_error_detail_on_a_failed_terminal_event_is_durably_recorded(
        self,
        session_factory,
    ) -> None:
        from ...control.event_handlers import _handle_terminal_event
        from ...database.models import ThreadModel

        async with session_factory() as session:
            thread = await create_thread(session, thread_id="t-failed-with-reason")
            await session.commit()
            assert thread.failure_reason is None

        await _handle_terminal_event(
            "t-failed-with-reason",
            {
                "event_type": "thread_terminal",
                "status": "failed",
                "error_detail": "Ingest stalled: no event from the graph for over 90s",
            },
            session_factory=session_factory,
        )

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-failed-with-reason")
            assert row is not None
            assert row.status == "failed"
            assert (
                row.failure_reason
                == "Ingest stalled: no event from the graph for over 90s"
            )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_completed_terminal_event_leaves_failure_reason_untouched(
        self,
        session_factory,
    ) -> None:
        """No error_detail on completed/cancelled — the column stays None."""
        from ...control.event_handlers import _handle_terminal_event
        from ...database import update_thread_status
        from ...database.models import ThreadModel
        from ...thread.enums import ThreadStatus

        async with session_factory() as session:
            thread = await create_thread(session, thread_id="t-completed-no-reason")
            # submitted -> completed directly is not a valid transition (mirrors
            # test_terminal_event_log_includes_runtime_fields above); route
            # through running first, matching a real dispatched run.
            await update_thread_status(session, thread.id, ThreadStatus.RUNNING)
            await session.commit()

        await _handle_terminal_event(
            "t-completed-no-reason",
            {"event_type": "thread_terminal", "status": "completed"},
            session_factory=session_factory,
        )

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-completed-no-reason")
            assert row is not None
            assert row.status == "completed"
            assert row.failure_reason is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_non_string_error_detail_is_ignored_not_persisted(
        self,
        session_factory,
    ) -> None:
        """A malformed relay payload (e.g. error_detail as a number) never
        reaches the durable column — falls back to leaving it untouched
        rather than raising or coercing garbage into the record."""
        from ...control.event_handlers import _handle_terminal_event
        from ...database.models import ThreadModel

        async with session_factory() as session:
            await create_thread(session, thread_id="t-malformed-detail")
            await session.commit()

        await _handle_terminal_event(
            "t-malformed-detail",
            {"event_type": "thread_terminal", "status": "failed", "error_detail": 42},
            session_factory=session_factory,
        )

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-malformed-detail")
            assert row is not None
            assert row.status == "failed"
            assert row.failure_reason is None


class TestTerminalEventProviderConditionPersistence:
    """The condition on a relayed terminal reaches the durable column.

    The reason says what happened, the condition says what the reader should do
    about it. A client left to derive the second from the first is back to
    matching vendor prose, so both are persisted from the same terminal event.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_relayed_condition_is_durably_recorded(
        self,
        session_factory,
    ) -> None:
        """The lane's own verdict survives the relay hop into the column."""
        from ...control.event_handlers import _handle_terminal_event
        from ...database.models import ThreadModel
        from ...providers import ProviderCondition

        async with session_factory() as session:
            await create_thread(session, thread_id="t-failed-throttled")
            await session.commit()

        await _handle_terminal_event(
            "t-failed-throttled",
            {
                "event_type": "thread_terminal",
                "status": "failed",
                "error_detail": "the provider refused for rate",
                "provider_condition": ProviderCondition.THROTTLED.value,
            },
            session_factory=session_factory,
        )

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-failed-throttled")
            assert row is not None
            assert row.status == "failed"
            assert row.provider_condition == ProviderCondition.THROTTLED.value
            assert row.failure_reason == "the provider refused for rate"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_failed_terminal_with_no_condition_records_the_floor(
        self,
        session_factory,
    ) -> None:
        """A failed run never persists a null condition.

        A run that fails without a classification is the blank terminal this
        campaign removes; the floor says plainly that nothing classified it,
        which a consumer can render and act on.
        """
        from ...control.event_handlers import _handle_terminal_event
        from ...database.models import ThreadModel
        from ...providers import ProviderCondition

        async with session_factory() as session:
            await create_thread(session, thread_id="t-failed-unclassified")
            await session.commit()

        await _handle_terminal_event(
            "t-failed-unclassified",
            {"event_type": "thread_terminal", "status": "failed"},
            session_factory=session_factory,
        )

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-failed-unclassified")
            assert row is not None
            assert row.provider_condition == ProviderCondition.UNKNOWN.value

    @pytest.mark.asyncio(loop_scope="function")
    async def test_an_unrecognised_condition_is_refused_for_the_floor(
        self,
        session_factory,
    ) -> None:
        """A value outside the closed vocabulary never reaches the column.

        The column is read by a second repository that validates it against the
        same closed set, so passing an unknown string through would hand that
        consumer a value it must reject - strictly worse than the floor, which
        it can at least render.
        """
        from ...control.event_handlers import _handle_terminal_event
        from ...database.models import ThreadModel
        from ...providers import ProviderCondition

        async with session_factory() as session:
            await create_thread(session, thread_id="t-failed-bogus-condition")
            await session.commit()

        await _handle_terminal_event(
            "t-failed-bogus-condition",
            {
                "event_type": "thread_terminal",
                "status": "failed",
                "provider_condition": "teapot_overheated",
            },
            session_factory=session_factory,
        )

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-failed-bogus-condition")
            assert row is not None
            assert row.provider_condition == ProviderCondition.UNKNOWN.value

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_completed_terminal_records_no_condition(
        self,
        session_factory,
    ) -> None:
        """A run that did not fail has no provider failure to classify."""
        from ...control.event_handlers import _handle_terminal_event
        from ...database import update_thread_status
        from ...database.models import ThreadModel
        from ...thread.enums import ThreadStatus

        async with session_factory() as session:
            thread = await create_thread(session, thread_id="t-completed-condition")
            await update_thread_status(session, thread.id, ThreadStatus.RUNNING)
            await session.commit()

        await _handle_terminal_event(
            "t-completed-condition",
            {
                "event_type": "thread_terminal",
                "status": "completed",
                "provider_condition": "throttled",
            },
            session_factory=session_factory,
        )

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-completed-condition")
            assert row is not None
            assert row.status == "completed"
            assert row.provider_condition is None


class TestConditionSurvivesAReload:
    """A reloading client recovers the condition from run-status ALONE.

    The whole point of persisting the condition is the client that was not
    listening: the error frame carrying it is droppable and a reconnecting
    subscriber gets a fresh empty queue, so a run's classification is only as
    recoverable as this read makes it. Nothing here subscribes to the stream -
    the terminal is relayed over the real worker-to-gateway HTTP hop, and the
    answer is read back over the real product route on a separate connection.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_run_status_recovers_the_condition_with_no_stream_attached(
        self,
        session_factory,
        checkpointer,
    ) -> None:
        from ...providers import ProviderCondition
        from .conftest import make_app

        app, _aggregator, _worker, _checkpointer = make_app(
            session_factory, checkpointer
        )
        async with session_factory() as session:
            await create_thread(session, thread_id="t-reload-condition")
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            relayed = await client.post(
                "/internal/events",
                json={
                    "thread_id": "t-reload-condition",
                    "payload": {
                        "event_type": "thread_terminal",
                        "status": "failed",
                        "error_detail": (
                            "Graph event stream failed unexpectedly: "
                            "AcpPromptError: credit balance too low"
                        ),
                        "provider_condition": (
                            ProviderCondition.CREDITS_EXHAUSTED.value
                        ),
                    },
                },
            )
            assert relayed.status_code == 200

        # A SEPARATE client, as a reloaded panel would be: no subscription, no
        # replay, nothing retained from the connection the failure arrived on.
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            status = await client.get("/v1/runs/t-reload-condition")

        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "failed"
        assert body["provider_condition"] == ProviderCondition.CREDITS_EXHAUSTED.value
        # The reason survives beside it: the two answer different questions and a
        # client needs both, so recovering one without the other is a half-fix.
        assert "credit balance too low" in body["failure_reason"]

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_run_that_never_failed_discloses_no_condition(
        self,
        session_factory,
        checkpointer,
    ) -> None:
        """An absent condition means no failure, never an unreported one."""
        from .conftest import make_app

        app, _aggregator, _worker, _checkpointer = make_app(
            session_factory, checkpointer
        )
        async with session_factory() as session:
            await create_thread(session, thread_id="t-reload-no-condition")
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            status = await client.get("/v1/runs/t-reload-no-condition")

        assert status.status_code == 200
        assert status.json()["provider_condition"] is None

    @pytest.mark.asyncio(loop_scope="function")
    async def test_run_status_discloses_why_an_operation_missed_a_live_run(
        self,
        session_factory,
        checkpointer,
    ) -> None:
        """A follow-up that never arrived is readable WITHOUT faking a failure.

        The paths that record this - an undelivered follow-up, an undelivered
        clarification resume - deliberately decline to write a failure reason,
        because the run is still parked on its question and may yet complete.
        That decision is only honest if the account still reaches a client, so
        this is the read that keeps it from being durable and unreadable.
        """
        from .conftest import make_app

        app, _aggregator, _worker, _checkpointer = make_app(
            session_factory, checkpointer
        )
        async with session_factory() as session:
            thread = await create_thread(session, thread_id="t-live-run-repair")
            await set_thread_repair_state(
                session,
                thread.id,
                repair_status=thread.repair_status,
                repair_reason="Follow-up message not delivered: worker unreachable",
            )
            await session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            status = await client.get("/v1/runs/t-live-run-repair")

        assert status.status_code == 200
        body = status.json()
        assert body["repair_reason"] == (
            "Follow-up message not delivered: worker unreachable"
        )
        # The run is ALIVE. Reporting either failure field here would tell a user
        # their run died when it is still waiting - the precise confusion the
        # two-channel split exists to prevent.
        assert body["failure_reason"] is None
        assert body["provider_condition"] is None
        assert body["status"] != "failed"


def _worker_bridge_into(app: FastAPI) -> WorkerBridge:
    """A real worker bridge whose relay posts into *app* over real HTTP.

    The executor reports a rejection by emitting a terminal through its bridge,
    which is an HTTP client. Pointing that client at the gateway app under test
    makes the worker-to-gateway hop real, so what is asserted afterwards is what
    the gateway actually received rather than what the worker meant to send.
    """
    bridge = WorkerBridge(api_url="http://gateway", worker_id="invariant-test")
    bridge._client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://gateway",
    )
    return bridge


class TestNoFailedRunPersistsWithoutACondition:
    """The invariant, swept across the two paths that fail a run without ingest.

    A failed run carrying no condition is the blank terminal this campaign
    exists to remove: a client sees ``failed`` and has nothing to act on. The
    two paths that reach that state without a provider ever being engaged are a
    dispatch that never left the gateway and a worker rejection before the graph
    ran, so both are asserted here rather than only the ingest path that already
    had coverage.
    """

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_worker_rejection_persists_a_condition(
        self,
        session_factory,
        checkpointer,
    ) -> None:
        """A dispatch the worker refuses reaches the column with a condition.

        Driven through the real executor and the real relay: the rejection is
        emitted as a terminal by the worker, crosses HTTP into the gateway, and
        is read back from the durable row. Nothing about the condition is
        asserted at the worker - only what survived the whole hop.
        """
        from ...database.models import ThreadModel
        from ...ipc.schemas import DispatchRequest
        from ...worker.executor import Executor
        from .conftest import make_app

        app, _aggregator, _worker, _checkpointer = make_app(
            session_factory, checkpointer
        )
        async with session_factory() as session:
            await create_thread(session, thread_id="t-worker-rejection")
            await session.commit()

        bridge = _worker_bridge_into(app)
        executor = Executor(checkpointer=checkpointer, bridge=bridge)
        # No graph is registered for this thread and the dispatch names no
        # preset, which is the worker's missing-graph refusal - a real run that
        # fails before any provider is engaged.
        await executor.handle_dispatch(
            DispatchRequest(
                action="ingest",
                thread_id="t-worker-rejection",
                content="do the thing",
                recursion_limit=25,
            )
        )
        await bridge.flush_events()

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-worker-rejection")
            assert row is not None
            assert row.status == "failed"
            # The invariant. The specific member is the floor here and that is
            # correct - nothing reached a provider - but what this asserts is
            # that SOMETHING was recorded, because a null here is the failure
            # mode, not a particular value.
            assert row.provider_condition is not None
            # A condition with no account beside it is only half an answer.
            assert row.failure_reason

    @pytest.mark.asyncio(loop_scope="function")
    async def test_a_dispatch_failure_persists_a_condition(
        self,
        session_factory,
    ) -> None:
        """A dispatch that never left the gateway fails the run with a condition."""
        from ...control.repair_transitions import apply_dispatch_failure
        from ...database.models import ThreadModel
        from ...thread.enums import ThreadStatus

        async with session_factory() as session:
            await create_thread(session, thread_id="t-dispatch-failure")
            await session.commit()

        async with session_factory() as session:
            await apply_dispatch_failure(
                session,
                "t-dispatch-failure",
                failed_status=ThreadStatus.FAILED,
                reason="the gateway worker is not reachable",
            )
            await session.commit()

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-dispatch-failure")
            assert row is not None
            assert row.status == "failed"
            assert row.provider_condition is not None
            assert row.failure_reason

    @pytest.mark.asyncio(loop_scope="function")
    async def test_an_undelivered_resume_is_not_a_failed_run_and_records_none(
        self,
        session_factory,
    ) -> None:
        """The honest exception to the sweep above, asserted rather than glossed.

        An undelivered permission resume settles the run to INPUT_REQUIRED: the
        answer did not arrive, but the run is alive and still parked on its
        question. It is NOT a failed run, so it correctly persists no condition
        and no failure reason - stamping either would make a reloading client
        report a failure that never happened. Its account survives on the repair
        reason, which a still-live run can honestly carry.
        """
        from ...control.repair_transitions import apply_dispatch_failure
        from ...database.models import ThreadModel
        from ...thread.enums import ThreadStatus

        async with session_factory() as session:
            await create_thread(session, thread_id="t-undelivered-resume")
            await session.commit()

        async with session_factory() as session:
            await apply_dispatch_failure(
                session,
                "t-undelivered-resume",
                failed_status=ThreadStatus.INPUT_REQUIRED,
                reason="the gateway worker is not reachable",
            )
            await session.commit()

        async with session_factory() as session:
            row = await session.get(ThreadModel, "t-undelivered-resume")
            assert row is not None
            assert row.status == ThreadStatus.INPUT_REQUIRED.value
            assert row.provider_condition is None
            assert row.failure_reason is None
            assert row.repair_reason == "the gateway worker is not reachable"
