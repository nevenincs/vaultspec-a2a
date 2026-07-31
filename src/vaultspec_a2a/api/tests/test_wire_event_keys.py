"""The relayed event-type key pair must hold on every path that produces one.

A relayed event names its type under two keys, ``type`` and ``event_type``, and
both have live readers. The rule that keeps them in step had three near-copies
and one bypass: the WebSocket terminal broadcast built its payload with
``event_type`` alone and handed it straight to ``broadcast_to_thread``, never
crossing the relay seam that mirrors the pair, while the SSE normaliser it fed
could repair only that direction and never the reverse.

Nothing was visibly broken because the one consumer that read the bypassed
payload happened to read the key it carried. These tests remove the coincidence:
they drive the real producing paths and assert the payload is classifiable by a
``type``-reading consumer, which is what the wire discriminator has always been.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from ...database.thread_repository import create_thread
from ...thread.enums import ThreadStatus
from ...thread.snapshots import (
    is_permission_event,
    is_progress_event,
    is_terminal_event,
    normalize_wire_event_type,
    wire_event_type,
)
from ..websocket import ConnectionManager
from ..ws_dispatch import create_dispatch_message_handler
from .conftest import make_app

# Closed port: the IANA discard service is not listening on the loopback test
# host, so a dispatch POST to it is refused by the real transport. The repo's
# established way to produce a genuine unreachable worker without a mock.
_UNREACHABLE_WORKER = "http://127.0.0.1:9"


# ---------------------------------------------------------------------------
# The bypass: a WS-origin terminal payload reaching a real client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_ws_terminal_broadcast_is_readable_by_a_type_reading_consumer(
    session_factory, checkpointer
) -> None:
    """A WS-origin terminal frame names its type under the wire discriminator.

    Driven through the real production seam end to end: a real WebSocket client
    subscribed to a real thread row, the real dispatch handler the lifespan
    installs, and a real transport refusal from a closed port. The handler marks
    the thread FAILED and broadcasts the terminal frame directly to subscriber
    queues - the one producing path that never crosses the relay normaliser - so
    the frame the client actually receives is the assertion target.

    A consumer discriminating on ``type`` (the wire discriminator every relayed
    frame is read by) must be able to classify it. Before the key pair was
    mirrored at construction, this frame arrived carrying ``event_type`` alone.
    """
    app, aggregator, _worker, _cp = make_app(session_factory, checkpointer)

    async with session_factory() as session:
        thread = await create_thread(
            session, status=ThreadStatus.RUNNING, title="ws terminal broadcast"
        )
        thread_id = thread.id
        await session.commit()

    manager = ConnectionManager(aggregator)
    app.state.connection_manager = manager

    async with httpx.AsyncClient(
        base_url=_UNREACHABLE_WORKER, timeout=2.0
    ) as unreachable:
        manager.set_message_handler(
            create_dispatch_message_handler(
                unreachable,
                session_factory,
                checkpointer,
                app.state.circuit_breaker,
                app.state.worker_spawner,
                manager,
                app.state,
            )
        )

        with TestClient(app) as client, client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "connected"
            ws.send_json({"type": "subscribe", "thread_ids": [thread_id]})

            ws.send_json(
                {
                    "type": "send_message",
                    "thread_id": thread_id,
                    "content": "keep going",
                }
            )

            frame = _await_terminal_frame(ws)

    # The wire discriminator must be present and correct, not merely mirrored
    # somewhere in the frame.
    assert frame["type"] == "thread_terminal"
    assert frame["event_type"] == "thread_terminal"
    assert frame["status"] == ThreadStatus.FAILED.value
    # And the domain classifier must agree, reading whichever key it prefers.
    assert is_terminal_event(frame)


def _await_terminal_frame(ws, *, limit: int = 10) -> dict:
    """Read frames until the terminal one arrives, or fail with what did."""
    seen: list[object] = []
    for _ in range(limit):
        frame = ws.receive_json()
        seen.append(frame)
        if wire_event_type(frame) == "thread_terminal":
            return frame
    raise AssertionError(f"no thread_terminal frame arrived; received {seen}")


# ---------------------------------------------------------------------------
# The seam: mirroring is bidirectional, and classification agrees either way
# ---------------------------------------------------------------------------


def test_normalizer_repairs_a_type_only_payload() -> None:
    """A payload naming its type under ``type`` alone leaves carrying both.

    The direction the SSE-side normaliser structurally could not repair: it
    returned early whenever ``type`` was present, so an ``event_type`` reader
    downstream saw an untyped payload.
    """
    normalized = normalize_wire_event_type({"type": "thread_terminal", "status": "ok"})
    assert normalized["type"] == "thread_terminal"
    assert normalized["event_type"] == "thread_terminal"


def test_normalizer_repairs_an_event_type_only_payload() -> None:
    """A payload naming its type under ``event_type`` alone leaves with both."""
    normalized = normalize_wire_event_type({"event_type": "message_chunk"})
    assert normalized["type"] == "message_chunk"
    assert normalized["event_type"] == "message_chunk"


def test_normalizer_leaves_an_untyped_payload_untyped() -> None:
    """A payload naming no type is not stamped with an empty one."""
    normalized = normalize_wire_event_type({"thread_id": "t1"})
    assert "type" not in normalized
    assert "event_type" not in normalized


def test_normalizing_is_idempotent() -> None:
    """Re-normalising an already-mirrored payload changes nothing."""
    once = normalize_wire_event_type({"event_type": "agent_status", "state": "busy"})
    assert normalize_wire_event_type(once) == once


@pytest.mark.parametrize(
    ("event_type", "classifier"),
    [
        ("thread_terminal", None),
        ("permission_request", is_permission_event),
        ("agent_status", is_progress_event),
    ],
)
def test_classifiers_agree_whichever_key_names_the_type(
    event_type: str, classifier
) -> None:
    """The three relay predicates classify a payload identically under either key.

    They previously read different keys - terminal read ``event_type``, the other
    two read ``type`` - so the same event classified differently depending only
    on which producer built it.
    """
    under_type = {"type": event_type, "status": ThreadStatus.FAILED.value}
    under_event_type = {"event_type": event_type, "status": ThreadStatus.FAILED.value}

    if classifier is None:
        assert is_terminal_event(under_type)
        assert is_terminal_event(under_event_type)
    else:
        assert classifier(under_type)
        assert classifier(under_event_type)
