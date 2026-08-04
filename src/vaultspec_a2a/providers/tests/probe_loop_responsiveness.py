"""Measure event-loop responsiveness across the model stack's first import.

Run as a script in a COLD interpreter - the cost under test is paid exactly once
per process, so a fresh subprocess is the only place it can be observed. Three
modes share one heartbeat meter so their numbers are directly comparable:

``on-loop``
    Imports the model stack directly inside a coroutine. This is the control:
    it establishes that the import really is expensive on this machine and that
    the meter can see a blocked loop at all, without which the other two modes
    would pass for free.
``offloaded``
    The same import through ``asyncio.to_thread``.
``compile``
    The production seam - ``GraphLifecycleManager.get_or_compile_graph`` for a
    real bundled preset - which triggers the same import from inside
    ``ProviderFactory.create``.

Prints one JSON object: the wall time of the measured work and the largest gap
between heartbeat ticks while it ran.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

TICK_SECONDS = 0.01


class _Heartbeat:
    """Ticks on the loop and remembers the longest interval it ever missed."""

    def __init__(self) -> None:
        self.max_gap = 0.0
        self.ticks = 0
        self._stop = False

    async def run(self) -> None:
        previous = time.monotonic()
        while not self._stop:
            await asyncio.sleep(TICK_SECONDS)
            now = time.monotonic()
            self.max_gap = max(self.max_gap, now - previous)
            previous = now
            self.ticks += 1

    def stop(self) -> None:
        self._stop = True


async def _run_compile(workspace: Path, heartbeat: _Heartbeat) -> float:
    """Compile a bundled preset and return how long the compile call took.

    Opening the checkpointer materializes a database, and closing the bridge
    retries a relay against an unreachable gateway; both are harness costs no
    dispatch repeats, so the meter is zeroed once the manager is built and the
    returned duration covers the compile call alone.
    """
    from uuid import uuid4

    from ...database.checkpoints import open_checkpointer
    from ...ipc.schemas import DispatchRequest
    from ...streaming.aggregator import EventAggregator
    from ...worker.catalog_store import RunCatalogStore
    from ...worker.graph_lifecycle import GraphLifecycleManager
    from ...worker.ipc import WorkerBridge
    from ...worker.token_store import RunTokenStore

    async with open_checkpointer() as checkpointer:
        bridge = WorkerBridge("http://127.0.0.1:9", uuid4().hex[:8], None)
        try:
            lifecycle = GraphLifecycleManager(
                checkpointer=checkpointer,
                bridge=bridge,
                aggregator=EventAggregator(),
                token_store=RunTokenStore(),
                catalog_store=RunCatalogStore(),
            )
            await asyncio.sleep(0.1)
            heartbeat.max_gap = 0.0
            started = time.monotonic()
            graph = await lifecycle.get_or_compile_graph(
                DispatchRequest(
                    action="ingest",
                    thread_id=f"loop-responsiveness-{uuid4().hex[:8]}",
                    agent_id="mock-coder-success",
                    content="probe",
                    team_preset="mock-success-single",
                    workspace_root=str(workspace),
                    recursion_limit=10,
                )
            )
            compile_seconds = time.monotonic() - started
            if graph is None:
                raise RuntimeError("preset compiled to no graph")
            return compile_seconds
        finally:
            await bridge.close()


async def _measure(mode: str, workspace: Path) -> dict[str, float | str]:
    from ..warmup import MODEL_STACK_MODULES, warm_model_imports

    already_loaded = [m for m in MODEL_STACK_MODULES if m.lstrip(".") in sys.modules]
    if already_loaded:
        raise RuntimeError(f"interpreter was not cold: {already_loaded} preloaded")

    heartbeat = _Heartbeat()
    ticker = asyncio.create_task(heartbeat.run())
    await asyncio.sleep(0.1)
    heartbeat.max_gap = 0.0

    started = time.monotonic()
    if mode == "on-loop":
        warm_model_imports()
        elapsed = time.monotonic() - started
    elif mode == "offloaded":
        await asyncio.to_thread(warm_model_imports)
        elapsed = time.monotonic() - started
    elif mode == "compile":
        elapsed = await _run_compile(workspace, heartbeat)
    else:
        raise SystemExit(f"unknown mode {mode!r}")

    heartbeat.stop()
    await ticker

    if "langchain_openai" not in sys.modules:
        raise RuntimeError("the measured work did not load the model stack")

    return {
        "mode": mode,
        "work_seconds": elapsed,
        "max_loop_gap_seconds": heartbeat.max_gap,
        "ticks": heartbeat.ticks,
    }


def main() -> int:
    """Entry point: ``probe_loop_responsiveness.py <mode> <workspace>``."""
    mode = sys.argv[1]
    workspace = Path(sys.argv[2])
    print(json.dumps(asyncio.run(_measure(mode, workspace))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
