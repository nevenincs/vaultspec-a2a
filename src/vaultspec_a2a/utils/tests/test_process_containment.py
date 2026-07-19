"""Real-process tests for the OS-owned process containment.

Real subprocess trees, no mocks: a root spawned inside its containment - plus a
grandchild it spawns - is reaped whole by :meth:`ProcessContainment.terminate`
without any parent-pid tree walk (Windows Job Object here; a POSIX process group
on POSIX hosts). Liveness is asserted with the canonical ``is_pid_alive`` probe.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from vaultspec_a2a.lifecycle.discovery import is_pid_alive
from vaultspec_a2a.utils.process import ProcessContainment

# A parent that spawns a long-lived grandchild, prints its pid, then sleeps.
_SPAWN_GRANDCHILD = (
    "import subprocess,sys,time;"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True);"
    "time.sleep(120)"
)


def test_spawn_kwargs_shape_matches_platform() -> None:
    containment = ProcessContainment.create()
    kwargs = containment.spawn_kwargs()
    if sys.platform == "win32":
        assert kwargs == {}
    else:
        assert kwargs == {"start_new_session": True}
    containment.close()


@pytest.mark.asyncio
async def test_terminate_fells_the_contained_tree() -> None:
    containment = ProcessContainment.create()
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
        **containment.spawn_kwargs(),
    )
    assert parent.stdout is not None
    containment.assign(parent.pid)
    assert containment.assigned is True
    grandchild_pid = int(parent.stdout.readline().strip())
    try:
        assert is_pid_alive(grandchild_pid)

        reaped = await containment.terminate(term_timeout=10.0, kill_timeout=5.0)
        parent.wait(timeout=10)

        assert reaped is True
        assert parent.poll() is not None
        # The grandchild is felled with the contained root — no orphan, no walk.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(grandchild_pid):
            time.sleep(0.05)
        assert not is_pid_alive(grandchild_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if is_pid_alive(grandchild_pid):
            from vaultspec_a2a.utils.process import kill_pid_tree_async

            await kill_pid_tree_async(grandchild_pid)


@pytest.mark.asyncio
async def test_terminate_of_already_exited_root_is_success() -> None:
    containment = ProcessContainment.create()
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"], **containment.spawn_kwargs()
    )
    containment.assign(proc.pid)
    proc.wait()
    assert await containment.terminate(term_timeout=2.0, kill_timeout=2.0) is True


@pytest.mark.asyncio
async def test_unassigned_containment_terminate_is_noop_success() -> None:
    containment = ProcessContainment.create()
    assert containment.assigned is False
    # Never assigned a pid: nothing to reap, terminate is a clean success.
    assert await containment.terminate() is True
