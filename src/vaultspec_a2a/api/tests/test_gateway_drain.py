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

from ...control.drain import DrainGate
from ..dependencies import LIFECYCLE_CAPABILITY_HEADER
from .conftest import make_app
from .test_gateway_live import _live_server

_PRESET = "mock-success-single"


def _run_body() -> dict:
    return {
        "team_preset": _PRESET,
        "message": "build it",
        "autonomous": True,
        "actor_tokens": {"tokens": {"coder": "tok-coder"}, "engine_bearer": "bearer"},
    }


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

    An authenticated, receipt-owned ``/api/admin/shutdown`` closes run admission
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
            "/api/admin/shutdown",
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
