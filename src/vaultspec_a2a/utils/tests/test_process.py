"""Real-process tests for the process-introspection backend and tree kill.

Real subprocesses, no mocks: a process that spawns a grandchild is felled whole,
so no orphan survives (the Windows taskkill /T behaviour the two former copies
existed to provide). Liveness is asserted with the canonical pid_is_live probe,
and listener ownership is read from the spawned tree's own sockets.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from typing import Any

import pytest

from ...lifecycle.manager import _await_listener
from ...testing import free_port
from ...utils._process_tree import (
    ListenerOwnership,
    _win_tree_kill,
    classify_listener_ownership,
    descendant_pids,
    kill_pid_tree_async,
    pid_is_live,
    port_has_listener,
    port_has_listener_async,
    process_start_identity,
    wait_pid_gone,
)

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
        assert pid_is_live(grandchild_pid)

        killed = await kill_pid_tree_async(
            parent.pid, term_timeout=10.0, kill_timeout=5.0
        )
        parent.wait(timeout=10)

        assert killed is True
        assert parent.poll() is not None
        # The grandchild is felled with the parent — no orphan.
        assert wait_pid_gone(grandchild_pid, timeout=10.0)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if pid_is_live(grandchild_pid):
            await kill_pid_tree_async(grandchild_pid)


def test_pid_is_live_separates_this_process_from_an_unallocated_pid() -> None:
    assert pid_is_live(os.getpid()) is True
    assert pid_is_live(2**31 - 1) is False


def test_pid_is_live_reports_a_killed_but_unreaped_child_as_dead() -> None:
    """A dead child is dead before its owner reaps it.

    The POSIX trap this guards: an exited child keeps answering a signal-0 probe
    until its parent waits on it, so a probe that stops at signal 0 would call
    this killed process alive for as long as the test holds off its ``wait()`` -
    and every kill path polling that probe would wait out its whole escalation and
    then report failure. The reap deliberately happens only in the ``finally``.
    """
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert pid_is_live(child.pid)
        child.kill()
        wait_pid_gone(child.pid, timeout=10.0)
        # Still unreaped at this point: no wait()/poll() has run, and the probe
        # itself must not reap (``poll()`` here would consume the exit status and
        # hide the very state under test).
        assert child.returncode is None
        assert not pid_is_live(child.pid)
    finally:
        child.wait(timeout=10)
    # The owner still collects the real exit status: the probe consumed nothing.
    assert child.returncode is not None


def test_start_identity_is_stable_and_tells_two_processes_apart() -> None:
    """The pid-reuse guard reads one stamp per process start, not one per read."""
    own = process_start_identity(os.getpid())
    if sys.platform != "win32" and not sys.platform.startswith("linux"):
        # No clock-independent stamp is read on this host; callers degrade to
        # pid-liveness alone.
        assert own is None
        return
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert own is not None
        assert process_start_identity(os.getpid()) == own
        assert process_start_identity(child.pid) not in {None, own}
    finally:
        child.kill()
        child.wait(timeout=10)


def test_descendant_walk_finds_a_grandchild() -> None:
    """The walk reaches a grandchild on every host.

    The POSIX tree kill signals the snapshot it returns, and the listener
    ownership verdict reads the sockets of every member it lists.
    """
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    grandchild_pid = int(parent.stdout.readline().strip())
    try:
        assert grandchild_pid in descendant_pids(parent.pid)
        assert parent.pid not in descendant_pids(parent.pid)
    finally:
        parent.kill()
        parent.wait()
        if pid_is_live(grandchild_pid):
            asyncio.run(kill_pid_tree_async(grandchild_pid))


@pytest.mark.asyncio
async def test_kill_pid_tree_on_an_already_dead_pid_is_success() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert await kill_pid_tree_async(proc.pid) is True


@pytest.mark.asyncio
async def test_kill_pid_tree_nonpositive_pid_is_success() -> None:
    assert await kill_pid_tree_async(0) is True
    assert await kill_pid_tree_async(-1) is True


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="only the Windows path shells out to taskkill; POSIX signals with "
    "os.kill, which does not block, so it has no wait to bound",
)
@pytest.mark.asyncio
async def test_the_taskkill_wait_is_bounded_by_the_callers_kill_budget() -> None:
    """A killer that outlives the budget is felled rather than waited on.

    ``taskkill`` normally returns in well under a second, but nothing here
    guarantees that: a wedged one must not hang the caller - and every
    synchronous caller reaches this through ``lifecycle.manager.tree_kill``'s
    ``asyncio.run`` wrapper, which has no escape from a hang of its own. Handing
    the seam an already-spent budget drives the timeout branch against a real
    ``taskkill`` process rather than a stand-in. The assertion is the property
    the bound is for: the call comes back on its own budget instead of waiting
    on the killer, felling it and bounding the reap at 1.0s (the literal in
    :func:`_win_tree_kill`'s except branch) rather than the pathological case
    in the wild.
    """
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        spent = time.monotonic()
        await _win_tree_kill(child.pid, timeout=0.0)
        elapsed = time.monotonic() - spent
        assert elapsed <= 3.0
    finally:
        await kill_pid_tree_async(child.pid)
        assert wait_pid_gone(child.pid, timeout=10.0)


# A process that binds a fresh loopback port, prints it, then holds it open.
_BIND_AND_HOLD = (
    "import socket,sys,time;"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',0));s.listen(5);"
    "print(s.getsockname()[1],flush=True);"
    "time.sleep(120)"
)
_SLEEP = "import time; time.sleep(120)"
# A parent that hands the listener script (its argv[1]) to its OWN child, so the
# listener is a descendant of the pid the test spawns rather than that pid.
_SPAWN_LISTENING_GRANDCHILD = (
    "import subprocess,sys,time;"
    "g=subprocess.Popen([sys.executable,'-c',sys.argv[1]],"
    "stdout=subprocess.PIPE,text=True);"
    "print(g.stdout.readline().strip(),flush=True);"
    "time.sleep(120)"
)


def _spawn_listener() -> tuple[subprocess.Popen[str], int]:
    """Spawn a real child that holds a loopback port; return it and the port."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _BIND_AND_HOLD], stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    port = int(proc.stdout.readline().strip())
    return proc, port


def _reap(*procs: subprocess.Popen[Any]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_wait_pid_gone_reports_a_live_and_then_a_dead_pid() -> None:
    """The termination gate is ``True`` only once the pid is actually gone."""
    child = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        # A live pid is not confirmed gone within a short window.
        assert wait_pid_gone(child.pid, timeout=0.3) is False
        child.kill()
        assert wait_pid_gone(child.pid, timeout=10.0) is True
    finally:
        _reap(child)


@pytest.mark.asyncio
async def test_port_has_listener_true_on_a_real_listener_false_on_a_free_port() -> None:
    """Both connect-probe forms: a real listener answers, a free port does not."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    # Room for both probes' connections, which nothing here accepts.
    sock.listen(8)
    bound_port = sock.getsockname()[1]
    try:
        assert port_has_listener(bound_port, timeout=1.0) is True
        assert await port_has_listener_async(bound_port, timeout=1.0) is True
    finally:
        sock.close()
    # Once closed, the same port no longer accepts a connect.
    assert port_has_listener(bound_port, timeout=0.5) is False
    assert await port_has_listener_async(bound_port, timeout=0.5) is False


def test_ownership_classification_confirms_a_descendant_listener() -> None:
    """A listener bound by a descendant of the root, not the root, is ours.

    This is the per-process socket query the ownership gate rests on, run
    without elevation over a real tree: the root holds no socket, its child
    does. A Windows venv host deepens the tree further, since ``python.exe`` is
    a launcher stub whose interpreter child is the real binder.
    """
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_LISTENING_GRANDCHILD, _BIND_AND_HOLD],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    try:
        port = int(parent.stdout.readline().strip())
        assert classify_listener_ownership(port, parent.pid) is (
            ListenerOwnership.CONFIRMED
        )
    finally:
        asyncio.run(kill_pid_tree_async(parent.pid))
        _reap(parent)


def test_await_listener_accepts_a_port_our_child_owns() -> None:
    listener, port = _spawn_listener()
    try:
        assert _await_listener(port, listener, timeout=10.0) is True
    finally:
        _reap(listener)


def test_await_listener_rejects_a_foreign_port_holder() -> None:
    """The fix: a foreign process holding the port never reads as our child ready.

    Stands in for a failed-eviction / racer scenario without an unkillable
    process: a real listener holds the port while a DIFFERENT live child (which
    never bound it) is the one whose readiness we probe. Before the owner check
    this returned ready on the stranger's listener; now it must time out to False
    because the listening pid is outside the probed process's tree.
    """
    holder, port = _spawn_listener()
    not_the_binder = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        assert not_the_binder.poll() is None  # the probed child is alive...
        assert _await_listener(port, not_the_binder, timeout=3.0) is False
    finally:
        _reap(holder, not_the_binder)


def test_ownership_classification_reads_the_tree_not_the_port() -> None:
    """Only a port the root's own tree listens on is ours.

    The verdict reads the sockets of the root and its descendants, never the
    host table, so a port nobody in the tree holds is ``OUTSIDE`` whether or not
    anything else listens there. A fully readable tree never reads as
    ``UNRESOLVED``: that verdict is reserved for a member whose sockets could not
    be read.
    """
    listener, port = _spawn_listener()
    try:
        assert classify_listener_ownership(port, listener.pid) is (
            ListenerOwnership.CONFIRMED
        )
        assert classify_listener_ownership(free_port(), listener.pid) is (
            ListenerOwnership.OUTSIDE
        )
    finally:
        _reap(listener)


def test_ownership_classification_of_a_gone_root_is_outside() -> None:
    """A tree whose root has exited owns nothing, so it confirms no listener."""
    holder, port = _spawn_listener()
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait(timeout=10)
    try:
        assert classify_listener_ownership(port, gone.pid) is (
            ListenerOwnership.OUTSIDE
        )
    finally:
        _reap(holder)


def test_ownership_classification_reports_a_positively_foreign_holder() -> None:
    """A real listener held outside the root's tree is OUTSIDE."""
    listener, port = _spawn_listener()
    stranger = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        assert classify_listener_ownership(port, stranger.pid) is (
            ListenerOwnership.OUTSIDE
        )
    finally:
        _reap(listener, stranger)
