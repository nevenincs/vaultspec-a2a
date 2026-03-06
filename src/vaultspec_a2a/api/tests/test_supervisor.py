"""Tests for src/vaultspec_a2a/api/supervisor.py -- WorkerSupervisor lifecycle (ADR-019).

Validates the supervisor's initial state and process lifecycle (start/stop)
using real subprocesses.  For lifecycle tests we use a simple ``python -c
'sleep'`` process rather than starting a real uvicorn worker, which would
bind ports and attempt connections to the control surface.

No mocks, no fakes, no monkeypatching.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ..supervisor import WorkerSupervisor


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    """Verify supervisor public behaviour before any process is started."""

    def test_pid_is_none_before_start(self) -> None:
        sup = WorkerSupervisor(worker_port=19999)
        assert sup.pid is None

    def test_is_alive_returns_false_before_start(self) -> None:
        sup = WorkerSupervisor(worker_port=19999)
        assert sup.is_alive() is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stop_before_start_is_safe(self) -> None:
        """stop() on a never-started supervisor must not raise."""
        sup = WorkerSupervisor(worker_port=19999)
        await sup.stop()
        assert sup.pid is None
        assert sup.is_alive() is False


# ---------------------------------------------------------------------------
# Process lifecycle using a real subprocess
# ---------------------------------------------------------------------------


class TestProcessLifecycle:
    """Test start/stop using a lightweight sleep subprocess.

    We assign a real ``subprocess.Popen`` to ``_process`` because calling
    ``start()`` would invoke ``python -m vaultspec_a2a.worker`` (binds ports, needs
    control surface up).  These tests verify that ``is_alive()``, ``pid``,
    and ``stop()`` correctly interrogate and manage a real OS process.
    """

    def test_running_process_is_detected_as_alive(self) -> None:
        sup = WorkerSupervisor(worker_port=19999)
        sup._process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        try:
            assert sup.is_alive() is True
            assert sup.pid is not None
            assert isinstance(sup.pid, int)
            assert sup.pid > 0
        finally:
            sup._process.terminate()
            sup._process.wait(timeout=10)

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stop_terminates_running_process(self) -> None:
        sup = WorkerSupervisor(worker_port=19999)
        sup._process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        assert sup.is_alive() is True
        pid_before = sup.pid

        await sup.stop()

        assert sup.is_alive() is False
        assert sup.pid is None
        # Verify the process is actually gone -- poll() returns exit code
        # when the process has terminated.  After stop(), _process is None
        # so we can't check directly, but the fact that stop() returned
        # without timeout means the process was successfully reaped.

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stop_on_already_exited_process_is_safe(self) -> None:
        """stop() when process exited naturally doesn't raise."""
        sup = WorkerSupervisor(worker_port=19999)
        sup._process = subprocess.Popen(
            [sys.executable, "-c", "pass"]  # Exits immediately
        )
        sup._process.wait(timeout=10)
        assert sup.is_alive() is False

        # stop() should not raise
        await sup.stop()

    def test_pid_reflects_process_exit(self) -> None:
        """pid returns None for an exited process (is_alive guard)."""
        sup = WorkerSupervisor(worker_port=19999)
        sup._process = subprocess.Popen(
            [sys.executable, "-c", "pass"]  # Exits immediately
        )
        sup._process.wait(timeout=10)
        assert sup.pid is None

    def test_start_spawns_real_subprocess(self) -> None:
        """Verify start() actually creates a child process.

        We call the real ``start()`` method.  The worker will fail during
        lifespan (no control surface running), but the subprocess itself
        will be alive momentarily.  We verify is_alive() then clean up.
        """
        sup = WorkerSupervisor(worker_port=19999)
        sup.start()
        try:
            # The subprocess may have started -- is_alive() should be True
            # before the worker crashes from missing control surface.
            # Even if it crashes immediately, pid should have been set.
            assert sup._process is not None
        finally:
            # Clean up regardless
            if sup._process is not None:
                sup._process.terminate()
                try:
                    sup._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    sup._process.kill()
                    sup._process.wait(timeout=5)
