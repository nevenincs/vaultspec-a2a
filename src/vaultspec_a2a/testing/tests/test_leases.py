"""Lease exclusion against the real filesystem and real processes.

The lease home is an isolated ``tmp_path`` per test; contending holders are
this process, its threads, and real spawned interpreters that exit or are
killed for real - no mocks, no patched clocks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from ..leases import (
    LEASE_TTL_MS,
    LeaseAcquisitionTimeoutError,
    acquire,
    hold_lease,
    lease_home,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_exclusive_lease_excludes_a_second_claimant(tmp_path: Path) -> None:
    with hold_lease("scratch-excl", home=tmp_path):
        with pytest.raises(LeaseAcquisitionTimeoutError) as excinfo:
            acquire("scratch-excl", home=tmp_path, acquire_timeout_s=0.8)
        # The refusal names the live holder, not just a clock.
        assert "pid" in str(excinfo.value)


def test_release_frees_the_lease_for_the_next_claimant(tmp_path: Path) -> None:
    with hold_lease("scratch-excl", home=tmp_path):
        pass
    follow_on = acquire("scratch-excl", home=tmp_path, acquire_timeout_s=2.0)
    follow_on.release()
    assert not follow_on.path.exists()


def test_dead_holder_is_reclaimed_by_pid_liveness(tmp_path: Path) -> None:
    """A holder that exits without releasing frees the lease immediately."""
    script = (
        "import sys; from pathlib import Path\n"
        "from vaultspec_a2a.testing.leases import acquire\n"
        "acquire(sys.argv[2], home=Path(sys.argv[1]))\n"
        "print('held', flush=True)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), "scratch-crash"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert "held" in completed.stdout
    marker = lease_home(tmp_path) / "scratch-crash.lease"
    assert marker.exists(), "the crashed holder left its marker behind"
    lease = acquire("scratch-crash", home=tmp_path, acquire_timeout_s=5.0)
    lease.release()


def test_frozen_heartbeat_with_live_pid_is_reclaimed(tmp_path: Path) -> None:
    """A live-pid marker whose heartbeat froze past the TTL loses the lease.

    Mirrors the engine precedent: a live process with a dead heartbeat writer
    must not hold a resource forever. The stall is real - the marker's mtime
    is genuinely old - only its age is arranged.
    """
    import os

    lease = acquire("scratch-frozen", home=tmp_path, refresh_interval_s=3600.0)
    stale_s = (LEASE_TTL_MS + 60_000) / 1000
    old = time.time() - stale_s
    os.utime(lease.path, times=(old, old))
    successor = acquire("scratch-frozen", home=tmp_path, acquire_timeout_s=5.0)
    # The displaced holder must not delete the successor's marker on release.
    lease.release()
    assert successor.path.exists()
    successor.release()


def test_refresher_heartbeats_the_marker(tmp_path: Path) -> None:
    lease = acquire("scratch-beat", home=tmp_path, refresh_interval_s=0.1)
    try:
        first = lease.path.stat().st_mtime
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if lease.path.stat().st_mtime > first:
                break
            time.sleep(0.05)
        assert lease.path.stat().st_mtime > first, "mtime never advanced"
    finally:
        lease.release()


def test_shared_leases_coexist_and_block_exclusive(tmp_path: Path) -> None:
    shared_one = acquire("scratch-mix", shared=True, home=tmp_path)
    shared_two = acquire(
        "scratch-mix", shared=True, home=tmp_path, acquire_timeout_s=2.0
    )
    with pytest.raises(LeaseAcquisitionTimeoutError):
        acquire("scratch-mix", home=tmp_path, acquire_timeout_s=0.8)
    shared_one.release()
    shared_two.release()
    exclusive = acquire("scratch-mix", home=tmp_path, acquire_timeout_s=2.0)
    exclusive.release()


def test_exclusive_lease_blocks_shared_claimants(tmp_path: Path) -> None:
    with (
        hold_lease("scratch-mix2", home=tmp_path),
        pytest.raises(LeaseAcquisitionTimeoutError),
    ):
        acquire("scratch-mix2", shared=True, home=tmp_path, acquire_timeout_s=0.8)


def test_malformed_keys_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="kebab-case"):
        acquire("Not A Key", home=tmp_path)


def test_two_processes_serialize_on_one_exclusive_key(tmp_path: Path) -> None:
    """Cross-process exclusion holds with no scheduler involved at all.

    Two real interpreters contend for one key; each records its held interval
    to disk. The intervals must not overlap - this is the guarantee placement
    quality merely optimizes.
    """
    script = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from vaultspec_a2a.testing.leases import hold_lease\n"
        "home, key, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])\n"
        "with hold_lease(key, home=home):\n"
        "    start = time.time()\n"
        "    time.sleep(0.8)\n"
        "    end = time.time()\n"
        "out.write_text(json.dumps({'start': start, 'end': end}))\n"
    )

    def _spawn(tag: str) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path),
                "scratch-serial",
                str(tmp_path / f"{tag}.json"),
            ]
        )

    first, second = _spawn("one"), _spawn("two")
    assert first.wait(timeout=120) == 0
    assert second.wait(timeout=120) == 0
    one = json.loads((tmp_path / "one.json").read_text())
    two = json.loads((tmp_path / "two.json").read_text())
    assert one["end"] <= two["start"] or two["end"] <= one["start"], (
        f"held intervals overlap: {one} vs {two}"
    )
