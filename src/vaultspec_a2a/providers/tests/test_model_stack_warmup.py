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
import time
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Any

import psutil
import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

#: The control must block the loop by at least this much for the comparison to
#: mean anything. Cold imports measured ~7s on the reference machine; this is a
#: wide margin below that, and a host fast enough to miss it has no stall to fix.
_BLOCKED_LOOP_FLOOR_SECONDS = 1.0

#: A loop that keeps ticking within this window is serving. Well above the 10ms
#: heartbeat so ordinary scheduler jitter never reads as a stall, and far below
#: the multi-second block the control demonstrates.
_RESPONSIVE_LOOP_CEILING_SECONDS = 0.5

# The remediation campaign froze worker execution concurrency C at five before
# measurement. Five independent CPU-bound processes make that load real and
# observable without changing the production ceiling or relying on whatever
# unrelated work happens to share the host during a test run.
_REPRESENTATIVE_BUSY_PROCESSES = 5
_REPRESENTATIVE_COMPILE_TRIALS = 5
_TEARDOWN_PHASE_FIELDS = (
    ("bridge_close_seconds", "bridge_close_max_loop_gap_seconds"),
    ("checkpointer_exit_seconds", "checkpointer_exit_max_loop_gap_seconds"),
    ("ambient_scheduler_seconds", "ambient_scheduler_max_loop_gap_seconds"),
)

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


@contextmanager
def _representative_cpu_load() -> Generator[list[psutil.Process]]:
    """Occupy the campaign's five worker slots with owned CPU-bound processes."""
    # On Windows a venv's ``sys.executable`` is a redirector that parents the
    # real interpreter. Measuring that idle redirector would make the load proof
    # vacuous, and signalling it would not identify the process burning CPU.
    python = getattr(sys, "_base_executable", sys.executable)
    processes = [
        subprocess.Popen(
            [python, "-c", "value = 1\nwhile True: value = value * 3 % 97"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(_REPRESENTATIVE_BUSY_PROCESSES)
    ]
    owners = [psutil.Process(process.pid) for process in processes]
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if all(owner.cpu_times().user > 0.05 for owner in owners):
                break
            time.sleep(0.05)
        assert all(owner.cpu_times().user > 0.05 for owner in owners), (
            "the representative CPU load never became non-vacuous"
        )
        yield owners
    finally:
        for process in processes:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)


@pytest.fixture(scope="module")
def blocked_loop_control(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """Import the model stack ON the loop, so the rest has a calibrated baseline."""
    return _probe("on-loop", tmp_path_factory.mktemp("warmup-control"))


@pytest.fixture(scope="module")
def cold_compile_probe(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """One immutable cold compile report shared by its independent assertions."""
    return _probe("compile", tmp_path_factory.mktemp("warmup-compile"))


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
    blocked_loop_control: dict[str, Any], cold_compile_probe: dict[str, Any]
) -> None:
    """The production compile seam pays the import without stalling the loop.

    Drives ``GraphLifecycleManager.get_or_compile_graph`` for a bundled preset.
    The preset resolves to the in-process mock lane, which needs no credential
    and no network, and still pays the identical cost: ``create`` imports the
    model stack before it branches on the requested provider.
    """
    compiled = cold_compile_probe

    assert compiled["max_loop_gap_seconds"] < _RESPONSIVE_LOOP_CEILING_SECONDS, (
        "compiling a graph stalled the worker's event loop; the model stack is "
        f"being imported on it again: {compiled}"
    )
    assert (
        compiled["max_loop_gap_seconds"] < blocked_loop_control["max_loop_gap_seconds"]
    ), f"compile is no better than importing on the loop: {compiled}"


def test_compile_probe_reports_distinct_teardown_windows(
    cold_compile_probe: dict[str, Any],
) -> None:
    """Compile cleanup phases have independent, internally bounded samples.

    This discriminator establishes the measurement boundary. The serving
    threshold for worker shutdown belongs to the separately tracked lifecycle
    qualification; an intermittent bridge-close violation must remain visible
    there without invalidating the compile-only sample.
    """
    compiled = cold_compile_probe

    for duration_field, gap_field in _TEARDOWN_PHASE_FIELDS:
        assert duration_field in compiled, (
            f"compile probe omitted teardown field {duration_field}"
        )
        assert gap_field in compiled, (
            f"compile probe omitted teardown field {gap_field}"
        )
        assert 0.0 <= compiled[gap_field] <= compiled[duration_field], (
            f"teardown phase boundaries disagree at {gap_field}: {compiled}"
        )
    assert compiled["bridge_close_seconds"] > 1.0, (
        "the unreachable-gateway retry cleanup was not exercised"
    )


def test_repeated_cold_compiles_keep_serving_under_five_slot_cpu_load(
    blocked_loop_control: dict[str, Any], tmp_path: Path
) -> None:
    """The fixed loop-gap ceiling holds repeatedly under named campaign load."""
    with _representative_cpu_load() as owners:
        before = [owner.cpu_times().user for owner in owners]
        scheduler = _probe("idle", tmp_path / "scheduler-control")
        compiled = [
            _probe("compile", tmp_path / f"trial-{trial}")
            for trial in range(_REPRESENTATIVE_COMPILE_TRIALS)
        ]
        after = [owner.cpu_times().user for owner in owners]

    assert all(end - start > 0.25 for start, end in zip(before, after, strict=True)), (
        "the five-slot CPU load did not remain active across the compile trials"
    )
    assert all(not owner.is_running() for owner in owners), (
        "an owned representative-load process survived the measurement"
    )
    assert scheduler["max_loop_gap_seconds"] < _RESPONSIVE_LOOP_CEILING_SECONDS, (
        "representative-load measurement is inconclusive: the idle event loop "
        f"already exceeded the fixed ceiling: {scheduler}"
    )
    assert all(
        result["max_loop_gap_seconds"] < _RESPONSIVE_LOOP_CEILING_SECONDS
        for result in compiled
    ), f"a compile exceeded the fixed loop responsiveness ceiling: {compiled}"
    assert all(
        result["max_loop_gap_seconds"] < blocked_loop_control["max_loop_gap_seconds"]
        for result in compiled
    ), f"loaded compile was no better than the on-loop control: {compiled}"
    assert all(
        0.0 <= result[gap_field] <= result[duration_field]
        for result in compiled
        for duration_field, gap_field in _TEARDOWN_PHASE_FIELDS
    ), f"loaded compile teardown phase boundaries disagree: {compiled}"
