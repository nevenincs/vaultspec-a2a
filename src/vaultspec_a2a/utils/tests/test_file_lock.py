"""The byte-zero file lock releases on a real process crash, not just a clean exit.

A holder that dies mid-lock (killed, not given the chance to release) must not
strand the resource: the kernel releases the lock when the holder's descriptor
table is torn down, crash included. A real child interpreter proves it, since
an in-process stand-in could only prove the primitive releases on its own
``close()`` - the one case nobody doubts.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ...testing import ProgressDeadline, wait_for
from ..file_lock import held_exclusive_lock, open_lock_file, release_lock, try_lock

if TYPE_CHECKING:
    from pathlib import Path

# A child interpreter that takes the byte-zero lock on *path*, signals it holds
# it into *ready*, then blocks until *stop* appears (a clean-exit control arm)
# or the test kills it outright (the crash arm).
_HOLDER = """
import sys, time
from pathlib import Path
from vaultspec_a2a.utils.file_lock import open_lock_file, try_lock, release_lock
path, ready, stop = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
fd = open_lock_file(path)
assert try_lock(fd), "the holder could not take its own fresh lock"
ready.write_text("HELD")
try:
    while not stop.exists():
        time.sleep(0.05)
finally:
    release_lock(fd)
"""


def _spawn_holder(
    tmp_path: Path, path: Path, tag: str
) -> tuple[subprocess.Popen[bytes], Path, Path]:
    ready = tmp_path / f"{tag}.ready"
    stop = tmp_path / f"{tag}.stop"
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(path), str(ready), str(stop)],
        env=os.environ.copy(),
    )
    return proc, ready, stop


def _await_held(ready: Path) -> None:
    wait_for(
        lambda: "HELD" if ready.exists() and ready.read_text() == "HELD" else None,
        deadline=ProgressDeadline(idle_window_s=20.0),
        interval_s=0.05,
        stalled=lambda: f"{ready} never reported HELD",
    )


def _probe_try_lock(path: Path) -> bool:
    """Open a fresh descriptor and attempt the lock once; always closes it."""
    fd = open_lock_file(path)
    try:
        granted = try_lock(fd)
        if granted:
            release_lock(fd)
        return granted
    finally:
        os.close(fd)


def test_a_holder_killed_mid_lock_releases_it_for_the_next_claimant(
    tmp_path: Path,
) -> None:
    """``terminate()`` is a real kill, not a cooperative shutdown - no stop file.

    The OS tears the killed process's handles down asynchronously, so the lock
    table entry can briefly outlive ``Popen.wait()`` returning; this is exactly
    why :func:`held_exclusive_lock` polls rather than asking once, and the
    bounded :func:`wait_for` below asserts nothing stronger than that same
    polling contract.
    """
    path = tmp_path / "crash.lock"
    holder, ready, _stop = _spawn_holder(tmp_path, path, "crash")
    try:
        _await_held(ready)
        still_held = not _probe_try_lock(path)
        assert still_held, "the lock must still be held by the live child"

        holder.terminate()
        holder.wait(timeout=20.0)

        wait_for(
            lambda: True if _probe_try_lock(path) else None,
            deadline=ProgressDeadline(idle_window_s=5.0),
            interval_s=0.1,
            stalled=lambda: f"{path} was never freed after its holder was killed",
        )
    finally:
        if holder.poll() is None:  # pragma: no cover - defensive teardown
            holder.kill()
            holder.wait(timeout=20.0)


def test_held_exclusive_lock_times_out_naming_the_path_while_a_child_holds_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "contended.lock"
    holder, ready, stop = _spawn_holder(tmp_path, path, "contended")
    try:
        _await_held(ready)

        with (
            pytest.raises(TimeoutError, match=r"held the lock at .*contended\.lock"),
            held_exclusive_lock(path, timeout_seconds=0.2, poll_seconds=0.05),
        ):
            pytest.fail("must never be granted while the child holds the lock")
    finally:
        stop.touch()
        holder.wait(timeout=20.0)


def test_held_exclusive_lock_is_granted_once_the_holder_releases(
    tmp_path: Path,
) -> None:
    """The same contended lock is acquirable the instant a clean release frees it."""
    path = tmp_path / "released.lock"
    holder, ready, stop = _spawn_holder(tmp_path, path, "released")
    try:
        _await_held(ready)
    finally:
        stop.touch()
        holder.wait(timeout=20.0)

    with held_exclusive_lock(path, timeout_seconds=5.0, poll_seconds=0.05):
        pass
