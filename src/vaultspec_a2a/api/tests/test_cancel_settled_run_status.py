"""Cancelling a run that already settled answers about the RUN, not about an upstream.

Real gateway app on a real socket, real SQLite database and checkpointer, real
in-process dispatch receiver, and - the part that makes this a proof rather than a
rehearsal - the run is driven to its terminal state by relaying a real worker
terminal event over the real ``/internal/events`` relay. Nothing here hand-writes
a status into the database, so the state the cancel is refused against is the
state production actually produces.

The defect these pin was observed live: a cancel issued against a run that had
just failed answered ``502 Bad Gateway``, three times over two sessions. 502 says
the gateway could not reach what it needed - it sends a caller looking at worker
health, transport, and capacity. The truth was that the run had finished
perfectly normally and the verb simply no longer applied to it. The cancel
service's own taxonomy already draws that line, marking a terminal refusal a
DOMAIN rejection and not a dispatch failure; only the HTTP mapping had discarded
it.

Two outcomes are asserted because they are genuinely different requests. A run
that settled some OTHER way - completed, failed - cannot be cancelled and never
will be, so the answer is a conflict the caller resolves by re-reading the run. A
run that is already CANCELLED is the state the caller asked for, and an
idempotent verb must not fail a request purely for being the second one.
"""

from __future__ import annotations

import httpx
import pytest

from ...thread.enums import ThreadStatus
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


def _terminal_envelope(run_id: str, status: str) -> dict:
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


async def _start_run(client: httpx.AsyncClient) -> str:
    resp = await client.post("/v1/runs", json=_run_body())
    assert resp.status_code == 201, resp.text
    return resp.json()["run_id"]


async def _settle(client: httpx.AsyncClient, run_id: str, status: str) -> None:
    """Drive *run_id* terminal through the real worker relay, then confirm it."""
    resp = await client.post(
        "/internal/events", json=_terminal_envelope(run_id, status)
    )
    assert resp.status_code == 200, resp.text
    snapshot = await client.get(f"/v1/runs/{run_id}")
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["status"] == status, (
        f"the relay did not settle {run_id} into {status!r}; the precondition this "
        f"test refuses against was never established: {snapshot.text}"
    )


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    "settled_status", [ThreadStatus.COMPLETED.value, ThreadStatus.FAILED.value]
)
async def test_cancelling_a_settled_run_is_a_conflict_not_a_bad_gateway(
    session_factory, checkpointer, settled_status: str
) -> None:
    """A run that finished refuses the verb on its own state, with 409.

    The negative half is the one that matters and is asserted explicitly: the
    answer must not be 502, because a caller reading 502 goes looking for a
    broken worker that is not broken.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        run_id = await _start_run(client)
        await _settle(client, run_id, settled_status)

        cancel = await client.post(f"/v1/runs/{run_id}/cancel")

        assert cancel.status_code != 502, (
            "a settled run reported as a bad gateway - the caller is told its "
            f"infrastructure failed when its run merely finished: {cancel.text}"
        )
        assert cancel.status_code == 409, cancel.text
        # The refusal names the state, so the caller learns to re-read the run
        # rather than to retry a request that can never succeed.
        assert settled_status in cancel.json()["detail"]


@pytest.mark.asyncio(loop_scope="function")
async def test_cancelling_an_already_cancelled_run_succeeds_idempotently(
    session_factory, checkpointer
) -> None:
    """The second cancel of a cancelled run is satisfied, not refused.

    The caller asked for cancelled and the run is cancelled, so there is nothing
    to report as an error. Answering 409 here would make an idempotent verb fail
    on repetition, which is the shape of a verb that is not idempotent at all.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        run_id = await _start_run(client)

        first = await client.post(f"/v1/runs/{run_id}/cancel")
        assert first.status_code == 200, first.text

        # The worker acknowledges the cancellation; only now is the run CANCELLED
        # rather than merely CANCELLING, which is the state under test.
        await _settle(client, run_id, ThreadStatus.CANCELLED.value)

        second = await client.post(f"/v1/runs/{run_id}/cancel")

        assert second.status_code == 200, second.text
        body = second.json()
        assert body["status"] == ThreadStatus.CANCELLED.value
        # Nothing new was dispatched - the run was already where it was asked to
        # be - and the response says so rather than claiming a fresh cancellation.
        assert body["cancelled"] is False
        assert body["applied"] is True


@pytest.mark.asyncio(loop_scope="function")
async def test_cancelling_an_absent_run_is_still_a_not_found(
    session_factory, checkpointer
) -> None:
    """The narrowing must not disturb the case that was already right.

    404 for an absent run is the established contract the dashboard edge asserts
    against; it is re-checked here so a change to the sibling branch cannot move
    it unnoticed.
    """
    app, _agg, _worker, _cp = make_app(session_factory, checkpointer)
    async with (
        _live_server(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10.0) as client,
    ):
        absent = await client.post("/v1/runs/no-such-run-at-all/cancel")

        assert absent.status_code == 404, absent.text
