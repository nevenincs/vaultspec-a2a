"""Real-process tests for the shared async tree-kill primitive.

Real subprocesses, no mocks: a process that spawns a grandchild is felled whole,
so no orphan survives (the Windows taskkill /T behaviour the two former copies
existed to provide). Liveness is asserted with the canonical is_pid_alive probe.
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

from vaultspec_a2a.lifecycle.discovery import is_pid_alive
from vaultspec_a2a.lifecycle.manager import _await_listener
from vaultspec_a2a.utils.process import (
    kill_pid_tree_async,
    listener_belongs_to,
    pid_is_live,
    port_listener_pid,
    posix_descendant_pids,
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
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and pid_is_live(child.pid):
            time.sleep(0.05)
        # Still unreaped at this point: no wait()/poll() has run, and the probe
        # itself must not reap (``poll()`` here would consume the exit status and
        # hide the very state under test).
        assert child.returncode is None
        assert not pid_is_live(child.pid)
    finally:
        child.wait(timeout=10)
    # The owner still collects the real exit status: the probe consumed nothing.
    assert child.returncode is not None


def test_descendant_walk_finds_a_grandchild_per_the_platform_contract() -> None:
    """POSIX enumerates descendants for the tree kill; Windows delegates to taskkill."""
    parent = subprocess.Popen(
        [sys.executable, "-c", _SPAWN_GRANDCHILD],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert parent.stdout is not None
    grandchild_pid = int(parent.stdout.readline().strip())
    try:
        if sys.platform == "win32":
            assert posix_descendant_pids(parent.pid) == []
        else:
            assert grandchild_pid in posix_descendant_pids(parent.pid)
    finally:
        parent.kill()
        parent.wait()
        if is_pid_alive(grandchild_pid):
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


# A process that binds a fresh loopback port, prints it, then holds it open.
_BIND_AND_HOLD = (
    "import socket,sys,time;"
    "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);"
    "s.bind(('127.0.0.1',0));s.listen(5);"
    "print(s.getsockname()[1],flush=True);"
    "time.sleep(120)"
)
_SLEEP = "import time; time.sleep(120)"


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


def test_port_listener_pid_resolves_a_real_listener() -> None:
    """The resolver names a real, live pid holding the loopback port, not a guess.

    Exact equality with the spawned pid does not hold on a Windows venv host,
    where ``python.exe`` is a launcher stub: the pid we spawn launches the real
    interpreter child that actually binds the port, so the listener is a
    descendant. The resolver must still name that real listening pid, and it must
    belong to the spawned tree.
    """
    listener, port = _spawn_listener()
    try:
        resolved = port_listener_pid(port)
        assert resolved is not None
        assert is_pid_alive(resolved)
        assert listener_belongs_to(port, listener.pid) is True
    finally:
        _reap(listener)


def test_listener_belongs_to_accepts_the_owning_process() -> None:
    listener, port = _spawn_listener()
    try:
        assert listener_belongs_to(port, listener.pid) is True
    finally:
        _reap(listener)


def test_listener_belongs_to_rejects_a_positively_foreign_holder() -> None:
    """A port held by one real process is not owned by an unrelated real root."""
    listener, port = _spawn_listener()
    stranger = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        # The listener genuinely holds the port, but the unrelated stranger's tree
        # does not contain the listening pid, so ownership is positively refused.
        assert listener_belongs_to(port, stranger.pid) is False
    finally:
        _reap(listener, stranger)


def test_listener_belongs_to_degrades_to_true_when_no_listener() -> None:
    """An unresolved owner (no listener at all) fails safe, never falsely rejects."""
    free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()  # nothing is listening now
    assert listener_belongs_to(port, os.getpid()) is True


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
