"""The model stack's first import must not run on a serving event loop.

``ProviderFactory.create`` loads ``langchain_openai`` and ``acp_chat_model`` on
first use, and it is reached from synchronous compile code that the worker runs
directly on its event loop. Paid there, that import stops the loop for seconds:
the worker answers no ``/health`` probe and accepts no second dispatch while a
run boots, which reads from outside as an absent worker.

These are process-level measurements, not assertions about call structure. The
cost exists once per interpreter, so each case runs in its own cold subprocess,
and an ``on-loop`` control run establishes on THIS machine that the import is
expensive and that the heartbeat meter can see a blocked loop - without it the
offloaded cases would pass for free on a fast host.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

#: The control must block the loop by at least this much for the comparison to
#: mean anything. Cold imports measured ~7s on the reference machine; this is a
#: wide margin below that, and a host fast enough to miss it has no stall to fix.
_BLOCKED_LOOP_FLOOR_SECONDS = 1.0

#: A loop that keeps ticking within this window is serving. Well above the 10ms
#: heartbeat so ordinary scheduler jitter never reads as a stall, and far below
#: the multi-second block the control demonstrates.
_RESPONSIVE_LOOP_CEILING_SECONDS = 0.5

pytestmark = pytest.mark.middleware


def _probe(mode: str, workspace: Path) -> dict[str, Any]:
    """Run one measurement in a cold interpreter and return its report."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_a2a.providers.tests.probe_loop_responsiveness",
            mode,
            str(workspace),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"{mode} probe exited {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def blocked_loop_control(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """Import the model stack ON the loop, so the rest has a calibrated baseline."""
    return _probe("on-loop", tmp_path_factory.mktemp("warmup-control"))


def test_importing_the_model_stack_on_the_loop_blocks_it(
    blocked_loop_control: dict[str, Any],
) -> None:
    """The regression this guards against is real and this meter detects it."""
    assert blocked_loop_control["work_seconds"] >= _BLOCKED_LOOP_FLOOR_SECONDS, (
        "the model stack imported too fast to measure; the comparison below "
        f"would be vacuous: {blocked_loop_control}"
    )
    assert blocked_loop_control["max_loop_gap_seconds"] >= (
        _BLOCKED_LOOP_FLOOR_SECONDS
    ), (
        "importing the model stack inside a coroutine did NOT block the loop, "
        f"so this suite cannot detect the stall it exists for: {blocked_loop_control}"
    )


def test_warm_model_imports_offloads_the_cost_off_the_loop(
    blocked_loop_control: dict[str, Any], tmp_path: Path
) -> None:
    """``warm_model_imports`` on a thread leaves the loop free to serve."""
    offloaded = _probe("offloaded", tmp_path)

    assert offloaded["max_loop_gap_seconds"] < _RESPONSIVE_LOOP_CEILING_SECONDS, (
        f"offloading left the loop stalled: {offloaded}"
    )
    assert (
        offloaded["max_loop_gap_seconds"] < blocked_loop_control["max_loop_gap_seconds"]
    ), f"offloaded is no better than on-loop: {offloaded} vs {blocked_loop_control}"


def test_compiling_a_graph_keeps_the_loop_serving(
    blocked_loop_control: dict[str, Any], tmp_path: Path
) -> None:
    """The production compile seam pays the import without stalling the loop.

    Drives ``GraphLifecycleManager.get_or_compile_graph`` for a bundled preset.
    The preset resolves to the in-process mock lane, which needs no credential
    and no network, and still pays the identical cost: ``create`` imports the
    model stack before it branches on the requested provider.
    """
    compiled = _probe("compile", tmp_path)

    assert compiled["max_loop_gap_seconds"] < _RESPONSIVE_LOOP_CEILING_SECONDS, (
        "compiling a graph stalled the worker's event loop; the model stack is "
        f"being imported on it again: {compiled}"
    )
    assert (
        compiled["max_loop_gap_seconds"] < blocked_loop_control["max_loop_gap_seconds"]
    ), f"compile is no better than importing on the loop: {compiled}"
