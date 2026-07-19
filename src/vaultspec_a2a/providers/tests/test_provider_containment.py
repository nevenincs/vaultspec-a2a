"""Real-process proof that a run-owned provider tree is OS-contained and reaped.

Spawns a genuine subprocess tree through :func:`spawn_acp_process` (a real Python
"provider" that itself spawns a grandchild), then proves
:func:`kill_process_tree` reaps the whole tree through the process's OS
containment - no external CLI, no mock. ``service``-marked because it spawns real
processes.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

from vaultspec_a2a.lifecycle.discovery import is_pid_alive
from vaultspec_a2a.providers._subprocess import kill_process_tree, spawn_acp_process
from vaultspec_a2a.utils.process import ProcessContainment

# A "provider" that spawns a long-lived grandchild, prints its pid, then sleeps.
_PROVIDER_WITH_GRANDCHILD = (
    "import subprocess,sys,time;"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True);"
    "time.sleep(120)"
)


@pytest.mark.service
@pytest.mark.asyncio
async def test_provider_tree_contained_and_reaped_whole() -> None:
    process = await spawn_acp_process(
        [sys.executable, "-c", _PROVIDER_WITH_GRANDCHILD],
        env=os.environ.copy(),
        cwd=os.getcwd(),
        use_exec=True,
    )
    assert process.stdout is not None
    # The provider root is seated in its own containment before descendant work.
    containment = getattr(process, "_vaultspec_containment", None)
    assert isinstance(containment, ProcessContainment)
    assert containment.assigned is True

    line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
    grandchild_pid = int(line.strip())
    try:
        assert is_pid_alive(grandchild_pid)

        await kill_process_tree(process)

        assert process.returncode is not None
        # The grandchild is felled with the contained provider root — no orphan.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(grandchild_pid):
            time.sleep(0.05)
        assert not is_pid_alive(grandchild_pid)
    finally:
        if is_pid_alive(grandchild_pid):
            from vaultspec_a2a.utils.process import kill_pid_tree_async

            await kill_pid_tree_async(grandchild_pid)
