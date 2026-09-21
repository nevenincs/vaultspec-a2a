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
``idle``
    A two-second scheduler calibration with no model work. A loaded-host proof
    must establish this control below the fixed ceiling before attributing a
    missed heartbeat to graph compilation.

Prints one JSON object. Every reported duration and maximum heartbeat gap share
the same exact interval. Compile mode also reports bridge close, checkpointer
exit, and an ambient post-cleanup scheduler window independently.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

TICK_SECONDS = 0.01

if TYPE_CHECKING:
    from ...database.checkpoints import Checkpointer
    from ...worker.ipc import WorkerBridge


class _Heartbeat:
    """Ticks on the loop and remembers the longest interval it ever missed."""

    def __init__(self) -> None:
        self.max_gap = 0.0
        self.ticks = 0
        self._stop = False
        self._last_tick_at = time.monotonic()

    async def run(self) -> None:
        while not self._stop:
            await asyncio.sleep(TICK_SECONDS)
            now = time.monotonic()
            self.max_gap = max(self.max_gap, now - self._last_tick_at)
            self._last_tick_at = now
            self.ticks += 1

    def begin_window(self) -> float:
        """Start a new measurement window at an exact loop timestamp."""
        now = time.monotonic()
        self.max_gap = 0.0
        self._last_tick_at = now
        return now

    def finish_window(self, finished_at: float) -> float:
        """Freeze the largest gap at the exact end of the measured work."""
        return max(self.max_gap, finished_at - self._last_tick_at)

    def stop(self) -> None:
        self._stop = True


async def _compile_measured_graph(
    workspace: Path,
    heartbeat: _Heartbeat,
    checkpointer: Checkpointer,
    bridge: WorkerBridge,
) -> tuple[float, float]:
    """Compile the bundled graph and return its duration and loop gap."""
    from uuid import uuid4

    from ...ipc.schemas import DispatchRequest
    from ...streaming.aggregator import EventAggregator
    from ...team.team_config import load_team_config
    from ...thread.executable_graph import freeze_graph_definition
    from ...worker.catalog_store import RunCatalogStore
    from ...worker.graph_lifecycle import GraphLifecycleManager
    from ...worker.token_store import RunTokenStore

    lifecycle = GraphLifecycleManager(
        checkpointer=checkpointer,
        bridge=bridge,
        aggregator=EventAggregator(),
        token_store=RunTokenStore(),
        catalog_store=RunCatalogStore(),
    )
    await asyncio.sleep(0.1)
    started = heartbeat.begin_window()
    graph = await lifecycle.get_or_compile_graph(
        DispatchRequest(
            action="ingest",
            thread_id=f"loop-responsiveness-{uuid4().hex[:8]}",
            agent_id="mock-coder-success",
            content="probe",
            team_preset="mock-success-single",
            graph_definition=freeze_graph_definition(
                load_team_config("mock-success-single", workspace_root=workspace),
                workspace_root=workspace,
            ),
            workspace_root=str(workspace),
            recursion_limit=10,
            model_assignment={
                "mock-coder-success": {
                    "schema_version": 1,
                    "provider": "mock",
                    "execution_mode": "in-process-mock",
                    "catalog_revision": "test-revision",
                    "entry_id": "mock-high",
                    "model_name": "mock-high",
                    "controls": [],
                    "fallbacks": [],
                    "provenance": {"selection_source": "team_selection"},
                }
            },
        )
    )
    compile_finished = time.monotonic()
    compile_seconds = compile_finished - started
    compile_gap = heartbeat.finish_window(compile_finished)
    if graph is None:
        raise RuntimeError("preset compiled to no graph")
    return compile_seconds, compile_gap


async def _run_compile(
    workspace: Path, heartbeat: _Heartbeat
) -> dict[str, float | str]:
    """Compile a bundled preset and report exact compile and teardown windows.

    Opening the checkpointer materializes a database before measurement. The
    compile snapshot is frozen before cleanup begins. Bridge close,
    checkpointer exit, and an ambient scheduler tail are then measured as
    separate windows so none can contaminate or disappear from the result.
    """
    from uuid import uuid4

    from ...database.checkpoints import open_checkpointer
    from ...worker.ipc import WorkerBridge

    checkpointer_context = open_checkpointer()
    checkpointer = await checkpointer_context.__aenter__()
    bridge = WorkerBridge("http://127.0.0.1:9", uuid4().hex[:8], None)
    try:
        try:
            compile_seconds, compile_gap = await _compile_measured_graph(
                workspace, heartbeat, checkpointer, bridge
            )
        finally:
            started = heartbeat.begin_window()
            await bridge.close()
            bridge_finished = time.monotonic()
            bridge_seconds = bridge_finished - started
            bridge_gap = heartbeat.finish_window(bridge_finished)
    finally:
        started = heartbeat.begin_window()
        await checkpointer_context.__aexit__(None, None, None)
        checkpointer_finished = time.monotonic()
        checkpointer_seconds = checkpointer_finished - started
        checkpointer_gap = heartbeat.finish_window(checkpointer_finished)

    started = heartbeat.begin_window()
    await asyncio.sleep(0.1)
    ambient_finished = time.monotonic()
    return {
        "mode": "compile",
        "work_seconds": compile_seconds,
        "max_loop_gap_seconds": compile_gap,
        "bridge_close_seconds": bridge_seconds,
        "bridge_close_max_loop_gap_seconds": bridge_gap,
        "checkpointer_exit_seconds": checkpointer_seconds,
        "checkpointer_exit_max_loop_gap_seconds": checkpointer_gap,
        "ambient_scheduler_seconds": ambient_finished - started,
        "ambient_scheduler_max_loop_gap_seconds": heartbeat.finish_window(
            ambient_finished
        ),
    }


async def _measure(mode: str, workspace: Path) -> dict[str, float | str]:
    from ..warmup import MODEL_STACK_MODULES, warm_model_imports

    already_loaded = [m for m in MODEL_STACK_MODULES if m.lstrip(".") in sys.modules]
    if already_loaded:
        raise RuntimeError(f"interpreter was not cold: {already_loaded} preloaded")

    heartbeat = _Heartbeat()
    ticker = asyncio.create_task(heartbeat.run())
    await asyncio.sleep(0.1)
    started = heartbeat.begin_window()
    result: dict[str, float | str] | None = None
    if mode == "on-loop":
        warm_model_imports()
    elif mode == "offloaded":
        await asyncio.to_thread(warm_model_imports)
    elif mode == "compile":
        result = await _run_compile(workspace, heartbeat)
    elif mode == "idle":
        await asyncio.sleep(2.0)
    else:
        raise SystemExit(f"unknown mode {mode!r}")

    if mode != "compile":
        finished = time.monotonic()
        result = {
            "mode": mode,
            "work_seconds": finished - started,
            "max_loop_gap_seconds": heartbeat.finish_window(finished),
        }

    heartbeat.stop()
    await ticker

    if mode != "idle" and "langchain_openai" not in sys.modules:
        raise RuntimeError("the measured work did not load the model stack")

    assert result is not None
    result["ticks"] = heartbeat.ticks
    return result


def main() -> int:
    """Entry point: ``probe_loop_responsiveness.py <mode> <workspace>``."""
    mode = sys.argv[1]
    workspace = Path(sys.argv[2])
    print(json.dumps(asyncio.run(_measure(mode, workspace))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
