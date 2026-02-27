"""Tests for the WebSocket ConnectionManager.

Uses Starlette TestClient for real WebSocket connections (no mocks).
"""

import asyncio
import threading
import time

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket

from ...core.aggregator import EventAggregator
from .. import websocket as websocket_module
from ..schemas.enums import AgentLifecycleState, ServerEventType
from ..websocket import ConnectionManager
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
            time.sleep(0.1)

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
            time.sleep(0.1)

            ws.send_json(
                {
                    "type": "unsubscribe",
                    "thread_ids": ["thread-1"],
                }
            )
            time.sleep(0.1)

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
            time.sleep(0.1)

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

            data = ws.receive_json()
            assert data["type"] == ServerEventType.AGENT_STATUS
            assert data["thread_id"] == "thread-1"
            assert data["state"] == AgentLifecycleState.WORKING


# ---------------------------------------------------------------------------
# Ping command
# ---------------------------------------------------------------------------


class TestPingCommand:
    """Tests for the ping no-op command."""

    def test_ping_does_not_error(self) -> None:
        """Sending a ping command does not disconnect or error the client."""
        app, _agg, _mgr = _create_app()

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            _connected = ws.receive_json()
            ws.send_json({"type": "ping"})


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
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    """Tests that the websocket module and api facade export expected names."""

    def test_all_defined(self) -> None:
        """Websocket module declares __all__ containing ConnectionManager."""
        assert hasattr(websocket_module, "__all__")
        assert "ConnectionManager" in websocket_module.__all__

    def test_facade_reexports(self) -> None:
        """lib.api re-exports ConnectionManager and it is the same class."""
        assert ConnectionManager is WebSocketConnectionManager
