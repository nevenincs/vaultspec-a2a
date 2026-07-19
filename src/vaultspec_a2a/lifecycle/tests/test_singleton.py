"""Real multi-process certification of the desktop runtime singleton.

These tests spawn real child interpreters that acquire and hold the operating-
system lock, so exclusion, stale detection after a real kill, and refusal to take
over a live holder are proven against genuine process boundaries rather than an
in-process stand-in. No mock, monkeypatch, stub, skip, or expected failure is
used; child processes are always torn down in a ``finally``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.lifecycle.singleton import (
    SingletonConflictError,
    SingletonHeldError,
    SingletonState,
    acquire_singleton,
    classify_app_home,
    default_owner,
    singleton_record_path,
)

if TYPE_CHECKING:
    from pathlib import Path

# A child interpreter that acquires the singleton for (app_home, owner), signals
# its outcome into a ready file, then holds the lock until a stop file appears.
_CHILD = """
import sys, time
from pathlib import Path
from vaultspec_a2a.lifecycle.singleton import (
    acquire_singleton, SingletonConflictError, SingletonHeldError,
)
app_home, owner, ready, stop = (Path(sys.argv[1]), sys.argv[2],
                                Path(sys.argv[3]), Path(sys.argv[4]))
try:
    singleton = acquire_singleton(app_home, owner=owner)
except SingletonHeldError:
    ready.write_text("HELD")
    sys.exit(7)
except SingletonConflictError:
    ready.write_text("CONFLICT")
    sys.exit(7)
ready.write_text("ACQUIRED:%d" % singleton.record.pid)
try:
    while not stop.exists():
        time.sleep(0.05)
finally:
    singleton.release()
"""


def _spawn_holder(
    tmp_path: Path, app_home: Path, owner: str, tag: str
) -> tuple[subprocess.Popen[bytes], Path, Path]:
    """Spawn a child that acquires and holds the singleton; return it and its files."""
    ready = tmp_path / f"{tag}.ready"
    stop = tmp_path / f"{tag}.stop"
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(app_home), owner, str(ready), str(stop)],
        env=os.environ.copy(),
    )
    return proc, ready, stop


def _await_file(path: Path, *, timeout: float = 20.0) -> str:
    """Block until *path* exists and return its text, or fail the test on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text()
            if text:
                return text
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _await_exit(proc: subprocess.Popen[bytes], *, timeout: float = 20.0) -> int:
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive teardown
        proc.kill()
        proc.wait(timeout=timeout)
        raise


def test_live_holder_excludes_every_other_claimant(tmp_path: Path) -> None:
    """A live child owner blocks in-process foreign and same-owner acquisition."""
    app_home = tmp_path / "app"
    proc, ready, stop = _spawn_holder(tmp_path, app_home, "alice", "holder")
    try:
        outcome = _await_file(ready)
        assert outcome.startswith("ACQUIRED:")

        state, record = classify_app_home(app_home, owner="bob")
        assert state is SingletonState.FOREIGN
        assert record is not None and record.owner == "alice"

        with pytest.raises(SingletonConflictError) as foreign:
            acquire_singleton(app_home, owner="bob")
        assert foreign.value.state is SingletonState.FOREIGN

        with pytest.raises(SingletonHeldError) as held:
            acquire_singleton(app_home, owner="alice")
        assert held.value.state is SingletonState.HELD
    finally:
        stop.touch()
        _await_exit(proc)


def test_second_process_cannot_acquire_a_live_home(tmp_path: Path) -> None:
    """A second real child process refuses a home a live child already owns."""
    app_home = tmp_path / "app"
    holder, ready, stop = _spawn_holder(tmp_path, app_home, "alice", "holder")
    try:
        assert _await_file(ready).startswith("ACQUIRED:")

        contender, ready2, _stop2 = _spawn_holder(
            tmp_path, app_home, "bob", "contender"
        )
        try:
            assert _await_file(ready2) == "CONFLICT"
            assert _await_exit(contender) == 7
        finally:
            if contender.poll() is None:  # pragma: no cover - defensive teardown
                contender.kill()
                contender.wait(timeout=10)
    finally:
        stop.touch()
        _await_exit(holder)


def test_stale_record_after_real_kill_permits_owner_takeover(tmp_path: Path) -> None:
    """A killed holder leaves a STALE record its owner may take over."""
    app_home = tmp_path / "app"
    proc, ready, _stop = _spawn_holder(tmp_path, app_home, "alice", "holder")
    dead_pid = 0
    try:
        outcome = _await_file(ready)
        dead_pid = int(outcome.split(":", 1)[1])
    finally:
        proc.terminate()
        _await_exit(proc)

    # The killed holder left its record behind; with its process dead it is STALE.
    assert singleton_record_path(app_home).exists()
    state, record = classify_app_home(app_home, owner="alice")
    assert state is SingletonState.STALE
    assert record is not None and record.pid == dead_pid

    # A foreign owner may not quarantine another owner's stale record.
    with pytest.raises(SingletonConflictError) as foreign:
        acquire_singleton(app_home, owner="bob")
    assert foreign.value.state is SingletonState.STALE

    # The matching owner takes over atomically.
    singleton = acquire_singleton(app_home, owner="alice")
    try:
        assert singleton.record.pid == os.getpid()
        assert singleton.record.pid != dead_pid
        assert classify_app_home(app_home, owner="alice")[0] is SingletonState.HELD
    finally:
        singleton.release()

    # A clean release clears the record so the next start reads FREE.
    assert classify_app_home(app_home, owner="alice")[0] is SingletonState.FREE


def test_absent_home_is_free_and_acquires_cleanly(tmp_path: Path) -> None:
    """An untouched application home classifies FREE and acquires without conflict."""
    app_home = tmp_path / "app"
    assert classify_app_home(app_home)[0] is SingletonState.FREE
    singleton = acquire_singleton(app_home)
    try:
        assert singleton.owner == default_owner()
        assert classify_app_home(app_home)[0] is SingletonState.HELD
    finally:
        singleton.release()
    assert classify_app_home(app_home)[0] is SingletonState.FREE


def test_malformed_record_reads_malformed(tmp_path: Path) -> None:
    """An unreadable owner record classifies MALFORMED rather than crashing a reader."""
    app_home = tmp_path / "app"
    record_path = singleton_record_path(app_home)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text("{ not json", encoding="utf-8")
    assert classify_app_home(app_home)[0] is SingletonState.MALFORMED
