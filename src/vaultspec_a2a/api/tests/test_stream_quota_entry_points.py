"""The stream quota must bind at every entry point, not just the one that checks.

The global cap on progress-stream subscribers is already proven against the SSE
edge with a real authenticated client (see the S160 global-quota cases in
``test_progress_allowlist``). That edge is not the only way into the subscriber
registry: the attach-gated event WebSocket registers against the very same
registry, and the SSE route's pre-check runs while the response is being built,
before the registration it authorises actually happens.

So these cover what the route-level check cannot: that an authenticated
WebSocket caller is held to the same bound, and that a caller refused at
registration is told so rather than dropped. Real gateway apps, the real attach
gate, and the real registry - no mocks and no auth bypass. Capacity is created by
registering real subscribers through the aggregator's production API, so the
registry is genuinely full rather than reported full.

The per-principal dimension is deliberately unrepresented here. This edge
authenticates one shared service token and derives no caller identity from it, so
there is no principal to key a quota on and no honest test to write for one.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient

from ...domain_config import domain_config
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ThreadStatus
from ...thread.errors import EventAggregatorError
from ..app import create_app
from ..routes.thread_stream import _stream_thread_events
from ..websocket import ConnectionManager

_SERVICE_TOKEN = "discovery-service-token"


def _gated_ws_app(aggregator: EventAggregator):
    """A real gateway app with the WS attach gate armed over *aggregator*."""

    @asynccontextmanager
    async def _noop_lifespan(_app):
        yield

    app = create_app(lifespan=_noop_lifespan)
    app.state.v1_service_token = _SERVICE_TOKEN
    app.state.allow_unauthenticated_v1_for_testing = False
    app.state.aggregator = aggregator
    app.state.connection_manager = ConnectionManager(aggregator)
    return app


def _occupy(aggregator: EventAggregator, count: int, *, prefix: str) -> None:
    """Register *count* real subscribers through the production registry API."""
    for index in range(count):
        aggregator.add_subscriber(f"{prefix}-{index}")


def test_an_authenticated_websocket_is_admitted_below_capacity() -> None:
    """Control: with room free the attach-gated WebSocket connects and takes a slot.

    This is what makes the refusal below meaningful - it establishes that the
    credential is accepted and that a WebSocket really does consume registry
    capacity, so the refusal cannot be an attach-gate artefact.
    """
    aggregator = EventAggregator()
    app = _gated_ws_app(aggregator)
    client = TestClient(app)

    with client.websocket_connect(
        "/ws", headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"}
    ) as websocket:
        websocket.receive_json()

        assert aggregator.subscriber_count() == 1


def test_an_authenticated_websocket_is_refused_at_capacity() -> None:
    """A WebSocket caller cannot walk past the cap the SSE route respects.

    This is the path the bound previously missed. The limit was enforced in the
    SSE route alone, so an authenticated WebSocket flood registered subscribers
    that check never saw and the gateway sailed past its own configured limit
    while continuing to refuse SSE callers on the strength of it.
    """
    aggregator = EventAggregator()
    limit = domain_config.max_stream_connections
    _occupy(aggregator, limit, prefix="held")
    app = _gated_ws_app(aggregator)
    client = TestClient(app)

    with (
        pytest.raises(EventAggregatorError, match="global limit"),
        client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"}
        ),
    ):
        pass

    # The substantive assertion: refused has to mean not registered.
    assert aggregator.subscriber_count() == limit


def test_a_websocket_refusal_leaves_the_held_subscribers_serviceable() -> None:
    """Refusing the newcomer must not disturb the callers already being served.

    A cap that shed existing streams under load would turn a bounded resource
    into an outage for the clients that arrived first.
    """
    aggregator = EventAggregator()
    limit = domain_config.max_stream_connections
    _occupy(aggregator, limit, prefix="held")
    app = _gated_ws_app(aggregator)
    client = TestClient(app)

    with (
        pytest.raises(EventAggregatorError),
        client.websocket_connect(
            "/ws", headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"}
        ),
    ):
        pass

    assert aggregator.get_subscriber_queue("held-0") is not None
    assert aggregator.get_subscriber_queue("held-42") is not None


@pytest.mark.asyncio(loop_scope="function")
async def test_a_stream_refused_at_registration_is_told_why() -> None:
    """The registry's refusal reaches the SSE caller as a frame, not a dead socket.

    The route's pre-check and the registration it authorises are separated by the
    response-start boundary: the body generator does not run until the client
    begins reading, and another caller - a WebSocket, say - can take the last slot
    in between. The registry is therefore where the bound actually holds, and a
    caller that loses that race must learn why.

    Drives the real response generator against a genuinely full registry, which is
    precisely the state that race produces.
    """
    aggregator = EventAggregator()
    limit = domain_config.max_stream_connections
    _occupy(aggregator, limit, prefix="raced")

    frames = [
        frame
        async for frame in _stream_thread_events(
            aggregator=aggregator,
            thread_id="run-1",
            initial_status=ThreadStatus.RUNNING.value,
        )
    ]

    assert len(frames) == 1
    body = frames[0].decode("utf-8")
    assert "stream_rejected" in body
    assert "stream_limit_exceeded" in body
    # The loser of the race must not linger in the registry it was refused from.
    assert aggregator.subscriber_count() == limit
