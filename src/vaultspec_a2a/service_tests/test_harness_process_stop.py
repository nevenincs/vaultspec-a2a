"""The service harness stops a process by felling its whole tree.

Real processes, no mocks: ``_stop_process`` now delegates to the lifecycle
``tree_kill``, so a grandchild the stopped process spawned dies with it. The old
terminate-only escalation orphaned grandchildren on Windows (no ``taskkill /T``) -
the stray-engine failure mode this guards against. Auto-marked ``service`` by the
package conftest; it needs no compose stack (spawns only its own children).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time

from ..lifecycle.discovery import is_pid_alive
from ..lifecycle.manager import tree_kill
from .harness import ServiceStack

# A parent that spawns a long-lived grandchild, prints the grandchild pid, then
# sleeps - so the test can assert the grandchild dies when the parent is stopped.
_SPAWN_GRANDCHILD = (
    "import subprocess,sys,time;"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True);"
    "time.sleep(120)"
)


def test_stop_process_tree_kills_grandchildren() -> None:
    stack = ServiceStack(project_name="stopproc-treekill", ports={"gateway": 0})
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    grandchild_pid = int(parent.stdout.readline().strip())
    try:
        assert is_pid_alive(grandchild_pid)

        stack._stop_process(parent)

        # Parent reaped, and the grandchild felled with it (the tree-kill win).
        assert parent.poll() is not None
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and is_pid_alive(grandchild_pid):
            time.sleep(0.05)
        assert not is_pid_alive(grandchild_pid)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=10.0)
        if is_pid_alive(grandchild_pid):
            tree_kill(grandchild_pid)
        shutil.rmtree(stack.runtime_dir, ignore_errors=True)
