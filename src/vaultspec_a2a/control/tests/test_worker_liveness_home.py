"""One owner for the worker-liveness stamp, one vocabulary for its wire kind.

Two properties are held here, and they are the same property seen from the two
sides of the gateway-worker boundary.

The first is convergence: every transport that observes worker contact - the
internal WebSocket accept, a WebSocket heartbeat frame, the HTTP heartbeat
route, and the post-dispatch acknowledgement - lands on ONE record, and every
reader that interprets it - the health projection, the watchdog's staleness
check, and the team-status thread list - reads that same record. The tests drive
the real routers over real transports rather than assigning the fields, because
an assignment would pass just as well against wiring that no longer exists.

The second is that the heartbeat's wire kind is named once. The dispatch arm
that accepts a heartbeat frame is bound to the declared enum member, so a
respelling moves the producer and the consumer together. A dispatch matching a
hand-copied literal would keep matching the old spelling while the producer
followed the declaration, and heartbeats would fall through to the unknown-type
branch - starving exactly the liveness signal the first property protects.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from ...api.internal import internal_router
from ...control.config import settings
from ...control.health import assemble_health_status
from ...control.worker_management import (
    LazyWorkerSpawner,
    WorkerLiveness,
    WorkerState,
    WorkerWatchdog,
    worker_liveness,
)
from ...graph.enums import ServerEventType
from ...testing.ports import free_port
from ...worker.ipc import WorkerBridge
from ..circuit_breaker import WorkerCircuitBreaker


def _gateway_app() -> FastAPI:
    """A real app carrying the internal router and nothing seated by hand."""
    app = FastAPI()
    app.include_router(internal_router)
    # Deliberately NOT seating a liveness record: the accessor is the thing under
    # test, and an app that declares nothing is the case a reader used to have to
    # guess about.
    app.state.aggregator = None
    app.state.db_session_factory = None
    return app


def _watchdog_over(app_state: object) -> WorkerWatchdog:
    """A watchdog reading *app_state*, wired through its real constructor."""
    port = free_port()
    spawner = LazyWorkerSpawner(
        worker_url=f"http://127.0.0.1:{port}", worker_port=port, auto_spawn=False
    )
    breaker = WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30)
    return WorkerWatchdog(spawner, breaker, WorkerState(), app_state)


# ---------------------------------------------------------------------------
# Convergence: the writers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_http_heartbeat_route_records_contact_on_the_one_record() -> None:
    """The HTTP transport writes through the owner, not onto a loose attribute."""
    app = _gateway_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/internal/heartbeat",
            json={
                "type": ServerEventType.HEARTBEAT,
                "worker_id": "w-http",
                "active_threads": ["t-1", "t-2"],
            },
        )

    assert response.status_code == 200
    record = app.state.worker_liveness
    assert isinstance(record, WorkerLiveness)
    assert record.active_threads == ["t-1", "t-2"]
    assert record.is_fresh()


@pytest.mark.asyncio(loop_scope="function")
async def test_real_worker_bridge_heartbeat_crosses_to_the_gateway_record() -> None:
    """The producer's own frame is accepted by the gateway's own dispatch.

    Neither side is restated here: ``WorkerBridge.send_heartbeat`` builds the
    frame and the internal router classifies it, so the two agree about the
    heartbeat's wire kind or this fails. That agreement is the whole point of
    naming the kind once.
    """
    app = _gateway_app()
    bridge = WorkerBridge(api_url="http://test", worker_id="w-bridge")
    bridge.track_thread("t-live")
    await bridge._client.aclose()
    bridge._client = httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    )
    try:
        assert await bridge.send_heartbeat() is True
    finally:
        await bridge._client.aclose()

    record = app.state.worker_liveness
    assert record.active_threads == ["t-live"]
    assert record.is_fresh()


def test_websocket_accept_and_heartbeat_land_on_the_same_record() -> None:
    """Two writers on one transport, one record - not one record each."""
    app = _gateway_app()
    with TestClient(app) as client, client.websocket_connect("/internal/ws") as ws:
        # The accept itself is contact, and claims no thread set.
        at_accept = app.state.worker_liveness
        assert at_accept.is_fresh()
        assert at_accept.active_threads == []

        ws.send_text(
            json.dumps(
                {
                    "type": ServerEventType.HEARTBEAT.value,
                    "active_threads": ["t-ws"],
                }
            )
        )
        # Round-trip an unknown frame to serialise against the handler's own
        # receive loop: once it has answered this, the heartbeat before it has
        # certainly been processed.
        ws.send_text(json.dumps({"type": "not-a-known-kind"}))
        ws.send_text(json.dumps({"type": "not-a-known-kind"}))

    after = app.state.worker_liveness
    assert after is at_accept, "the heartbeat arm seated a second record"
    assert after.active_threads == ["t-ws"]


def test_omitting_the_thread_set_leaves_the_last_known_one_standing() -> None:
    """A writer that observed contact without learning threads must not blank them.

    The socket accept and the post-dispatch acknowledgement both know only that
    the worker answered. Recording an empty list for them would erase a live
    thread set and report the worker as running nothing.
    """
    record = WorkerLiveness()
    record.record_contact(active_threads=["t-a", "t-b"])
    record.record_contact()
    assert record.active_threads == ["t-a", "t-b"]

    record.record_contact(active_threads=[])
    assert record.active_threads == [], "an explicit empty set must still clear"


# ---------------------------------------------------------------------------
# Convergence: the readers
# ---------------------------------------------------------------------------


def test_health_and_watchdog_read_one_record_and_move_together() -> None:
    """The connected verdict and the staleness verdict share one stamp.

    They were two independent copies of the same guard over the same undeclared
    attribute. Held apart, one could accept a value the other rejected; held
    here, a single recorded contact decides both.
    """
    app_state = SimpleNamespace()
    watchdog = _watchdog_over(app_state)

    worker_liveness(app_state).record_contact()
    assert assemble_health_status(app_state=app_state)["worker_connected"] is True
    assert watchdog._heartbeat_stale() is False

    # Age the one stamp past the timeout; both readers must follow it.
    record = worker_liveness(app_state)
    contacted_at = record.last_contact_ts
    assert contacted_at is not None
    record.record_contact(
        when=contacted_at - settings.worker_heartbeat_timeout_seconds - 5.0
    )
    assert assemble_health_status(app_state=app_state)["worker_connected"] is False
    assert watchdog._heartbeat_stale() is True


def test_a_worker_never_heard_from_is_not_stale_and_not_connected() -> None:
    """The asymmetry the two predicates must keep.

    ``is_fresh`` and ``is_stale`` are not complements. Reporting a worker that
    has never checked in as STALE would hand the watchdog a crash signal for a
    worker that has simply not finished starting; reporting it as CONNECTED
    would claim a liveness nobody observed.
    """
    app_state = SimpleNamespace()
    watchdog = _watchdog_over(app_state)

    assert assemble_health_status(app_state=app_state)["worker_connected"] is False
    assert watchdog._heartbeat_stale() is False
    assert worker_liveness(app_state).age_seconds() is None


@pytest.mark.parametrize("degenerate", [float("nan"), float("inf"), True])
def test_a_degenerate_stamp_reads_as_no_contact_for_both_readers(
    degenerate: float,
) -> None:
    """The validity guard survived the move, and survived it once rather than twice.

    ``app.state`` remains an untyped attribute bag an embedding host can seat
    anything on. A value that is not a finite real number must read as no contact
    at all, and must read that way for BOTH predicates - a stamp one reader calls
    fresh while the other calls it stale is the disagreement this home exists to
    make impossible.
    """
    record = WorkerLiveness(last_contact_ts=degenerate)
    assert record.age_seconds() is None
    assert record.is_fresh() is False
    assert record.is_stale() is False


def test_the_accessor_seats_a_record_rather_than_reporting_absence() -> None:
    """An app that declares nothing gets a record saying 'never heard from'.

    A reader used to receive ``None`` here and had to decide for itself what an
    absent attribute meant. It now receives the same answer in the vocabulary of
    the domain, and receives the SAME object on every call, so a writer reached
    through the accessor is visible to a reader reached through it.
    """
    app_state = SimpleNamespace()
    first = worker_liveness(app_state)
    assert isinstance(first, WorkerLiveness)
    assert first.last_contact_ts is None

    first.record_contact()
    assert worker_liveness(app_state) is first
    assert app_state.worker_liveness is first


# ---------------------------------------------------------------------------
# One vocabulary for the heartbeat's wire kind
# ---------------------------------------------------------------------------


def test_the_ws_dispatch_is_bound_to_the_declared_heartbeat_value() -> None:
    """The heartbeat arm matches the declaration, and matches nothing else.

    The trap is asserted live before it is exercised: a near-miss spelling must
    reach the unknown-type branch and record no contact. Without that half, a
    heartbeat accepted for any reason at all would pass this test, including a
    dispatch that had stopped discriminating.
    """
    app = _gateway_app()
    near_miss = ServerEventType.HEARTBEAT.value + "s"
    assert near_miss != ServerEventType.HEARTBEAT.value

    with TestClient(app) as client, client.websocket_connect("/internal/ws") as ws:
        record = app.state.worker_liveness
        aged_out = settings.worker_heartbeat_timeout_seconds + 5.0
        record.record_contact(when=record.last_contact_ts - aged_out)
        stale_stamp = record.last_contact_ts

        ws.send_text(json.dumps({"type": near_miss, "active_threads": ["t-ghost"]}))
        ws.send_text(json.dumps({"type": near_miss}))
        assert record.last_contact_ts == stale_stamp, (
            "a frame that is not the declared heartbeat kind recorded contact"
        )
        assert record.active_threads == []

        ws.send_text(
            json.dumps(
                {
                    "type": ServerEventType.HEARTBEAT.value,
                    "active_threads": ["t-real"],
                }
            )
        )
        ws.send_text(json.dumps({"type": near_miss}))

    assert record.last_contact_ts > stale_stamp
    assert record.active_threads == ["t-real"]


def test_a_real_heartbeat_reaches_the_wire_with_its_fields_intact() -> None:
    """The acceptance bar for the catalog conversion: CONTENT, not the key.

    The per-event catalog is an ALLOWLIST, and an allowlist is invisible to the
    type system. Its contract is projection by omission, never refusal: a frame
    whose kind misses the catalog is rebuilt from the always-safe identity keys
    and emitted anyway. So a lookup that stopped matching would raise nothing,
    fail no type check, and still satisfy any test asserting only that a frame of
    this kind appeared - it would simply arrive materially empty.

    The negative control runs FIRST so the allowlist is proven live before the
    positive case leans on it. A catalog that passed everything through would
    otherwise satisfy the survival assertion while enforcing nothing.
    """
    from ...api.schemas.events import HeartbeatEvent
    from ...streaming.sse_frames import encode_sse_frame, enforce_progress_allowlist

    uncatalogued = enforce_progress_allowlist(
        {"type": "definitely_not_catalogued", "server_uptime_seconds": 99.5}
    )
    assert "server_uptime_seconds" not in uncatalogued, (
        "the allowlist is not enforcing; the survival assertion below proves nothing"
    )

    # A StrEnum member hashes as its VALUE (str wins the MRO), so the catalog
    # matches whichever side the lookup arrives on. Asserted rather than assumed:
    # Enum.__hash__ hashes the member NAME, and inheriting that instead would
    # strand every converted key silently.
    for probe in (ServerEventType.HEARTBEAT.value, ServerEventType.HEARTBEAT):
        projected = enforce_progress_allowlist(
            {"type": probe, "server_uptime_seconds": 99.5}
        )
        assert projected.get("server_uptime_seconds") == 99.5, (
            f"catalog lookup missed for {probe!r} - frame would arrive empty"
        )

    # The real producer's own frame, through the real encode boundary.
    heartbeat = HeartbeatEvent(
        timestamp=datetime.now(UTC),
        server_uptime_seconds=42.5,
    )
    raw = encode_sse_frame(
        heartbeat.model_dump(mode="json"),
        event=ServerEventType.HEARTBEAT,
        thread_id="t-probe",
    )
    text = raw.decode("utf-8")
    decoded = json.loads(
        "".join(
            line.removeprefix("data: ")
            for line in text.splitlines()
            if line.startswith("data: ")
        )
    )
    assert decoded["server_uptime_seconds"] == 42.5
    assert decoded["type"] == ServerEventType.HEARTBEAT.value


def test_no_declared_event_kind_is_catalogued_under_a_hand_copied_literal() -> None:
    """No catalog entry is left stranded behind a respelling of its declaration."""
    from ...streaming.sse_frames import _PROGRESS_CATALOG

    assert ServerEventType.HEARTBEAT in _PROGRESS_CATALOG
    declared = set(ServerEventType)
    for key in _PROGRESS_CATALOG:
        if key in declared:
            assert isinstance(key, ServerEventType), (
                f"{key!r} is a declared event kind keyed by a hand-copied literal"
            )


@pytest.mark.parametrize("key", ["type", "event_type"])
@pytest.mark.asyncio(loop_scope="function")
async def test_the_shared_frame_reader_skips_heartbeats_under_either_wire_key(
    key: str,
) -> None:
    """The reader reads the frame kind through the owner of the mirrored pair.

    ``type`` and ``event_type`` are mirrored on purpose and producers write
    either. A reader consulting one key directly classifies a payload written
    under the other as untyped - which means it neither skips the keep-alive it
    was asked to skip nor recognises the frame it was asked to wait for.
    """
    from ...testing.sse import read_frame

    frames = [
        json.dumps({key: ServerEventType.HEARTBEAT.value, "server_uptime_seconds": 1}),
        json.dumps({key: "agent_status", "state": "working"}),
    ]

    async def _lines():
        for frame in frames:
            yield f"data: {frame}"
            yield ""

    payload, _raw = await read_frame(_lines(), wanted="agent_status", timeout=2.0)
    assert payload["state"] == "working", "the heartbeat keep-alive was not skipped"
