"""A worker that never becomes ready must not leave its tree behind.

When the readiness wait expires, `_spawn_worker` reports the spawn as failed by
returning ``None``. Anything still alive at that point is an orphan holding the
worker port, and the next spawn meets its own leftover there and refuses it as
an unidentified occupant - so an incomplete reap wedges the band rather than
merely leaking a process.

These drive the production reap seam with REAL process trees: a parent that
spawns real grandchildren, reaped through the same function the readiness
timeout calls. Both bands are covered, because they take different paths - the
armed desktop gateway owns an OS containment, Compose and development do not.

The grandchildren are what make these tests discriminating. A bare
``Popen.terminate`` fells the parent and passes any parent-only assertion, so a
test that watched only the parent would go green against the defect this covers.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import time

import pytest

from ...control.worker_management import _reap_unready_worker
from ...lifecycle.discovery import is_pid_alive
from ...utils import kill_pid_tree_async
from ...utils.process import ProcessContainment

# A stand-in for the half-started worker: spawns real grandchildren, prints their
# pids so the test can watch them independently of the parent, then sleeps well
# past the test's own patience. Deliberately ignores SIGTERM on POSIX so the
# escalation to SIGKILL is exercised rather than assumed - a reap that only ever
# sends SIGTERM would hang here instead of passing.
_WORKER_WITH_CHILDREN = (
    "import signal, subprocess, sys, time\n"
    "if hasattr(signal, 'SIGTERM'):\n"
    "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "kids = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])"
    " for _ in range(2)]\n"
    "print(' '.join(str(k.pid) for k in kids), flush=True)\n"
    "time.sleep(300)\n"
)


def _spawn_tree(
    containment: ProcessContainment | None,
) -> tuple[subprocess.Popen[bytes], list[int]]:
    """Spawn the stand-in worker and return it with its real grandchild pids."""
    new_session = containment is not None and bool(
        containment.spawn_kwargs().get("start_new_session")
    )
    process = subprocess.Popen(
        [sys.executable, "-c", _WORKER_WITH_CHILDREN],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=new_session,
    )
    if containment is not None:
        containment.assign(process.pid)
    assert process.stdout is not None
    line = process.stdout.readline().decode("utf-8").strip()
    child_pids = [int(p) for p in line.split()]
    assert len(child_pids) == 2, f"stand-in worker did not report children: {line!r}"
    return process, child_pids


def _await_gone(pids: list[int], *, timeout: float = 20.0) -> list[int]:
    """Wait for every pid to die, returning any survivors."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(is_pid_alive(p) for p in pids):
        time.sleep(0.05)
    return [p for p in pids if is_pid_alive(p)]


async def _force_cleanup(pids: list[int]) -> None:
    """Last-resort teardown so a failing assertion cannot leak real processes."""
    for pid in pids:
        if is_pid_alive(pid):
            with contextlib.suppress(Exception):
                await kill_pid_tree_async(pid, term_timeout=2.0, kill_timeout=2.0)


@pytest.mark.asyncio
async def test_unready_worker_tree_is_reaped_without_a_containment() -> None:
    """The Compose / development band reaps the whole tree, not just the root.

    This band has no OS containment, which is exactly where a bare
    ``Popen.terminate`` used to leave both grandchildren running.
    """
    process, child_pids = _spawn_tree(None)
    try:
        await _reap_unready_worker(process, None)

        assert process.poll() is not None, "the worker root survived the reap"
        survivors = _await_gone(child_pids)
        assert not survivors, f"worker descendants survived the reap: {survivors}"
    finally:
        await _force_cleanup([process.pid, *child_pids])


@pytest.mark.asyncio
async def test_unready_worker_tree_is_reaped_through_its_containment() -> None:
    """The armed desktop band reaps the tree through its OS containment."""
    containment = ProcessContainment.create()
    process, child_pids = _spawn_tree(containment)
    try:
        await _reap_unready_worker(process, containment)

        assert process.poll() is not None, "the worker root survived the reap"
        survivors = _await_gone(child_pids)
        assert not survivors, f"worker descendants survived the reap: {survivors}"
    finally:
        await _force_cleanup([process.pid, *child_pids])


@pytest.mark.asyncio
async def test_the_reaped_handle_is_waited_so_no_zombie_remains() -> None:
    """The Popen handle is reaped, not just signalled.

    On POSIX an unwaited terminated child stays a zombie in the process table.
    ``returncode`` is only populated by a successful wait, so asserting it is
    set is the portable way to prove the handle was actually collected.
    """
    process, child_pids = _spawn_tree(None)
    try:
        await _reap_unready_worker(process, None)

        assert process.returncode is not None, (
            "the worker handle was never waited; a zombie would remain on POSIX"
        )
    finally:
        await _force_cleanup([process.pid, *child_pids])
