"""Progress-based child waits, driven against real interpreters.

A wait must finish a child that ends, reap one that stops making progress, and
catch one that only spins - from a plain test and from one running an event
loop alike.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TYPE_CHECKING

import psutil
import pytest

from ...utils import ProcessContainment, spawn_contained
from ..children import await_child, reap_contained, run_child
from ..progress import ProgressStalledError

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Generator


@contextlib.contextmanager
def _contained(
    code: str,
) -> Generator[tuple[subprocess.Popen[bytes], ProcessContainment]]:
    """Run *code* in a contained interpreter, reaped however the test ends."""
    containment = ProcessContainment.create()
    process = spawn_contained([sys.executable, "-c", code], containment)
    try:
        yield process, containment
    finally:
        reap_contained(process, containment)


def test_a_child_that_finishes_returns_its_exit_status() -> None:
    result = run_child(
        [sys.executable, "-c", "import sys; print('done'); sys.exit(3)"],
        what="a finishing child",
    )

    assert result.returncode == 3
    assert result.stdout.strip() == "done"


def test_a_child_that_stops_making_progress_is_reaped() -> None:
    with _contained("import time; time.sleep(3600)") as (idle, containment):
        with pytest.raises(ProgressStalledError, match="an idle child"):
            await_child(idle, containment, what="an idle child", idle_window_s=2.0)

        assert not psutil.pid_exists(idle.pid) or idle.poll() is not None


def test_a_spinning_child_is_caught_by_its_ceiling() -> None:
    """CPU keeps moving in a poll loop, so only the ceiling can call it wedged."""
    with _contained("import time\nwhile True:\n    time.sleep(0.01)\n") as (
        spinning,
        containment,
    ):
        with pytest.raises(ProgressStalledError, match="ceiling"):
            await_child(spinning, containment, what="a spinning child", ceiling_s=3.0)

        assert spinning.poll() is not None


def test_a_wedged_child_is_reaped_from_inside_an_event_loop() -> None:
    with _contained("import time; time.sleep(3600)") as (idle, containment):

        async def _wait_inside_a_loop() -> None:
            await_child(idle, containment, what="an idle child", idle_window_s=2.0)

        with pytest.raises(ProgressStalledError, match="an idle child"):
            asyncio.run(_wait_inside_a_loop())

        assert idle.poll() is not None
