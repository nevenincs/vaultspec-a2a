"""Tests for the WebSocket ConnectionManager.

Uses Starlette TestClient for real WebSocket connections (no mocks).
"""

import asyncio
import logging
import threading

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket

from ...core.aggregator import EventAggregator
from ...core.config import settings
from .. import websocket as websocket_module
from ..schemas.enums import AgentControlAction, AgentLifecycleState, ServerEventType
from ..websocket import ConnectionManager, WebSocketCommandRejectedError
from ..websocket import ConnectionManager as WebSocketConnectionManager


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _create_app() -> tuple[Starlette, EventAggregator, ConnectionManager]:
    """Create a minimal Starlette app wired to a real ConnectionManager."""
    aggregator = EventAggregator()
    manager = ConnectionManager(aggregator)

    async def ws_endpoint(websocket: WebSocket) -> None:
        client_id = await manager.connect(websocket)
        await manager.listen(client_id)

    app = Starlette(routes=[WebSocketRoute("/ws", ws_endpoint)])
    return app, aggregator, manager


# ---------------------------------------------------------------------------
# ConnectedEvent on open
# ---------------------------------------------------------------------------


class TestConnectedEvent:
    """Tests for the initial ConnectedEvent sent on WebSocket open."""

    def test_receives_connected_event_on_open(self) -> None:
        """Client receives a ConnectedEvent immediately after connecting."""
        app, _agg, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
            assert data["type"] == ServerEventType.CONNECTED
            assert "client_id" in data
            assert data["server_version"] == "0.1.0"
            assert isinstance(data["active_threads"], list)


# ---------------------------------------------------------------------------
# Subscribe / Unsubscribe
# ---------------------------------------------------------------------------


class TestSubscriptions:
    """Tests for the subscribe and unsubscribe client commands."""

    def test_subscribe_command(self) -> None:
        """Subscribe command registers the thread_ids on the aggregator."""
        app, aggregator, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            connected = ws.receive_json()
            client_id = connected["client_id"]

            ws.send_json(
                {
                    "type": "subscribe",
                    "thread_ids": ["thread-1", "thread-2"],
                }
            )
            # Ping forces the server loop past the subscribe handler
            ws.send_json({"type": "ping"})

            subs = aggregator.get_subscriptions(client_id)
            assert "thread-1" in subs
            assert "thread-2" in subs

    def test_unsubscribe_command(self) -> None:
        """Unsubscribe command removes the specified thread_id from the subscription."""
        app, aggregator, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            connected = ws.receive_json()
            client_id = connected["client_id"]

            ws.send_json(
                {
                    "type": "subscribe",
                    "thread_ids": ["thread-1", "thread-2"],
                }
            )
            ws.send_json(
                {
                    "type": "unsubscribe",
                    "thread_ids": ["thread-1"],
                }
            )
            # Ping forces the server loop past both handlers
            ws.send_json({"type": "ping"})

            subs = aggregator.get_subscriptions(client_id)
            assert "thread-1" not in subs
            assert "thread-2" in subs


# ---------------------------------------------------------------------------
# Event delivery
# ---------------------------------------------------------------------------


class TestEventDelivery:
    """Tests that events emitted on subscribed threads are delivered to the client."""

    def test_receives_broadcast_events(self) -> None:
        """An event emitted on a subscribed thread arrives at the WebSocket client."""
        app, aggregator, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()

            ws.send_json(
                {
                    "type": "subscribe",
                    "thread_ids": ["thread-1"],
                }
            )
            # Ping forces the server loop past the subscribe handler
            ws.send_json({"type": "ping"})

            def emit_event() -> None:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    aggregator.emit_agent_status(
                        thread_id="thread-1",
                        agent_id="agent-1",
                        node_name="worker",
                        state=AgentLifecycleState.WORKING,
                    )
                )
                loop.close()

            t = threading.Thread(target=emit_event)
            t.start()
            t.join(timeout=5)

            # Skip any heartbeat messages (ping now sends a pong heartbeat)
            for _ in range(5):
                data = ws.receive_json()
                if data["type"] != "heartbeat":
                    break
            assert data["type"] == ServerEventType.AGENT_STATUS
            assert data["thread_id"] == "thread-1"
            assert data["state"] == AgentLifecycleState.WORKING


# ---------------------------------------------------------------------------
# Ping command
# ---------------------------------------------------------------------------


class TestPingCommand:
    """Tests for the ping command (responds with a heartbeat)."""

    def test_ping_responds_with_heartbeat(self) -> None:
        """Sending a ping command returns a heartbeat response."""
        app, _agg, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "heartbeat"
            assert "timestamp" in pong
            assert "server_uptime_seconds" in pong


# ---------------------------------------------------------------------------
# Invalid command handling
# ---------------------------------------------------------------------------


class TestInvalidCommands:
    """Tests that unknown command types are silently discarded."""

    def test_invalid_command_does_not_crash(self) -> None:
        """An unrecognised command type is discarded; subsequent ping still works."""
        app, _agg, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()
            ws.send_json({"type": "nonexistent_command", "garbage": True})
            ws.send_json({"type": "ping"})


# ---------------------------------------------------------------------------
# Permission response WebSocket rejection (ADR-011 §3.1)
# ---------------------------------------------------------------------------


class TestPermissionResponseRejection:
    """permission_response over WebSocket must be rejected with an error frame."""

    def test_permission_response_returns_error_frame(self) -> None:
        """Sending permission_response over WebSocket triggers an error event.

        ADR-011 §3.1 mandates REST-only delivery for permission responses.
        The server must send back an explicit error frame so the client can
        redirect to POST /threads/{id}/permission.
        """
        app, _agg, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()

            ws.send_json(
                {
                    "type": "permission_response",
                    "request_id": "req-123",
                    "option_id": "allow_once",
                    "thread_id": "thread-1",
                }
            )

            # Server must send back an error frame immediately
            error = ws.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "PERMISSION_RESPONSE_WS_FORBIDDEN"
            assert error["recoverable"] is True
            assert "REST" in error["message"]


# ---------------------------------------------------------------------------
# SEND_MESSAGE command dispatch (API-M5)
# ---------------------------------------------------------------------------


class TestSendMessageCommand:
    """Tests for the SEND_MESSAGE command dispatch."""

    def test_send_message_invokes_handler(self) -> None:
        """SEND_MESSAGE command calls the registered message handler."""
        app, _aggregator, manager = _create_app()

        received: list[tuple[str, str, str | None]] = []

        async def _handler(thread_id: str, content: str, agent_id: str | None) -> None:
            received.append((thread_id, content, agent_id))

        manager.set_message_handler(_handler)

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()

            ws.send_json(
                {
                    "type": "send_message",
                    "thread_id": "thread-1",
                    "content": "Hello from client",
                    "agent_id": "coder",
                }
            )
            # Ping forces server to process the send_message before we check
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong

        assert len(received) == 1
        assert received[0] == ("thread-1", "Hello from client", "coder")

    def test_send_message_log_includes_runtime_fields(
        self, caplog
    ) -> None:
        """SEND_MESSAGE log records should carry client/thread/agent fields."""
        app, _aggregator, manager = _create_app()

        async def _handler(thread_id: str, content: str, agent_id: str | None) -> None:
            return None

        manager.set_message_handler(_handler)

        with (
            caplog.at_level(logging.INFO, logger="vaultspec_a2a.api.websocket"),
            TestClient(app) as client,
            client.websocket_connect("/ws") as ws,
        ):
            connected = ws.receive_json()
            client_id = connected["client_id"]
            ws.send_json(
                {
                    "type": "send_message",
                    "thread_id": "thread-1",
                    "content": "Hello from client",
                    "agent_id": "coder",
                }
            )
            ws.send_json({"type": "ping"})
            ws.receive_json()

        record = next(
            rec for rec in caplog.records if "sent message to thread" in rec.message
        )
        assert record.client_id == client_id
        assert record.thread_id == "thread-1"
        assert record.agent_id == "coder"
        assert record.action == "send_message"
        assert record.command_type == "send_message"

    def test_send_message_without_handler_emits_status(self) -> None:
        """SEND_MESSAGE with no handler emits SUBMITTED agent status."""
        app, agg, _manager = _create_app()

        # Add subscriber so aggregator can route events
        agg.add_subscriber("test-sub")
        agg.subscribe("test-sub", ["thread-emit"])

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()

            ws.send_json(
                {
                    "type": "subscribe",
                    "thread_ids": ["thread-emit"],
                }
            )
            ws.send_json(
                {
                    "type": "send_message",
                    "thread_id": "thread-emit",
                    "content": "No handler here",
                }
            )
            # Ping forces processing
            ws.send_json({"type": "ping"})

            # Collect events; one should be the AGENT_STATUS/SUBMITTED
            events = []
            for _ in range(10):
                data = ws.receive_json()
                if data["type"] not in ("heartbeat",):
                    events.append(data)
                if len(events) >= 1:
                    break

        status_events = [e for e in events if e["type"] == ServerEventType.AGENT_STATUS]
        assert any(
            e.get("state") == AgentLifecycleState.SUBMITTED for e in status_events
        )

    def test_send_message_handler_rejection_emits_error(self) -> None:
        """Structured handler rejections should be emitted as WS error frames."""
        app, _aggregator, manager = _create_app()

        async def _handler(thread_id: str, content: str, agent_id: str | None) -> None:
            raise WebSocketCommandRejectedError(
                thread_id=thread_id,
                code="THREAD_STATE_DRIFT",
                message="Thread state drift detected.",
                recoverable=True,
                metadata={"checkpoint_present": True},
            )

        manager.set_message_handler(_handler)

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()
            ws.send_json(
                {
                    "type": "send_message",
                    "thread_id": "thread-drift",
                    "content": "Hello from client",
                }
            )
            error = ws.receive_json()

        assert error["type"] == "error"
        assert error["thread_id"] == "thread-drift"
        assert error["code"] == "THREAD_STATE_DRIFT"
        assert error["recoverable"] is True
        assert error["metadata"]["checkpoint_present"] is True


# ---------------------------------------------------------------------------
# AGENT_CONTROL command dispatch (API-M5)
# ---------------------------------------------------------------------------


class TestAgentControlCommand:
    """Tests for the AGENT_CONTROL command dispatch."""

    def test_agent_control_invokes_handler(self) -> None:
        """AGENT_CONTROL command calls the registered control handler."""
        app, _aggregator, manager = _create_app()

        received: list[tuple[str, str, AgentControlAction]] = []

        async def _ctrl(
            thread_id: str, agent_id: str, action: AgentControlAction
        ) -> None:
            received.append((thread_id, agent_id, action))

        manager.set_agent_control_handler(_ctrl)

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()

            ws.send_json(
                {
                    "type": "agent_control",
                    "thread_id": "thread-ctrl",
                    "agent_id": "coder",
                    "action": "terminate",
                }
            )
            ws.send_json({"type": "ping"})
            ws.receive_json()  # pong

        assert len(received) == 1
        assert received[0] == ("thread-ctrl", "coder", AgentControlAction.TERMINATE)

    def test_rejected_command_log_includes_runtime_fields(self, caplog) -> None:
        """Rejected WS commands should log client/thread/error correlation fields."""
        app, _aggregator, manager = _create_app()

        async def _ctrl(
            thread_id: str, agent_id: str, action: AgentControlAction
        ) -> None:
            raise WebSocketCommandRejectedError(
                thread_id=thread_id,
                code="THREAD_STATE_DRIFT",
                message="Thread state drift detected.",
                recoverable=True,
                metadata={"checkpoint_present": True},
            )

        manager.set_agent_control_handler(_ctrl)

        with (
            caplog.at_level(logging.WARNING, logger="vaultspec_a2a.api.websocket"),
            TestClient(app) as client,
            client.websocket_connect("/ws") as ws,
        ):
            connected = ws.receive_json()
            client_id = connected["client_id"]
            ws.send_json(
                {
                    "type": "agent_control",
                    "thread_id": "thread-ctrl",
                    "agent_id": "coder",
                    "action": "terminate",
                }
            )
            ws.receive_json()

        record = next(
            rec for rec in caplog.records if "Rejected websocket command" in rec.message
        )
        assert record.client_id == client_id
        assert record.thread_id == "thread-ctrl"
        assert record.error_code == "THREAD_STATE_DRIFT"
        assert record.action == "command_rejected"
        assert record.recoverable is True


# ---------------------------------------------------------------------------
# Oversized frame rejection (API-M5)
# ---------------------------------------------------------------------------


class TestOversizedFrame:
    """Tests that oversized WebSocket frames are rejected without crashing."""

    def test_oversized_message_is_dropped(self) -> None:
        """A message exceeding the configured max size is silently dropped.

        The server should continue processing subsequent valid commands.
        """
        app, _agg, _mgr = _create_app()
        # Craft a message slightly over the limit (JSON overhead adds bytes)
        oversized_content = "x" * (settings.ws_max_message_bytes + 100)
        msg_content = '{"type":"send_message","thread_id":"t1","content":"'
        oversized_msg = msg_content + oversized_content + '"}}'

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()

            ws.send_text(oversized_msg)
            # A subsequent ping must still be processed — server did not crash
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()

        assert pong["type"] == "heartbeat"


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    """Tests that the websocket module and api facade export expected names."""

    def test_all_defined(self) -> None:
        """Websocket module declares __all__ containing ConnectionManager."""
        assert hasattr(websocket_module, "__all__")
        assert "ConnectionManager" in websocket_module.__all__

    def test_facade_reexports(self) -> None:
        """vaultspec_a2a.api re-exports ConnectionManager and it is the same class."""
        assert ConnectionManager is WebSocketConnectionManager
