"""Live proof that run admission is gated by the drain gate at the gateway.

Real gateway app on a real socket, real SQLite DB and checkpointer, real
in-process dispatch receiver (established api-test precedent - not a mock). Proves
the wiring is LIVE: closing the shared ``app.state`` drain gate refuses a new run
with 503 before any dispatch, while cancellation stays available so a drain can
still quiesce.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...control.drain import DrainGate
from ...database import get_thread
from ...thread.enums import TERMINAL_STATUSES, ThreadStatus
from ..dependencies import LIFECYCLE_CAPABILITY_HEADER
from ..websocket import ConnectionManager
from ..ws_dispatch import create_dispatch_message_handler
from .conftest import make_app
from .test_gateway_live import _live_server

_PRESET = "mock-success-single"

# Closed port: the IANA discard service is not listening on the loopback test
# host, so a dispatch POST to it is refused by the real transport. The repo's
# established way to produce a genuine unreachable worker without a mock.
_UNREACHABLE_WORKER = "http://127.0.0.1:9"


def _run_body() -> dict:
    return {
        "team_preset": _PRESET,
        "message": "build it",
        "autonomous": True,
        "actor_tokens": {"tokens": {"coder": "tok-coder"}, "engine_bearer": "bearer"},
    }


def _terminal_envelope(run_id: str, status: str = "completed") -> dict:
    """The worker-IPC envelope carrying one run's terminal event."""
    return {
        "type": "event",
        "thread_id": run_id,
        "payload": {
            "type": "thread_terminal",
            "event_type": "thread_terminal",
            "thread_id": run_id,
            "status": status,
        },
    }


async def _relay_terminal(client: httpx.AsyncClient, run_id: str) -> None:
    """Deliver a run's terminal event over the real worker relay endpoint."""
    resp = await client.post("/internal/events", json=_terminal_envelope(run_id))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio(loop_scope="function")
async def test_run_start_admits_while_open_then_refuses_once_draining(
    session_factory, checkpointer
) -> None:
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        # Open gate: the run is admitted and dispatched.
        first = await client.post("/v1/runs", json=_run_body())
        assert first.status_code == 201, first.text
        run_id = first.json()["run_id"]
        assert worker.dispatches, "an admitted run must dispatch to the worker"
        dispatched = len(worker.dispatches)

        # The route created the shared gate on app.state; it now tracks the run.
        gate = app.state.drain_gate
        assert isinstance(gate, DrainGate)
        assert gate.is_active(run_id)

        # Close admission: a new run is refused with 503 before any new dispatch.
        await gate.close_admission()
        refused = await client.post("/v1/runs", json=_run_body())
        assert refused.status_code == 503, refused.text
        assert len(worker.dispatches) == dispatched, (
            "a refused run must not reach the worker"
        )

        # Cancellation is never admission-gated: it stays available while draining
        # so the drain can settle the in-flight run.
        cancel = await client.post(f"/v1/runs/{run_id}/cancel")
        assert cancel.status_code == 200, cancel.text


@pytest.mark.asyncio(loop_scope="function")
async def test_admin_stop_closes_admission_and_refuses_new_runs(
    session_factory, checkpointer
) -> None:
    """The administrative stop path engages the drain gate.

    An authenticated, receipt-owned ``/admin/shutdown`` closes run admission
    before it initiates the (deferred) process stop, so a run-start issued after
    it is refused 503 while the gateway is still up. Driven in-process over ASGI:
    the deferred self-SIGINT is scheduled on the test loop and discarded when the
    loop closes, so it never stops the test runner.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    capability = "ownership-capability-drain-0011223344556677"
    app.state.lifecycle_capability = capability
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://desktop.test"
    ) as client:
        # Admission open: a run starts and dispatches.
        first = await client.post("/v1/runs", json=_run_body())
        assert first.status_code == 201, first.text
        dispatched = len(worker.dispatches)

        # Receipt-owned administrative stop closes admission.
        stop = await client.post(
            "/admin/shutdown",
            headers={LIFECYCLE_CAPABILITY_HEADER: capability},
        )
        assert stop.status_code == 202, stop.text

        # A new run is now refused before any dispatch.
        refused = await client.post("/v1/runs", json=_run_body())
        assert refused.status_code == 503, refused.text
        assert len(worker.dispatches) == dispatched, (
            "a run refused after admin stop must not reach the worker"
        )


@pytest.mark.asyncio(loop_scope="function")
async def test_unexpected_run_start_failure_releases_admission_and_drain_quiesces(
    tmp_path, checkpointer
) -> None:
    """An unexpected run-start failure releases the admission so drain can quiesce.

    A real, schemaless database - the ``threads`` table is never created - makes
    the run-start INSERT raise a genuine ``OperationalError`` inside
    ``create_and_dispatch_thread``: an unexpected failure that is neither a nickname
    conflict nor an integrity race, occurring after the run was admitted to the
    drain gate but before any durable run exists. No mock, monkeypatch, or fake is
    used. Without the release-on-every-failure guard this would leave a phantom
    active run that makes ``drain()`` hang forever.
    """
    db_file = tmp_path / "schemaless.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        app, _agg, worker, _cp = make_app(factory, checkpointer)
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        ):
            resp = await client.post("/v1/runs", json=_run_body())
            # The unexpected DB failure surfaces as a 500 and never dispatched.
            assert resp.status_code == 500, resp.text
            assert not worker.dispatches, "a failed create must not dispatch"

            # The admission was released on the failure path: no phantom active run.
            gate = app.state.drain_gate
            assert isinstance(gate, DrainGate)
            assert gate.active_run_count == 0

            # A drain now quiesces at once instead of hanging on a phantom run.
            result = await gate.drain(timeout=1.0)
            assert result.quiescent and result.active_runs == 0, result
    finally:
        await engine.dispose()


@pytest.mark.asyncio(loop_scope="function")
async def test_client_run_id_replay_does_not_double_count_admission(
    session_factory, checkpointer
) -> None:
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        body = {**_run_body(), "run_id": "run-drain-replay"}
        first = await client.post("/v1/runs", json=body)
        assert first.status_code == 201, first.text
        # A dispatch-exactly-once retry returns the same run without re-admitting.
        second = await client.post("/v1/runs", json=body)
        assert second.status_code == 201, second.text
        assert second.json()["run_id"] == first.json()["run_id"]
        gate = app.state.drain_gate
        assert gate.active_run_count == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_normal_completion_releases_admission_and_drain_quiesces(
    session_factory, checkpointer
) -> None:
    """A run that starts and completes normally leaves the drain gate's active set.

    The whole seam, live: a real gateway on a real socket starts and dispatches a
    run through the real run-start verb, then the worker's terminal event arrives
    over the real ``/internal/events`` relay endpoint and travels the production
    path (endpoint -> ``_relay_single_event`` -> ``relay_event`` ->
    ``_handle_terminal_event``). Real SQLite for the durable status write, real
    in-process dispatch receiver, no mock or monkeypatch anywhere.

    This is the invariant a drain depends on: without the terminal release the
    run stays active for the life of the process and the gate can never quiesce.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        started = await client.post("/v1/runs", json=_run_body())
        assert started.status_code == 201, started.text
        run_id = started.json()["run_id"]
        assert worker.dispatches, "an admitted run must dispatch to the worker"

        gate = app.state.drain_gate
        assert isinstance(gate, DrainGate)
        assert gate.is_active(run_id)

        # While the run is live a drain genuinely cannot quiesce; this is the
        # state a leaked admission would leave behind permanently.
        busy = await gate.wait_quiescent(timeout=0.2)
        assert not busy.quiescent, busy
        assert busy.active_runs == 1, busy

        await _relay_terminal(client, run_id)

        # The run left the active set on its terminal event.
        assert not gate.is_active(run_id)
        assert gate.active_run_count == 0

        # ...and the terminal status really was persisted, so the release is not
        # standing in for a relay that silently did nothing.
        async with session_factory() as db:
            thread = await get_thread(db, run_id)
        assert thread is not None
        assert thread.status == ThreadStatus.COMPLETED.value

        # A drain now quiesces instead of hanging forever on a completed run.
        result = await gate.drain(timeout=1.0)
        assert result.quiescent and result.active_runs == 0, result


@pytest.mark.asyncio(loop_scope="function")
async def test_dispatch_failure_that_marks_run_failed_releases_admission(
    session_factory, checkpointer
) -> None:
    """A start-path dispatch failure that settles the run FAILED releases it.

    The worker client points at a closed loopback port, so ``safe_dispatch``
    takes a real transport refusal - not a simulated one - and the dispatch
    policy marks the durable run FAILED. That run is terminal and no worker ever
    ran it, so no terminal event will ever arrive: unless the start path releases
    it, the admission leaks for the life of the process.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    run_id = "run-drain-dispatch-failure"
    async with httpx.AsyncClient(
        base_url=_UNREACHABLE_WORKER, timeout=2.0
    ) as unreachable:
        app.state.worker_client = unreachable
        async with (
            _live_server(app) as base,
            httpx.AsyncClient(base_url=base, timeout=10.0) as client,
        ):
            resp = await client.post("/v1/runs", json={**_run_body(), "run_id": run_id})
            assert resp.status_code == 502, resp.text

            # The run is durable and terminal: the failure is real, not a refusal
            # before any durable state existed.
            async with session_factory() as db:
                thread = await get_thread(db, run_id)
            assert thread is not None
            assert thread.status == ThreadStatus.FAILED.value

            gate = app.state.drain_gate
            assert isinstance(gate, DrainGate)
            assert not gate.is_active(run_id)
            assert gate.active_run_count == 0

            result = await gate.drain(timeout=1.0)
            assert result.quiescent and result.active_runs == 0, result


@pytest.mark.asyncio(loop_scope="function")
async def test_followup_dispatch_failure_that_marks_run_failed_releases_admission(
    session_factory, checkpointer
) -> None:
    """A follow-up dispatch failure that settles the run FAILED releases it.

    The run starts and dispatches normally against the in-process worker, then
    the worker client is swapped for one pointed at a closed loopback port, so
    the follow-up message takes a real transport refusal and the message service
    marks the thread FAILED. That is a terminal run whose worker never received
    the follow-up, so no terminal event follows it: the messages route is the
    only site that can release its admission.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "run-drain-followup-failure"
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        started = await client.post("/v1/runs", json={**_run_body(), "run_id": run_id})
        assert started.status_code == 201, started.text
        assert worker.dispatches

        gate = app.state.drain_gate
        assert isinstance(gate, DrainGate)
        assert gate.is_active(run_id)

        async with httpx.AsyncClient(
            base_url=_UNREACHABLE_WORKER, timeout=2.0
        ) as unreachable:
            app.state.worker_client = unreachable
            followup = await client.post(
                f"/api/threads/{run_id}/messages",
                json={"content": "keep going"},
            )
            assert followup.status_code == 502, followup.text

        async with session_factory() as db:
            thread = await get_thread(db, run_id)
        assert thread is not None
        assert thread.status == ThreadStatus.FAILED.value

        assert not gate.is_active(run_id)
        result = await gate.drain(timeout=1.0)
        assert result.quiescent and result.active_runs == 0, result


@pytest.mark.asyncio(loop_scope="function")
async def test_ws_followup_dispatch_failure_releases_admission(
    session_factory, checkpointer
) -> None:
    """The WS follow-up path releases a run its dispatch failure settled FAILED.

    The WS handler marks the thread FAILED and broadcasts the terminal frame
    straight to its clients - that broadcast never travels the relay handler that
    releases - so the handler itself is the only site that can free the
    admission. Driven through the real handler the production lifespan installs,
    over a real ``ConnectionManager`` and a real transport refusal.
    """
    app, agg, worker, _cp = make_app(session_factory, checkpointer)
    run_id = "run-drain-ws-followup-failure"
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        started = await client.post("/v1/runs", json={**_run_body(), "run_id": run_id})
        assert started.status_code == 201, started.text
        assert worker.dispatches

        gate = app.state.drain_gate
        assert isinstance(gate, DrainGate)
        assert gate.is_active(run_id)

    async with httpx.AsyncClient(
        base_url=_UNREACHABLE_WORKER, timeout=2.0
    ) as unreachable:
        handler = create_dispatch_message_handler(
            unreachable,
            session_factory,
            checkpointer,
            app.state.circuit_breaker,
            app.state.worker_spawner,
            ConnectionManager(agg),
            app.state,
        )
        await handler(run_id, "keep going", None)

    async with session_factory() as db:
        thread = await get_thread(db, run_id)
    assert thread is not None
    assert thread.status == ThreadStatus.FAILED.value

    assert not gate.is_active(run_id)
    result = await gate.drain(timeout=1.0)
    assert result.quiescent and result.active_runs == 0, result


@pytest.mark.asyncio(loop_scope="function")
async def test_cancel_and_terminal_events_for_one_run_do_not_corrupt_the_set(
    session_factory, checkpointer
) -> None:
    """Cancel plus repeated terminal events drop exactly the runs they name.

    Two shapes, both over real HTTP against one live gateway, with a third run
    kept live throughout so every assertion on the set is exact:

    - A cancelled run reaches CANCELLING, not a terminal status, so the cancel
      verb deliberately leaves it in the active set; its worker terminal event is
      what releases it. That is the designed hand-off, and the run must not
      vanish from the set early.
    - A repeated terminal event for one run releases twice. The second delivery
      takes the ``InvalidTransitionError`` branch - the run is already terminal -
      and must still leave the set consistent. This is the reachable double
      release in production: the worker bridge batches and retries.

    A reference count would have decremented the repeated run twice here and
    taken the surviving run's accounting down with it; the idempotent discard
    absorbs it with no coordination.
    """
    app, _agg, worker, _cp = make_app(session_factory, checkpointer)
    cancelled_run = "run-drain-cancelled"
    repeated_run = "run-drain-repeated"
    survivor = "run-drain-survivor"
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        for run_id in (cancelled_run, repeated_run, survivor):
            started = await client.post(
                "/v1/runs", json={**_run_body(), "run_id": run_id}
            )
            assert started.status_code == 201, started.text
        assert len(worker.dispatches) == 3

        gate = app.state.drain_gate
        assert isinstance(gate, DrainGate)
        assert gate.active_run_count == 3

        # A cancel that only reaches CANCELLING keeps its admission: the run is
        # still executing until its worker says otherwise.
        cancelled = await client.post(f"/v1/runs/{cancelled_run}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] not in TERMINAL_STATUSES
        assert gate.is_active(cancelled_run)
        assert gate.active_run_count == 3

        # Its terminal event then releases it - and only it.
        await _relay_terminal(client, cancelled_run)
        assert not gate.is_active(cancelled_run)
        assert gate.active_run_count == 2

        # A repeated terminal event releases the same run twice; the second
        # delivery takes the already-terminal branch.
        await _relay_terminal(client, repeated_run)
        assert not gate.is_active(repeated_run)
        await _relay_terminal(client, repeated_run)
        assert not gate.is_active(repeated_run)

        # Exactly the two settled runs left; the survivor's accounting is intact.
        assert gate.is_active(survivor)
        assert gate.active_run_count == 1

        # The surviving run still holds the drain open - the repeated release did
        # not empty the set behind it.
        not_yet = await gate.wait_quiescent(timeout=0.2)
        assert not not_yet.quiescent, not_yet
        assert not_yet.active_runs == 1, not_yet

        await _relay_terminal(client, survivor)
        result = await gate.drain(timeout=1.0)
        assert result.quiescent and result.active_runs == 0, result
