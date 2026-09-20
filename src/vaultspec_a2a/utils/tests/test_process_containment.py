"""Real processes exercise descendant, cancellation, and native handle ownership."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import psutil
import pytest

from ...utils._process_tree import kill_pid_tree_async, pid_is_live
from ...utils._process_tree import win_kernel32 as _win_kernel32
from ...utils._process_tree import win_parent_map as _win_parent_map
from ...utils.process import (
    ProcessContainment,
    ProcessContainmentError,
    _posix_group_is_live,
    _ps_group_is_live,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# The gate makes job assignment precede descendant creation on Windows. The
# descendant's ready message proves its signal handler is installed before teardown.
_GATED_TREE = """
import os, subprocess, sys, time
sys.stdin.readline()
child = subprocess.Popen(
    [sys.executable, '-c', sys.argv[1]], stdout=subprocess.PIPE, text=True,
)
assert child.stdout.readline().strip() == 'ready'
print(child.pid, flush=True)
print(os.getpid(), flush=True)
time.sleep(120)
"""
_CHILD = "import time; print('ready', flush=True); time.sleep(120)"
_STUBBORN_CHILD = (
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "print('ready', flush=True); time.sleep(120)"
)


@contextlib.asynccontextmanager
async def _owned_tree(
    child_source: str = _CHILD,
) -> AsyncGenerator[tuple[ProcessContainment, subprocess.Popen[str], int]]:
    containment = ProcessContainment.create()
    parent: subprocess.Popen[str] | None = None
    child_pid: int | None = None
    try:
        parent = subprocess.Popen(
            [sys.executable, "-c", _GATED_TREE, child_source],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            **containment.spawn_kwargs(),
        )
        containment.assign(parent.pid)
        assert parent.stdin is not None
        assert parent.stdout is not None
        parent.stdin.write("go\n")
        parent.stdin.flush()
        child_pid = int(await asyncio.to_thread(parent.stdout.readline))
        yield containment, parent, child_pid
    finally:
        try:
            await containment.terminate(term_timeout=0.2, kill_timeout=5.0)
            if child_pid is not None and pid_is_live(child_pid):
                await kill_pid_tree_async(child_pid, term_timeout=0.2)
        finally:
            if parent is not None:
                if parent.poll() is None:
                    parent.kill()
                parent.wait(timeout=10)
                if parent.stdin is not None:
                    parent.stdin.close()
                if parent.stdout is not None:
                    parent.stdout.close()
            containment.close()


def test_spawn_kwargs_shape_matches_platform() -> None:
    containment = ProcessContainment.create()
    try:
        expected = {} if sys.platform == "win32" else {"start_new_session": True}
        assert containment.spawn_kwargs() == expected
    finally:
        containment.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("root_exited", [False, True])
@pytest.mark.parametrize("child_source", [_CHILD, _STUBBORN_CHILD])
async def test_terminate_fells_the_contained_tree(
    root_exited: bool, child_source: str
) -> None:
    async with _owned_tree(child_source) as (containment, parent, child_pid):
        foreign = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"]
        )
        try:
            assert containment.assigned
            assert pid_is_live(child_pid)
            if root_exited:
                parent.kill()
                parent.wait(timeout=10)
                assert pid_is_live(child_pid)

            assert await containment.terminate(term_timeout=0.2, kill_timeout=5.0)
            parent.wait(timeout=10)

            assert not pid_is_live(child_pid)
            assert foreign.poll() is None
            assert not containment.assigned
            assert containment._pid is None
            assert containment._pgid is None
            # Repetition cannot send another signal to a numeric group that may
            # now have been reused by another owner.
            assert await containment.terminate(term_timeout=0.2, kill_timeout=5.0)
            assert foreign.poll() is None
        finally:
            foreign.kill()
            foreign.wait(timeout=10)


@pytest.mark.asyncio
async def test_cancellation_joins_contained_tree_cleanup() -> None:
    async with _owned_tree(_STUBBORN_CHILD) as (containment, parent, child_pid):
        task = asyncio.create_task(
            containment.terminate(term_timeout=0.2, kill_timeout=5.0)
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        parent.wait(timeout=10)
        assert not pid_is_live(child_pid)
        assert not containment.assigned
        assert containment._job is None


@pytest.mark.asyncio
async def test_cancellation_joins_pid_tree_cleanup() -> None:
    async with _owned_tree(_STUBBORN_CHILD) as (_, parent, child_pid):
        task = asyncio.create_task(
            kill_pid_tree_async(parent.pid, term_timeout=0.2, kill_timeout=5.0)
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        parent.wait(timeout=10)
        assert not pid_is_live(child_pid)


@pytest.mark.asyncio
async def test_concurrent_termination_joins_one_owned_cleanup() -> None:
    async with _owned_tree(_STUBBORN_CHILD) as (containment, parent, child_pid):
        results = await asyncio.gather(
            containment.terminate(term_timeout=0.2, kill_timeout=5.0),
            containment.terminate(term_timeout=0.2, kill_timeout=5.0),
        )
        assert results == [True, True]
        parent.wait(timeout=10)
        assert not pid_is_live(child_pid)


@pytest.mark.asyncio
async def test_terminate_of_already_exited_root_is_success() -> None:
    containment = ProcessContainment.create()
    try:
        # Keep the process alive until its Windows job assignment completes.
        with subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.readline()"],
            stdin=subprocess.PIPE,
            **containment.spawn_kwargs(),
        ) as proc:
            containment.assign(proc.pid)
            assert proc.stdin is not None
            proc.stdin.close()
            proc.wait(timeout=10)
            assert await containment.terminate(term_timeout=0.2, kill_timeout=2.0)
            assert not containment.assigned
    finally:
        containment.close()


@pytest.mark.asyncio
async def test_repeated_unassigned_termination_releases_native_handles() -> None:
    # Warm up the event-loop/native API paths before taking the process handle count.
    warmup = ProcessContainment.create()
    assert await warmup.terminate()
    process = psutil.Process()
    before = process.num_handles() if sys.platform == "win32" else process.num_fds()
    for _ in range(100):
        containment = ProcessContainment.create()
        try:
            assert not containment.assigned
            assert await containment.terminate()
            assert await containment.terminate()
            assert containment._job is None
        finally:
            containment.close()
    after = process.num_handles() if sys.platform == "win32" else process.num_fds()
    # Other completed subprocess handles may be collected during the loop.
    assert after <= before


def test_repeated_liveness_probes_release_process_handles() -> None:
    process = psutil.Process()
    assert pid_is_live(process.pid)
    before = process.num_handles() if sys.platform == "win32" else process.num_fds()
    for _ in range(100):
        assert pid_is_live(process.pid)
    after = process.num_handles() if sys.platform == "win32" else process.num_fds()
    assert after <= before


if sys.platform == "win32":

    @pytest.mark.asyncio
    async def test_parent_snapshots_track_descendants_without_handle_growth() -> None:
        async with _owned_tree() as (_, parent, child_pid):
            assert parent.stdout is not None
            # Windows venv launchers can add an interpreter beneath Popen's PID.
            # Read the executing parent's identity from that real child process.
            executing_parent_pid = int(await asyncio.to_thread(parent.stdout.readline))
            assert _win_parent_map()[child_pid] == executing_parent_pid
            process = psutil.Process()
            before = process.num_handles()
            for _ in range(50):
                parents = _win_parent_map()
                assert parents[parent.pid] == process.pid
                assert parents[child_pid] == executing_parent_pid
            assert process.num_handles() <= before

    @pytest.mark.asyncio
    async def test_closed_job_accounting_is_unknown() -> None:
        containment = ProcessContainment.create()
        containment.close()
        assert containment._win_active_processes(_win_kernel32()) is None
        assert not await containment._terminate_win_job(kill_timeout=0.2)

else:

    def test_assignment_rejects_a_process_in_an_unowned_group() -> None:
        containment = ProcessContainment.create()
        foreign = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"]
        )
        try:
            with pytest.raises(ProcessContainmentError, match="new session"):
                containment.assign(foreign.pid)
            assert not containment.assigned
            assert containment._pid is None
            assert foreign.poll() is None
        finally:
            foreign.kill()
            foreign.wait(timeout=10)
            containment.close()

    @pytest.mark.asyncio
    async def test_proc_and_ps_observe_orphaned_and_zombie_group_members() -> None:
        async with _owned_tree(_STUBBORN_CHILD) as (containment, parent, child_pid):
            pgid = os.getpgid(parent.pid)
            parent.kill()
            parent.wait(timeout=10)
            assert _posix_group_is_live(pgid) is True
            # Exercise the macOS probe against the real ps boundary on Linux too.
            assert _ps_group_is_live(pgid) is True
            assert await containment.terminate(term_timeout=0.2, kill_timeout=5.0)
            assert _posix_group_is_live(pgid) is False
            assert _ps_group_is_live(pgid) is False
            assert not pid_is_live(child_pid)
