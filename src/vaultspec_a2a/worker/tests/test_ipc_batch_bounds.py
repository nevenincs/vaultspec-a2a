"""The event bridge must not build a post the gateway will refuse.

Three of these drive the bridge against the REAL gateway route, so the size limit
under test is the one that ships rather than a number restated here; the limit is
lowered through the setting BOTH sides read, which is what makes one home for it
worth having. The fourth uses a small real ASGI service that can be held
mid-request, because what it observes is overlap between two flushes and no
production route can be asked to pause.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from httpx import ASGITransport

from ...api.internal import internal_router
from ...control.config import settings
from ...streaming.aggregator import EventAggregator
from ...testing.environment import settings_override
from ..ipc import WorkerBridge

# Small enough to reach the batch boundary with a handful of events, and applied
# to the setting the gateway enforces and the worker measures against, so both
# sides move together.
_SMALL_BODY_LIMIT = 4096


def _gateway_app() -> FastAPI:
    """Mount the production internal relay route on a real application.

    The route itself is the gateway's own, so the batch limit it enforces is the
    shipped one. It is given a real event aggregator and told explicitly that it
    has no database, which is the declared shape for a host that relays progress
    without persisting it - and progress is all these events are.
    """
    app = FastAPI()
    app.include_router(internal_router)
    app.state.aggregator = EventAggregator()
    app.state.db_session_factory = None
    app.state.checkpointer = None
    return app


def _bridge_to(app: FastAPI) -> WorkerBridge:
    """Point a real bridge at a real ASGI application."""
    bridge = WorkerBridge(api_url="http://control:8000", worker_id="ipc-bounds")
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://control:8000"
    )
    return bridge


def _progress(index: int, *, size: int) -> dict[str, Any]:
    return {
        "event_type": "message_chunk",
        "thread_id": "run-bounds",
        "message_id": f"m-{index}",
        "content": "x" * size,
    }


def _terminal() -> dict[str, Any]:
    return {
        "event_type": "thread_terminal",
        "thread_id": "run-bounds",
        "status": "completed",
    }


class _SizeRecordingGateway:
    """A real gateway app that records the body size of every batch it accepts."""

    def __init__(self) -> None:
        self.body_sizes: list[int] = []
        self.events: list[dict[str, Any]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.gate: asyncio.Event | None = None

        app = FastAPI()
        recorder = self

        @app.post("/internal/events/batch")
        async def _batch(request: Request) -> Response:
            recorder.in_flight += 1
            recorder.max_in_flight = max(recorder.max_in_flight, recorder.in_flight)
            try:
                raw = await request.body()
                if recorder.gate is not None:
                    await recorder.gate.wait()
                recorder.body_sizes.append(len(raw))
                body: dict[str, Any] = await request.json()
                recorder.events.extend(body["events"])
                return Response(
                    content='{"status":"ok"}', media_type="application/json"
                )
            finally:
                recorder.in_flight -= 1

        _ = _batch
        self.app = app


@pytest.mark.asyncio
async def test_a_backlog_is_split_into_batches_the_gateway_accepts() -> None:
    """A buffer larger than one body is delivered, not refused whole.

    The whole buffer used to go out as a single post. A backlog built while the
    gateway was away therefore arrived over the limit, was refused, and was
    re-queued unchanged - so it was refused again, indefinitely. It is now cut
    into bodies that fit, in order, and the real route accepts every one.
    """
    with settings_override(internal_max_http_body_bytes=_SMALL_BODY_LIMIT):
        limit = settings.internal_max_event_batch_bytes
        bridge = _bridge_to(_gateway_app())
        try:
            for index in range(24):
                await bridge.send_event("run-bounds", _progress(index, size=1024))
            assert await bridge.flush_events() is True
        finally:
            await bridge.close()

    # Nothing is left behind, and the buffer really did need splitting.
    assert bridge._event_buffer == []
    assert limit == _SMALL_BODY_LIMIT * settings.internal_event_batch_body_multiplier


@pytest.mark.asyncio
async def test_every_posted_body_stays_under_the_limit_and_carries_every_event() -> (
    None
):
    """The bodies are measured, and the split loses and duplicates nothing.

    Driven against a recording gateway rather than the production route because
    the property is about the bodies the worker BUILDS: the route can only say
    whether it liked them.
    """
    gateway = _SizeRecordingGateway()
    with settings_override(internal_max_http_body_bytes=_SMALL_BODY_LIMIT):
        limit = settings.internal_max_event_batch_bytes
        bridge = _bridge_to(gateway.app)
        try:
            for index in range(24):
                await bridge.send_event("run-bounds", _progress(index, size=1024))
            assert await bridge.flush_events() is True
        finally:
            await bridge.close()

    assert len(gateway.body_sizes) > 1, "the backlog was small enough not to split"
    assert all(size <= limit for size in gateway.body_sizes), gateway.body_sizes
    ids = [event["payload"]["message_id"] for event in gateway.events]
    assert ids == [f"m-{index}" for index in range(24)]


@pytest.mark.asyncio
async def test_an_event_too_large_to_relay_is_reported_and_stops_blocking_the_rest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An event no body can carry must not hold the queue behind it forever.

    No number of retries can make it fit, so retrying it is an outage rather than
    resilience. It is dropped, loudly - the loss is real and is recorded as one -
    and the events behind it go through.
    """
    with (
        settings_override(internal_max_http_body_bytes=_SMALL_BODY_LIMIT),
        caplog.at_level(logging.ERROR, logger="vaultspec_a2a.worker.ipc"),
    ):
        limit = settings.internal_max_event_batch_bytes
        bridge = _bridge_to(_gateway_app())
        try:
            await bridge.send_event("run-bounds", _progress(0, size=limit * 2))
            await bridge.send_event("run-bounds", _progress(1, size=64))
            assert await bridge.flush_events() is False
        finally:
            await bridge.close()

    assert bridge._event_buffer == [], "the undeliverable event still blocks the queue"
    undeliverable = [
        record
        for record in caplog.records
        if getattr(record, "action", None) == "flush_events_undeliverable"
    ]
    assert len(undeliverable) == 1
    assert getattr(undeliverable[0], "dropped_event_type", None) == "message_chunk"


@pytest.mark.asyncio
async def test_a_full_buffer_gives_up_progress_before_an_outcome() -> None:
    """Drop-oldest must not evict the one event that ends the run.

    A terminal is stated once and nothing restates it, so a lost one leaves the
    gateway watching a run that never ends - and the flood of progress that
    precedes a terminal is exactly what used to push it out of a full buffer.
    """
    gateway = _SizeRecordingGateway()
    with settings_override(ipc_max_event_buffer=4):
        bridge = _bridge_to(gateway.app)
        try:
            for index in range(3):
                await bridge.send_event("run-bounds", _progress(index, size=32))
            await bridge.send_event("run-bounds", _terminal())
            # Enough further progress to have evicted the terminal under a policy
            # that takes the head whatever it is.
            for index in range(3, 7):
                await bridge.send_event("run-bounds", _progress(index, size=32))

            buffered = [
                entry["payload"].get("event_type") for entry in bridge._event_buffer
            ]
            assert "thread_terminal" in buffered, buffered
            assert await bridge.flush_events() is True
        finally:
            await bridge.close()

    relayed = [event["payload"].get("event_type") for event in gateway.events]
    assert relayed.count("thread_terminal") == 1, relayed


@pytest.mark.asyncio
async def test_two_flushes_never_overlap_on_the_wire() -> None:
    """The cadence flush and a terminal's immediate flush take turns.

    They used to share no lock, so both could hold a slice of one buffer at once:
    the gateway then had two posts in flight whose relative order nothing
    established, and a failure in either re-queued events the other had already
    delivered. The gateway is held mid-request here so the overlap, if there were
    one, would be unmissable.
    """
    gateway = _SizeRecordingGateway()
    gateway.gate = asyncio.Event()
    bridge = _bridge_to(gateway.app)
    try:
        await bridge.send_event("run-bounds", _progress(0, size=32))
        first = asyncio.create_task(bridge.flush_events())
        while gateway.in_flight == 0:
            await asyncio.sleep(0)

        await bridge.send_event("run-bounds", _terminal())
        second = asyncio.create_task(bridge.flush_events())
        # Give the second flush every chance to race the first one.
        for _ in range(20):
            await asyncio.sleep(0)
        assert gateway.in_flight == 1

        gateway.gate.set()
        assert await first is True
        assert await second is True
    finally:
        await bridge.close()

    assert gateway.max_in_flight == 1
    relayed = [event["payload"].get("event_type") for event in gateway.events]
    assert relayed == ["message_chunk", "thread_terminal"]
