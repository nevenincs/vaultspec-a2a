"""Real-process tests for the shared async tree-kill primitive.

Real subprocesses, no mocks: a process that spawns a grandchild is felled whole,
so no orphan survives (the Windows taskkill /T behaviour the two former copies
existed to provide). Liveness is asserted with the canonical is_pid_alive probe.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from vaultspec_a2a.lifecycle.discovery import is_pid_alive
from vaultspec_a2a.utils.process import kill_pid_tree_async

# A parent that spawns a long-lived grandchild, prints its pid, then sleeps.
_SPAWN_GRANDCHILD = (
    "import subprocess,sys,time;"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True);"
    "time.sleep(120)"
)


@pytest.mark.asyncio
async def test_kill_pid_tree_fells_the_whole_tree() -> None:
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    grandchild_pid = int(parent.stdout.readline().strip())
    try:
        assert is_pid_alive(grandchild_pid)

        killed = await kill_pid_tree_async(
            parent.pid, term_timeout=10.0, kill_timeout=5.0
        )
        parent.wait(timeout=10)

        assert killed is True
        assert parent.poll() is not None
        # The grandchild is felled with the parent — no orphan.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(grandchild_pid):
            time.sleep(0.05)
        assert not is_pid_alive(grandchild_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if is_pid_alive(grandchild_pid):
            await kill_pid_tree_async(grandchild_pid)


@pytest.mark.asyncio
async def test_kill_pid_tree_on_an_already_dead_pid_is_success() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert await kill_pid_tree_async(proc.pid) is True


@pytest.mark.asyncio
async def test_kill_pid_tree_nonpositive_pid_is_success() -> None:
    assert await kill_pid_tree_async(0) is True
    assert await kill_pid_tree_async(-1) is True
