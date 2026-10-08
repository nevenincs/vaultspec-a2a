"""The worker's event client must outlast the gateway's terminal confirmation.

The gateway answers a relayed terminal only after it has confirmed it: a
durable write, then a checkpoint read bounded by the operator's own
``aget_state`` budget. A client that gives up at that same number abandons a
confirmation that is still in progress and re-posts a terminal the gateway is
in the middle of accepting, which is the duplicate this module rules out.

The live case runs a real Uvicorn gateway over loopback and a real
``WorkerBridge`` with its production client, so the budget under test is the
one the worker ships with.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response

from ...domain_config import domain_config
from ...testing import inherited_environment, serve_on_loopback
from ..ipc import WorkerBridge, event_client_timeout

# The worst case the gateway is allowed: a checkpoint read that spends its whole
# bound, plus a durable write before it. Shorter than the client budget derived
# from the same bound, and longer than the flat ten seconds that budget replaced.
_CONFIRMATION_HOLD_SECONDS = domain_config.aget_state_timeout_seconds + 1.0

# Three attempts at the pre-fix ten-second client budget, with their back-off,
# plus room for the accepted post this test expects instead.
_FLUSH_WAIT_SECONDS = 60.0

_TIMEOUT_PROBE = textwrap.dedent(
    """
    import json

    from vaultspec_a2a.domain_config import domain_config
    from vaultspec_a2a.worker.ipc import WorkerBridge

    bridge = WorkerBridge(api_url="http://127.0.0.1:1", worker_id="probe")
    print(
        json.dumps(
            {
                "bound": domain_config.aget_state_timeout_seconds,
                "read": bridge._client.timeout.read,
                "connect": bridge._client.timeout.connect,
            }
        )
    )
    """
)


def _probe_client_budget(*, bound_env: str) -> dict[str, Any]:
    """Build a real bridge in a fresh process with the operator's bound set.

    ``domain_config`` resolves once at import, so the knob only reaches a
    process that has it in the environment before the import runs.
    """
    env = inherited_environment({"VAULTSPEC_A2A_AGET_STATE_TIMEOUT_SECONDS": bound_env})
    result = subprocess.run(
        [sys.executable, "-c", _TIMEOUT_PROBE],
        capture_output=True,
        text=True,
        timeout=60.0,
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"probe failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_event_client_budget_exceeds_the_confirmation_bound() -> None:
    """The client budget the bridge is built with must not expire inside the
    gateway's own bound."""
    budget = event_client_timeout().read
    assert budget is not None
    assert budget > domain_config.aget_state_timeout_seconds, (
        "the worker's event client gives up at or before the gateway's bounded "
        f"terminal confirmation ({budget} vs "
        f"{domain_config.aget_state_timeout_seconds})"
    )


def test_the_event_client_budget_follows_the_operators_confirmation_bound() -> None:
    """Raising the gateway's read bound must raise the client budget with it.

    Two numbers that must stay ordered cannot both be written down; an operator
    who widens the checkpoint read for a slow store would otherwise leave the
    client expiring inside the wider confirmation.
    """
    probe = _probe_client_budget(bound_env="30.0")

    assert probe["bound"] == 30.0, probe
    assert probe["read"] > 30.0, (
        "the event client budget must be derived from the operator's "
        f"aget_state bound, not from a constant beside it: {probe}"
    )
    assert probe["connect"] == 5.0, probe


@pytest.mark.asyncio(loop_scope="function")
async def test_a_terminal_held_for_the_whole_confirmation_is_posted_once() -> None:
    """A gateway that spends its confirmation bound receives one post, not two."""
    posts: list[str] = []
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def _batch(request: Request) -> Response:
        posts.append(request.url.path)
        # Stands in for the confirmation itself: the durable write and the
        # checkpoint read the gateway runs before it answers.
        await asyncio.sleep(_CONFIRMATION_HOLD_SECONDS)
        return Response(content='{"status":"ok"}', media_type="application/json")

    _ = _batch

    async with serve_on_loopback(app, log_level="error") as base:
        bridge = WorkerBridge(api_url=base, worker_id="confirming")
        try:
            await bridge.send_event(
                "held-terminal-run", {"type": "thread_terminal", "status": "completed"}
            )
            # Drive exactly one flush, so the cadence flush and this one cannot
            # both take a slice of the same buffer and confuse the count below.
            deferred = bridge._flush_task
            assert deferred is not None
            deferred.cancel()
            await asyncio.gather(deferred, return_exceptions=True)

            delivered = await asyncio.wait_for(
                bridge.flush_events(), timeout=_FLUSH_WAIT_SECONDS
            )

            assert delivered, (
                "the worker gave up on a terminal the gateway was still confirming"
            )
            assert posts == ["/internal/events/batch"], (
                f"the terminal was posted {len(posts)} times: {posts}"
            )
        finally:
            await bridge.close()
