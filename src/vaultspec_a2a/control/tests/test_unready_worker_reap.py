"""A worker that never becomes ready must not leave its tree behind.

When the readiness wait expires, `_spawn_worker` reports the spawn as failed by
returning ``None``. Anything still alive at that point is an orphan holding the
worker port, and the next spawn meets its own leftover there and refuses it as
an unidentified occupant - so an incomplete reap wedges the band rather than
merely leaking a process.

These drive the production reap seam with REAL process trees: a parent that
spawns real grandchildren, reaped through the same function the readiness
timeout calls. Every stand-in is started through the same contained spawn as a
gateway-owned worker, so its containment is the only authority for the tree.

The grandchildren are what make these tests discriminating. A bare
``Popen.terminate`` fells the parent and passes any parent-only assertion, so a
test that watched only the parent would go green against the defect this covers.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ...control._worker_process_stop import _shutdown_worker_process
from ...control._worker_readiness import _reap_unready_worker
from ...control.worker_management import LazyWorkerSpawner
from ...lifecycle.shutdown import ShutdownDeadline
from ...testing import free_port
from ...utils import (
    ProcessContainment,
    ProcessContainmentError,
    kill_pid_tree_async,
    spawn_contained,
)
from ...utils._process_tree import pid_is_live, port_has_listener_async, wait_pid_gone

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


def _cooperative_worker_script(port: int, marker: Path) -> str:
    """Return a stdlib HTTP worker that exits cooperatively but leaves a child."""
    return (
        "import http.server, pathlib, subprocess, sys, threading\n"
        "kid=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'])\n"
        f"path=pathlib.Path({str(marker)!r})\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        " def log_message(self,*args): pass\n"
        " def do_POST(self):\n"
        "  if self.path != '/admin/shutdown':\n"
        "   self.send_response(404); self.end_headers(); return\n"
        "  path.write_text(str(kid.pid), encoding='utf-8')\n"
        "  self.send_response(202); self.end_headers()\n"
        "  threading.Thread(target=server.shutdown, daemon=True).start()\n"
        f"server=http.server.ThreadingHTTPServer(('127.0.0.1',{port}),H)\n"
        "server.serve_forever(); server.server_close()\n"
    )


def _late_child_worker_script(port: int, marker: Path) -> str:
    """Return a worker that creates its only child while handling shutdown."""
    return (
        "import http.server, pathlib, subprocess, sys, threading\n"
        f"path=pathlib.Path({str(marker)!r})\n"
        "class H(http.server.BaseHTTPRequestHandler):\n"
        " def log_message(self,*args): pass\n"
        " def do_POST(self):\n"
        "  if self.path != '/admin/shutdown':\n"
        "   self.send_response(404); self.end_headers(); return\n"
        "  kid=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'])\n"
        "  path.write_text(str(kid.pid), encoding='utf-8')\n"
        "  self.send_response(202); self.end_headers()\n"
        "  threading.Thread(target=server.shutdown, daemon=True).start()\n"
        f"server=http.server.ThreadingHTTPServer(('127.0.0.1',{port}),H)\n"
        "server.serve_forever(); server.server_close()\n"
    )


def _base_interpreter() -> str:
    # A uv-managed Windows venv executable is a redirector process.  Use the
    # retained base interpreter so the returned Popen is the actual worker root
    # whose identity and descendants production cleanup must own.
    return getattr(sys, "_base_executable", sys.executable)


def _spawn_tree(
    containment: ProcessContainment,
) -> tuple[subprocess.Popen[bytes], list[int]]:
    """Spawn the stand-in worker and return it with its real grandchild pids."""
    process = spawn_contained(
        [_base_interpreter(), "-c", _WORKER_WITH_CHILDREN],
        containment,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert process.stdout is not None
    line = process.stdout.readline().decode("utf-8").strip()
    child_pids = [int(p) for p in line.split()]
    assert len(child_pids) == 2, f"stand-in worker did not report children: {line!r}"
    return process, child_pids


async def _serving_contained_worker(
    script: str, port: int
) -> tuple[subprocess.Popen[bytes], ProcessContainment, LazyWorkerSpawner]:
    """Run *script* in real containment, owned by a spawner, once it serves *port*."""
    containment = ProcessContainment.create()
    process = spawn_contained(
        [_base_interpreter(), "-c", script],
        containment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    spawner = LazyWorkerSpawner(
        worker_url=f"http://127.0.0.1:{port}", worker_port=port, auto_spawn=False
    )
    spawner.replace_process(process, containment)
    ready_deadline = time.monotonic() + 5.0
    while time.monotonic() < ready_deadline:
        if await port_has_listener_async(port, timeout=0.5):
            return process, containment, spawner
        await asyncio.sleep(0.02)
    await containment.terminate(term_timeout=2.0, kill_timeout=2.0)
    raise AssertionError("contained worker socket did not become ready")


def _await_gone(pids: list[int], *, timeout: float = 20.0) -> list[int]:
    """Wait for every pid to die, returning any survivors."""
    wait_pid_gone(*pids, timeout=timeout)
    return [p for p in pids if pid_is_live(p)]


async def _force_cleanup(pids: list[int]) -> None:
    """Last-resort teardown so a failing assertion cannot leak real processes."""
    for pid in pids:
        if pid_is_live(pid):
            with contextlib.suppress(Exception):
                await kill_pid_tree_async(pid, term_timeout=2.0, kill_timeout=2.0)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job assignment proof")
def test_refused_admission_kills_the_root_before_its_first_instruction(
    tmp_path: Path,
) -> None:
    """A real closed Job cannot admit the worker root, and the root never runs."""
    marker = tmp_path / "worker-first-instruction"
    script = f"from pathlib import Path; Path({str(marker)!r}).touch()"
    containment = ProcessContainment.create()
    containment.close()
    started = time.monotonic()
    with pytest.raises(ProcessContainmentError, match="no job object") as caught:
        spawn_contained([_base_interpreter(), "-c", script], containment)
    elapsed = time.monotonic() - started
    assert elapsed < 10.5, f"refused-admission reap took {elapsed:.4f}s"
    pid_match = re.search(r"process (\d+)", str(caught.value))
    assert pid_match is not None
    assert not marker.exists(), "the worker root ran before its admission failed"
    assert not pid_is_live(int(pid_match.group(1))), "refused root left live"


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
    containment = ProcessContainment.create()
    process, child_pids = _spawn_tree(containment)
    try:
        await _reap_unready_worker(process, containment)

        assert process.returncode is not None, (
            "the worker handle was never waited; a zombie would remain on POSIX"
        )
    finally:
        await _force_cleanup([process.pid, *child_pids])
        containment.close()


@pytest.mark.asyncio
async def test_shutdown_reaps_descendants_after_worker_root_crashes() -> None:
    containment = ProcessContainment.create()
    process, child_pids = _spawn_tree(containment)
    try:
        process.kill()
        process.wait(timeout=5)
        assert all(pid_is_live(pid) for pid in child_pids)

        await _shutdown_worker_process(process, containment)

        assert not _await_gone(child_pids)
    finally:
        await _force_cleanup([process.pid, *child_pids])
        containment.close()
        if process.stdout is not None:
            process.stdout.close()


@pytest.mark.asyncio
async def test_spawner_shutdown_clears_crashed_tree_before_replacement() -> None:
    containment = ProcessContainment.create()
    process, child_pids = _spawn_tree(containment)
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
    )
    spawner.replace_process(process, containment)
    try:
        process.kill()
        process.wait(timeout=5)
        await spawner.shutdown()

        assert spawner.process is None
        assert spawner.containment is None
        assert not _await_gone(child_pids)
        await spawner.shutdown()
    finally:
        await _force_cleanup([process.pid, *child_pids])
        containment.close()
        if process.stdout is not None:
            process.stdout.close()


@pytest.mark.asyncio
async def test_cancelled_shutdown_joins_worker_reap() -> None:
    containment = ProcessContainment.create()
    process, child_pids = _spawn_tree(containment)
    try:
        cleanup = asyncio.create_task(_shutdown_worker_process(process, containment))
        await asyncio.sleep(0)
        for _ in range(3):
            cleanup.cancel()
            await asyncio.sleep(0)
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(cleanup, timeout=25)

        assert process.poll() is not None
        assert not _await_gone(child_pids)
    finally:
        await _force_cleanup([process.pid, *child_pids])
        containment.close()
        if process.stdout is not None:
            process.stdout.close()


@pytest.mark.asyncio
async def test_spawner_cooperates_then_reaps_the_remaining_owned_tree(
    tmp_path: Path,
) -> None:
    """A real 202 stop precedes bounded containment escalation for descendants."""
    port = free_port()
    marker = tmp_path / "cooperative-stop.txt"
    process, containment, spawner = await _serving_contained_worker(
        _cooperative_worker_script(port, marker), port
    )

    started = asyncio.get_running_loop().time()
    deadline = ShutdownDeadline.start(4.0)
    try:
        await spawner.shutdown(deadline=deadline)
        elapsed = asyncio.get_running_loop().time() - started
        assert marker.exists(), "the cooperative shutdown route was not reached"
        child_pid = int(marker.read_text(encoding="utf-8"))
        assert elapsed < 4.2, f"owned worker teardown took {elapsed:.4f}s"
        assert process.poll() is not None
        assert not pid_is_live(child_pid), "owned descendant survived escalation"
        assert spawner.process is None and spawner.containment is None
    finally:
        child_pids: list[int] = []
        if marker.exists():
            child_pids.append(int(marker.read_text(encoding="utf-8")))
        await _force_cleanup([process.pid, *child_pids])
        containment.close()


@pytest.mark.asyncio
async def test_shutdown_reaps_child_created_after_cooperative_request(
    tmp_path: Path,
) -> None:
    """Containment authority survives a root that exits after creating a child."""
    port = free_port()
    marker = tmp_path / "late-child.txt"
    process, containment, spawner = await _serving_contained_worker(
        _late_child_worker_script(port, marker), port
    )

    started = asyncio.get_running_loop().time()
    deadline = ShutdownDeadline.start(4.0)
    try:
        await spawner.shutdown(deadline=deadline)
        elapsed = asyncio.get_running_loop().time() - started
        assert marker.exists(), "shutdown request did not create the late child"
        child_pid = int(marker.read_text(encoding="utf-8"))
        assert elapsed < 4.2, f"late-child teardown took {elapsed:.4f}s"
        assert process.poll() is not None
        assert not pid_is_live(child_pid), "late descendant survived root exit"
    finally:
        child_pids: list[int] = []
        if marker.exists():
            child_pids.append(int(marker.read_text(encoding="utf-8")))
        await _force_cleanup([process.pid, *child_pids])
        containment.close()
