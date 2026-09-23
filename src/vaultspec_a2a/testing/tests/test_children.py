"""Progress-based child waits, driven against real interpreters.

A wait must finish a child that ends, reap one that stops making progress, and
catch one that only spins - from a plain test and from one running an event
loop alike.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import psutil
import pytest

from ..children import await_child, run_child
from ..progress import ProgressStalledError


def _spawn(code: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", code])


def test_a_child_that_finishes_returns_its_exit_status() -> None:
    result = run_child(
        [sys.executable, "-c", "import sys; print('done'); sys.exit(3)"],
        what="a finishing child",
    )

    assert result.returncode == 3
    assert result.stdout.strip() == "done"


def test_a_child_that_stops_making_progress_is_reaped() -> None:
    idle = _spawn("import time; time.sleep(3600)")

    with pytest.raises(ProgressStalledError, match="an idle child"):
        await_child(idle, what="an idle child", idle_window_s=2.0)

    assert not psutil.pid_exists(idle.pid) or idle.poll() is not None


def test_a_spinning_child_is_caught_by_its_ceiling() -> None:
    """CPU keeps moving in a poll loop, so only the ceiling can call it wedged."""
    spinning = _spawn("import time\nwhile True:\n    time.sleep(0.01)\n")

    with pytest.raises(ProgressStalledError, match="ceiling"):
        await_child(spinning, what="a spinning child", ceiling_s=3.0)

    assert spinning.poll() is not None


def test_a_wedged_child_is_reaped_from_inside_an_event_loop() -> None:
    idle = _spawn("import time; time.sleep(3600)")

    async def _wait_inside_a_loop() -> None:
        await_child(idle, what="an idle child", idle_window_s=2.0)

    with pytest.raises(ProgressStalledError, match="an idle child"):
        asyncio.run(_wait_inside_a_loop())

    assert idle.poll() is not None
