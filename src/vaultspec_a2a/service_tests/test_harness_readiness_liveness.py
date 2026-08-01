"""The service harness's readiness waits fail fast on a dead child.

Real processes, no mocks: the harness owns ``Popen`` handles for the gateway and
the worker, so a child that dies during a readiness wait is knowable
immediately. Before, the wait polled an HTTP probe to a generic deadline and
raised a bare ``TimeoutError`` carrying neither the exit code nor the log - the
bind-race signature took the full 120s or 180s to surface as an unexplained
timeout. Auto-marked ``service`` by the package conftest; it needs no compose
stack (spawns only its own children).
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from ..tests.gateway_boot import GatewayBootError
from .harness import ServiceStack, _wait_for

if TYPE_CHECKING:
    from pathlib import Path

# A child that reports a plausible boot failure to its log, then exits nonzero.
_DIES_ON_BOOT = (
    "import sys;"
    "print('ERROR: [Errno 10048] address already in use');"
    "sys.stdout.flush();"
    "sys.exit(3)"
)
_STAYS_ALIVE = "import time; time.sleep(120)"


def _spawn(program: str, log_path: Path) -> subprocess.Popen[str]:
    with log_path.open("w", encoding="utf-8") as log_file:
        return subprocess.Popen(
            [sys.executable, "-c", program],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )


def test_dead_child_fails_readiness_immediately_with_exit_code_and_log(
    tmp_path: Path,
) -> None:
    """A child that exits mid-wait fails at once, not at the deadline."""
    log_path = tmp_path / "gateway.log"
    proc = _spawn(_DIES_ON_BOOT, log_path)
    assert proc.wait(timeout=30) == 3

    started = time.monotonic()
    with pytest.raises(GatewayBootError) as excinfo:
        _wait_for(
            "gateway HTTP readiness",
            lambda: False,  # never ready — only the liveness check can end this
            timeout=60.0,
            interval=0.1,
            watch=[("gateway", proc, log_path)],
        )
    elapsed = time.monotonic() - started

    # The substance of the fix: the 60s deadline was never burned.
    assert elapsed < 10.0, f"took {elapsed:.1f}s — did not fail fast"
    message = str(excinfo.value)
    assert "gateway" in message
    assert "exit 3" in message
    assert "address already in use" in message, "log tail missing from the failure"


def test_live_child_still_waits_for_its_probe(tmp_path: Path) -> None:
    """The liveness check does not false-positive on a healthy child."""
    log_path = tmp_path / "gateway.log"
    proc = _spawn(_STAYS_ALIVE, log_path)
    try:
        polls: list[int] = []

        def probe() -> bool:
            polls.append(1)
            return len(polls) >= 3

        _wait_for(
            "gateway HTTP readiness",
            probe,
            timeout=30.0,
            interval=0.05,
            watch=[("gateway", proc, log_path)],
        )
        assert len(polls) == 3
    finally:
        proc.kill()
        proc.wait(timeout=30)


def test_alive_but_unready_child_times_out_with_its_log(tmp_path: Path) -> None:
    """A hung-but-alive child is a genuine timeout — now carrying the log."""
    log_path = tmp_path / "gateway.log"
    proc = _spawn(_STAYS_ALIVE, log_path)
    log_path.write_text("still starting up\n", encoding="utf-8")
    try:
        with pytest.raises(TimeoutError) as excinfo:
            _wait_for(
                "gateway HTTP readiness",
                lambda: False,
                timeout=1.0,
                interval=0.1,
                watch=[("gateway", proc, log_path)],
            )
        assert "still starting up" in str(excinfo.value)
    finally:
        proc.kill()
        proc.wait(timeout=30)


def test_processless_wait_keeps_plain_timeout() -> None:
    """Compose-managed waits have no owning Popen and are left unchanged."""
    with pytest.raises(TimeoutError) as excinfo:
        _wait_for("compose service", lambda: False, timeout=1.0, interval=0.1)
    # Not the boot error: there is no exit status to report for a Docker-owned
    # service, so escalating to GatewayBootError here would be a lie.
    assert not isinstance(excinfo.value, GatewayBootError)


def test_watched_reports_only_spawned_processes() -> None:
    """Nothing is watchable before the harness has spawned anything."""
    stack = ServiceStack(project_name="watched-none", ports={"gateway": 0})
    assert stack._watched("gateway", "worker") == []
