"""The desktop event WebSocket requires the attach credential before accept."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from vaultspec_a2a.api.app import create_app
from vaultspec_a2a.streaming.aggregator import EventAggregator

_TOKEN = "attach-credential-token-0f1e2d3c4b5a6978"


def _gated_ws_app():
    """A real gateway app with the WS attach gate armed and a connection manager."""
    from vaultspec_a2a.api.websocket import ConnectionManager

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app = create_app(lifespan=_noop_lifespan)
    app.state.v1_service_token = _TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    aggregator = EventAggregator()
    app.state.aggregator = aggregator
    app.state.connection_manager = ConnectionManager(aggregator)
    return app


def test_ws_rejects_unauthenticated_client() -> None:
    """A WebSocket with no attach credential is closed before it is accepted."""
    app = _gated_ws_app()
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws"),
    ):
        pass
    assert exc_info.value.code == 1008


def test_ws_rejects_wrong_credential() -> None:
    """A WebSocket bearing the wrong credential is closed with the policy code."""
    app = _gated_ws_app()
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/ws", headers={"authorization": "Bearer not-the-real-token"}
        ),
    ):
        pass
    assert exc_info.value.code == 1008


def test_ws_accepts_valid_attach_credential() -> None:
    """A WebSocket bearing the correct attach credential is accepted."""
    app = _gated_ws_app()
    client = TestClient(app)
    with client.websocket_connect(
        "/ws", headers={"authorization": f"Bearer {_TOKEN}"}
    ) as websocket:
        # Reaching the context body proves the handshake was accepted past the gate.
        websocket.close()
