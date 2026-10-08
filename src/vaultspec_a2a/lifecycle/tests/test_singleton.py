"""Real multi-process certification of the desktop runtime singleton.

These tests spawn real child interpreters that acquire and hold the operating-
system lock, so exclusion, stale detection after a real kill, and refusal to take
over a live holder are proven against genuine process boundaries rather than an
in-process stand-in. No mock, monkeypatch, stub, skip, or expected failure is
used; every child is started inside OS containment and reaped through it in a
``finally``, so a holder that fails mid-test cannot outlive the test and keep the
lock from the next one.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ...lifecycle.singleton import (
    SINGLETON_RECORD_VERSION,
    SingletonConflictError,
    SingletonHeldError,
    SingletonRecord,
    SingletonState,
    acquire_singleton,
    classify_app_home,
    default_owner,
    singleton_record_path,
)
from ...testing import ProgressDeadline, child_tree_progress, wait_for
from ...utils import ProcessContainment, reap_contained, spawn_contained
from ...utils._process_tree import pid_is_live

if TYPE_CHECKING:
    from collections.abc import Generator
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


@dataclass(frozen=True, slots=True)
class _Holder:
    """A contained child singleton holder and the files it signals through."""

    process: subprocess.Popen[bytes]
    containment: ProcessContainment
    ready: Path
    stop: Path
    log: Path

    def reap(self) -> None:
        """Fell the holder's whole tree and wait its root; idempotent."""
        reap_contained(self.process, self.containment, term_timeout=5.0)

    def diagnosis(self) -> str:
        """Why the holder has not signalled yet, in the child's own words."""
        output = self.log.read_text(encoding="utf-8", errors="replace").strip()
        return (
            f"{self.ready} was never written "
            f"(exit: {self.process.poll()}; child output: {output or '<none>'})"
        )


@contextlib.contextmanager
def _holder(tmp_path: Path, app_home: Path, owner: str, tag: str) -> Generator[_Holder]:
    """A child that acquires and holds the singleton, reaped whatever happens.

    Contained rather than bare: a holder keeps an OS lock on the application home
    for as long as it lives, so one that survives its test does not merely leak a
    process - it fails every later test against that home. The containment owns
    the tree, so the reap needs no pid walk and cannot miss a descendant.

    Its output is captured to a file rather than inherited, because the only thing
    a holder that fails to signal leaves behind is what it printed, and a stall
    message that cannot quote it says nothing about the cause.
    """
    ready = tmp_path / f"{tag}.ready"
    stop = tmp_path / f"{tag}.stop"
    log = tmp_path / f"{tag}.log"
    containment = ProcessContainment.create()
    with log.open("wb") as sink:
        process = spawn_contained(
            [sys.executable, "-c", _CHILD, str(app_home), owner, str(ready), str(stop)],
            containment,
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=sink,
            env=os.environ.copy(),
        )
    holder = _Holder(process, containment, ready, stop, log)
    try:
        yield holder
    finally:
        holder.reap()
        containment.close()


def _await_signal(holder: _Holder, *, timeout: float = 20.0) -> str:
    """Block until the holder signals its outcome, quoting its output on a stall.

    The wait watches the holder's own tree progress, so a cold child still
    importing the package on a loaded host is slow rather than stalled. Without
    that watch the idle window bounded the WHOLE wait, which made a busy machine -
    a full suite run spawning interpreters of its own - read a working child as
    hung.
    """

    def _text() -> str | None:
        return (holder.ready.read_text() if holder.ready.exists() else "") or None

    return wait_for(
        _text,
        deadline=ProgressDeadline(idle_window_s=timeout),
        fingerprint=lambda: child_tree_progress(holder.process.pid),
        interval_s=0.05,
        stalled=holder.diagnosis,
    )


def _await_exit(proc: subprocess.Popen[bytes], *, timeout: float = 20.0) -> int:
    """Wait for a child asked to stop cooperatively; its reap stays with its owner."""
    return proc.wait(timeout=timeout)


def test_live_holder_excludes_every_other_claimant(tmp_path: Path) -> None:
    """A live child owner blocks in-process foreign and same-owner acquisition."""
    app_home = tmp_path / "app"
    with _holder(tmp_path, app_home, "alice", "holder") as holder:
        outcome = _await_signal(holder)
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

        # The cooperative stop proves the holder RELEASES rather than merely
        # dying, which the reap in the context manager's exit cannot show.
        holder.stop.touch()
        assert _await_exit(holder.process) == 0


def test_second_process_cannot_acquire_a_live_home(tmp_path: Path) -> None:
    """A second real child process refuses a home a live child already owns."""
    app_home = tmp_path / "app"
    with _holder(tmp_path, app_home, "alice", "holder") as holder:
        assert _await_signal(holder).startswith("ACQUIRED:")

        with _holder(tmp_path, app_home, "bob", "contender") as contender:
            assert _await_signal(contender) == "CONFLICT"
            assert _await_exit(contender.process) == 7

        holder.stop.touch()
        assert _await_exit(holder.process) == 0


def test_stale_record_after_real_kill_permits_owner_takeover(tmp_path: Path) -> None:
    """A killed holder leaves a STALE record its owner may take over."""
    app_home = tmp_path / "app"
    with _holder(tmp_path, app_home, "alice", "holder") as holder:
        dead_pid = int(_await_signal(holder).split(":", 1)[1])
        # Felled, not asked to stop: the record must be left behind, which a
        # clean release would have cleared.
        holder.reap()
        assert not pid_is_live(dead_pid)

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


def test_a_failed_owner_record_publication_leaves_no_temporary(tmp_path: Path) -> None:
    """A publication that cannot complete must not leave residue behind.

    The owner record is published through the package's audited writer, which
    removes its temporary when the rename fails; a directory standing where the
    record belongs makes the rename fail for real, and the assertion is that the
    runtime directory holds no residue afterwards.
    """
    from ..singleton import _write_record, current_process_fingerprint

    record_path = singleton_record_path(tmp_path / "app")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.mkdir()
    record = SingletonRecord(
        version=SINGLETON_RECORD_VERSION,
        pid=os.getpid(),
        owner=default_owner(),
        start_fingerprint=current_process_fingerprint(),
        acquired_at_ms=int(time.time() * 1000),
    )

    with pytest.raises(OSError):
        _write_record(record_path, record)

    assert record_path.is_dir()
    assert sorted(record_path.parent.glob("*.tmp")) == []


def test_the_owner_record_is_written_owner_only(tmp_path: Path) -> None:
    """Adopting the shared writer must keep the record's owner-only permissions.

    The private copy opened its own descriptor to get ``0o600``; the shared
    writer takes the same bits through its ``mode`` argument, and this proves
    the bits actually reached the published file rather than the temporary.
    """
    app_home = tmp_path / "app"
    singleton = acquire_singleton(app_home, owner="alice")
    try:
        published = singleton_record_path(app_home)
        assert published.is_file()
        if os.name == "posix":
            assert stat.S_IMODE(published.stat().st_mode) == 0o600
        assert json.loads(published.read_text(encoding="utf-8"))["owner"] == "alice"
    finally:
        singleton.release()
