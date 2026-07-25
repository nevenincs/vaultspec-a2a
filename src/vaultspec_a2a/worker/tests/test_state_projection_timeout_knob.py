"""``emit_execution_state_projection`` must honour the operator's timeout knob.

``StateProjector`` was extracted from ``Executor`` but its ``aget_state`` call
kept a hardcoded ``timeout=10.0`` instead of reading
``domain_config.aget_state_timeout_seconds`` -- the same knob ``Executor``
and ``streaming/transformer.py`` already honour, settable via the
``VAULTSPEC_AGET_STATE_TIMEOUT_SECONDS`` env var. The two call sites read the
same numeric default today, so nothing looked broken; an operator who raised
the knob to fix a slow checkpointer would see the executor's own read obey and
this sibling keep timing out at the stale 10.0.

``domain_config`` is a module-level singleton resolved once at import
(``vaultspec_a2a/domain_config.py``), so the env var only takes effect for a
process that has it set *before* importing the module -- setting
``os.environ`` mid-process does not reach an already-constructed singleton.
This drives the probe in a fresh subprocess with the env var pre-set, the
same recipe ``providers/tests/test_codex_turn_idle_timeout.py`` uses for the
identical "settings load once at import" shape.

The probe's graph is a minimal ``StreamableGraph``-protocol stub whose
``aget_state`` sleeps a controlled duration. Policy exception mirroring
``streaming/tests/test_aggregator.py``'s ``_SilentGraph``: a full compiled
LangGraph graph cannot guarantee a deterministic checkpoint-read latency, and
that latency -- not graph compilation -- is exactly what this test needs to
control. Everything downstream of the stubbed boundary (``StateProjector``,
``WorkerBridge``, the real ASGI gateway, ``asyncio.wait_for`` wiring) is real,
unmodified production code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from typing import Any

_PROBE = textwrap.dedent(
    """
    import asyncio
    import json
    import sys
    import time

    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import Response
    from httpx import ASGITransport
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from vaultspec_a2a.streaming.types import StreamableGraph
    from vaultspec_a2a.worker.ipc import WorkerBridge
    from vaultspec_a2a.worker.state_projection import StateProjector

    SLEEP_SECONDS = float(sys.argv[1])


    class _DelayedGraph:
        \"\"\"Minimal StreamableGraph stub: aget_state sleeps a controlled duration.

        See the module docstring's Policy exception note.
        \"\"\"

        async def astream_events(self, graph_input, config, *, version):
            return
            yield  # pragma: no cover -- makes this an async generator

        async def aget_state(self, config):
            await asyncio.sleep(SLEEP_SECONDS)
            return object()


    assert issubclass(_DelayedGraph, StreamableGraph)  # protocol drift guard


    def _make_bridge(api_url, worker_id):
        app = FastAPI()
        received = []

        @app.post("/internal/events/batch")
        async def _batch(request: Request) -> Response:
            received.append(await request.json())
            return Response(content='{"status":"ok"}', media_type="application/json")

        bridge = WorkerBridge(api_url=api_url, worker_id=worker_id)
        bridge._client = httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url=api_url,
        )
        return bridge, received


    async def main() -> dict:
        async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
            await cp.setup()
            bridge, received = _make_bridge("http://control:8000", "probe-worker")
            projector = StateProjector(checkpointer=cp, bridge=bridge)
            start = time.monotonic()
            try:
                await projector.emit_execution_state_projection(
                    "thread-probe",
                    _DelayedGraph(),
                    {"configurable": {"thread_id": "thread-probe"}},
                )
                await bridge.flush_events()
                elapsed = time.monotonic() - start
            finally:
                await bridge.close()

        assert len(received) == 1, received
        events = received[0]["events"]
        assert len(events) == 1, events
        payload = events[0]["payload"]
        return {
            "elapsed": elapsed,
            "degraded_reasons": payload.get("degraded_reasons") or [],
        }


    print(json.dumps(asyncio.run(main())))
    """
)


def _run_probe(*, timeout_env: str, sleep_seconds: float) -> dict[str, Any]:
    """Run the probe in a fresh process with the timeout knob set in the env."""
    env = os.environ.copy()
    env["VAULTSPEC_AGET_STATE_TIMEOUT_SECONDS"] = timeout_env
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, str(sleep_seconds)],
        capture_output=True,
        text=True,
        timeout=30.0,
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"probe failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_state_projection_honors_the_operator_configured_aget_state_timeout() -> None:
    """A short operator knob must cut off ``aget_state`` well inside the sleep.

    The graph's ``aget_state`` sleeps 1.0s -- well inside the sibling module's
    stale hardcoded 10.0s default (which would let it finish and emit a full,
    non-degraded payload) but well past a 0.15s operator-configured knob
    (which must abort it early and emit the degraded
    ``"execution_state_projection_timeout"`` payload). A projection path that
    still reads the hardcoded 10.0 instead of ``domain_config`` -- the
    pre-fix behaviour -- reports no timeout here and this assertion fails.
    """
    probe = _run_probe(timeout_env="0.15", sleep_seconds=1.0)
    elapsed = float(probe["elapsed"])

    assert probe["degraded_reasons"] == ["execution_state_projection_timeout"], (
        "the projection path must honour VAULTSPEC_AGET_STATE_TIMEOUT_SECONDS, "
        f"not a hardcoded 10.0s default: {probe}"
    )
    assert elapsed < 0.9, (
        "the timeout must fire near the 0.15s knob, not the stale 10.0s "
        f"hardcoded default nor the full 1.0s sleep: {probe}"
    )
