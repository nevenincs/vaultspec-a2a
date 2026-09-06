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
import re
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ...lifecycle.discovery import is_pid_alive
from ...providers._subprocess import (
    _spawn_acp_process,
    kill_process_tree,
    spawn_acp_process,
)
from ...utils.process import ProcessContainment, ProcessContainmentError

# A "provider" that spawns a long-lived grandchild, prints its pid, then sleeps.
_PROVIDER_WITH_GRANDCHILD = (
    "import subprocess,sys,time;"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True);"
    "time.sleep(120)"
)

_PROVIDER_WITH_LATE_GRANDCHILD = (
    "import subprocess,sys,time;"
    "print('ready',flush=True);"
    "time.sleep(0.5);"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True);"
    "time.sleep(120)"
)

_PROVIDER_EXITS_AFTER_GRANDCHILD = (
    "import subprocess,sys;"
    "g=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']);"
    "print(g.pid,flush=True)"
)


def _base_interpreter() -> str:
    """Return the real interpreter rather than a Windows venv redirector."""
    return getattr(sys, "_base_executable", sys.executable)


def _await_gone(pids: list[int], *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(is_pid_alive(pid) for pid in pids):
        time.sleep(0.05)
    survivors = [pid for pid in pids if is_pid_alive(pid)]
    assert not survivors, f"provider descendants survived reap: {survivors}"


async def _force_reap(pids: list[int]) -> None:
    from ...utils.process import kill_pid_tree_async

    for pid in pids:
        if is_pid_alive(pid):
            await kill_pid_tree_async(pid, term_timeout=0.2, kill_timeout=2.0)


@pytest.mark.service
@pytest.mark.asyncio
@pytest.mark.parametrize("use_exec", [False, True], ids=["shell", "exec"])
async def test_provider_tree_contained_and_reaped_whole(use_exec: bool) -> None:
    process = await spawn_acp_process(
        [_base_interpreter(), "-c", _PROVIDER_WITH_GRANDCHILD],
        env=os.environ.copy(),
        cwd=os.getcwd(),
        use_exec=use_exec,
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
        _await_gone([grandchild_pid])
    finally:
        await _force_reap([grandchild_pid])


@pytest.mark.service
@pytest.mark.asyncio
async def test_late_provider_child_remains_in_owned_containment() -> None:
    process = await spawn_acp_process(
        [_base_interpreter(), "-c", _PROVIDER_WITH_LATE_GRANDCHILD],
        env=os.environ.copy(),
        cwd=os.getcwd(),
        use_exec=True,
    )
    assert process.stdout is not None
    ready = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
    assert ready.strip() == b"ready"
    grandchild_pid = int(
        (await asyncio.wait_for(process.stdout.readline(), timeout=10.0)).strip()
    )
    try:
        assert is_pid_alive(grandchild_pid)
        await kill_process_tree(process)
        _await_gone([grandchild_pid])
    finally:
        await _force_reap([grandchild_pid])


@pytest.mark.service
@pytest.mark.asyncio
async def test_containment_reaps_child_after_provider_root_exits() -> None:
    process = await spawn_acp_process(
        [_base_interpreter(), "-c", _PROVIDER_EXITS_AFTER_GRANDCHILD],
        env=os.environ.copy(),
        cwd=os.getcwd(),
        use_exec=True,
    )
    assert process.stdout is not None
    grandchild_pid = int(
        (await asyncio.wait_for(process.stdout.readline(), timeout=10.0)).strip()
    )
    try:
        deadline = time.monotonic() + 10.0
        while process.returncode is None and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert process.returncode == 0
        assert is_pid_alive(grandchild_pid)
        await kill_process_tree(process)
        _await_gone([grandchild_pid])
    finally:
        await _force_reap([grandchild_pid])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job assignment proof")
@pytest.mark.service
@pytest.mark.asyncio
async def test_assignment_failure_reaps_suspended_root_before_first_instruction(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "provider-first-instruction"
    script = f"from pathlib import Path; Path({str(marker)!r}).touch()"
    containment = ProcessContainment.create()
    containment.close()
    started = time.monotonic()
    with pytest.raises(
        ProcessContainmentError, match="Windows containment has no job object"
    ) as caught:
        await _spawn_acp_process(
            [_base_interpreter(), "-c", script],
            os.environ.copy(),
            os.getcwd(),
            use_exec=True,
            metadata=None,
            containment=containment,
        )
    elapsed = time.monotonic() - started
    assert elapsed < 10.5, f"assignment-failure cleanup took {elapsed:.4f}s"
    pid_match = re.search(r"process (\d+)", str(caught.value))
    assert pid_match is not None
    assert not marker.exists(), "provider executed before failed Job assignment"
    assert not is_pid_alive(int(pid_match.group(1)))
