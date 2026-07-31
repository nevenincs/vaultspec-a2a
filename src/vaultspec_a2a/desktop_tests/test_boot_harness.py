"""Real-process proof that a failed gateway boot leaves nothing running.

The shared boot helper hands a spawned gateway to its caller only on success,
so a boot that never reaches readiness has no other owner: the caller's context
manager is still blocked inside the helper and will never see a handle to reap.
Before this was closed, every such failure leaked one live gateway tree, and a
few of them starved the machine until unrelated later boots timed out as well -
one real failure becoming a cascade of false ones.

The subject is process ownership, so the child here is a real process that
genuinely stays alive and genuinely never serves readiness. It is not a stand-in
for the gateway: the helper under test only ever observes ``poll()`` and an HTTP
probe, and both observations are real.
"""

from __future__ import annotations

import _thread
import subprocess
import sys
import threading
from typing import TYPE_CHECKING

import pytest

from ..lifecycle.discovery import is_pid_alive
from ..tests.gateway_boot import (
    GatewayBootError,
    spawn_until_ready,
)

if TYPE_CHECKING:
    from pathlib import Path

# Long enough that the child cannot plausibly exit on its own within the test,
# so "gone afterwards" can only mean the helper reaped it.
_SLEEPER = "import time; time.sleep(600)"


def test_a_gateway_that_never_becomes_ready_is_reaped(tmp_path: Path) -> None:
    """An alive-but-unready boot fails loudly AND leaves no live process.

    Discriminating on three points:

    - The failure is a plain readiness failure, NOT :class:`GatewayBootError`.
      That distinction is the whole point of the branch under test: a child that
      died on its own is retried and needs no reaping, while this one is alive
      at the deadline and is the case that used to leak.
    - The child was really alive when the helper gave up - asserted through the
      real operating-system liveness predicate before the deadline is reached,
      via a process that sleeps far longer than the test.
    - It is gone afterwards, checked both on the handle and independently
      through the same operating-system predicate. Remove the reap and the
      process is still running here.
    """
    spawned: list[subprocess.Popen[bytes]] = []
    log_path = tmp_path / "boot.log"
    log_handle = log_path.open("wb")

    def _spawn(_gateway_port: int, _worker_port: int) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            [sys.executable, "-c", _SLEEPER],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        spawned.append(proc)
        # Alive at spawn time, through the real predicate: the assertion below
        # about it being gone is only meaningful because it was here first.
        assert is_pid_alive(proc.pid), "the sleeper never started"
        return proc

    try:
        with pytest.raises(AssertionError) as caught:
            spawn_until_ready(_spawn, log_path=log_path, attempts=1, timeout=5.0)

        # A live-but-unready gateway, not a dead one: the retry branch would
        # have swallowed this, and the leak lived on the path taken here.
        assert not isinstance(caught.value, GatewayBootError), caught.value
        assert "readiness never came up" in str(caught.value), caught.value

        assert len(spawned) == 1, spawned
        proc = spawned[0]
        assert proc.poll() is not None, "the unready gateway was left running"
        assert not is_pid_alive(proc.pid), "the unready gateway tree survived"
    finally:
        for proc in spawned:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        log_handle.close()


def test_an_interrupted_boot_is_reaped(tmp_path: Path) -> None:
    """An interrupt during the readiness wait reaps the child before propagating.

    The complement to the deadline case, and the one least likely to be noticed
    in practice: a suite cancelled part-way through a boot leaves the gateway
    running for the rest of the session and beyond it. ``KeyboardInterrupt``
    derives from :class:`BaseException`, not :class:`Exception`, so an
    ``except Exception`` guard would let it past untouched - which is exactly
    the branch under test.

    The interrupt is a REAL one, delivered into the main thread by the
    interpreter's own ``_thread.interrupt_main`` while the production readiness
    poll is genuinely running; nothing about the helper is patched or replaced.
    """
    spawned: list[subprocess.Popen[bytes]] = []
    log_path = tmp_path / "boot.log"
    log_handle = log_path.open("wb")
    # Fires while await_gateway_ready is polling: long enough that the poll is
    # certainly under way, far short of the readiness timeout below.
    interrupter = threading.Timer(2.0, _thread.interrupt_main)

    def _spawn(_gateway_port: int, _worker_port: int) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            [sys.executable, "-c", _SLEEPER],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        spawned.append(proc)
        assert is_pid_alive(proc.pid), "the sleeper never started"
        interrupter.start()
        return proc

    try:
        with pytest.raises(KeyboardInterrupt):
            spawn_until_ready(_spawn, log_path=log_path, attempts=1, timeout=120.0)

        # The interrupt propagated - the helper did not swallow a cancellation -
        # and the child it owned did not outlive it.
        assert len(spawned) == 1, spawned
        proc = spawned[0]
        assert proc.poll() is not None, "the interrupted gateway was left running"
        assert not is_pid_alive(proc.pid), "the interrupted gateway tree survived"
    finally:
        interrupter.cancel()
        for proc in spawned:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        log_handle.close()
