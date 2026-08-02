"""Default-safe allocation and concurrent-session admission, proven live.

The properties under proof are the inverted ones: an UNDECLARED test that
allocates through the shared spawning primitives cannot collide with a
concurrent session, and a second pytest session is admitted degraded rather
than multiplying load. Everything runs against real interpreters, real
reservation markers in a shared registry home, and the real pytest CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from ...lifecycle import load_procs_config
from ...tests.gateway_boot import free_port
from ..sessions import SESSION_LEASE_KEY, effective_worker_count

if TYPE_CHECKING:
    from pathlib import Path


def test_free_port_takes_a_held_registry_reservation() -> None:
    """The shared primitive allocates from the band and HOLDS the claim.

    The claim is machine-global state another allocator observes, which is
    the whole default-safe property: no declaration, no fixture request, and
    still no contention surface.
    """
    from ...lifecycle import procs_home

    port = free_port()
    band = load_procs_config().role("scratch").band
    assert port in band
    marker = procs_home() / f"scratch-{port}.reserved"
    assert marker.exists(), "the allocation left no held reservation marker"


def test_two_concurrent_processes_never_share_free_ports(tmp_path: Path) -> None:
    """Two real interpreters allocating simultaneously get disjoint ports.

    Both children share one registry home and each takes ten ports while the
    other does the same; the O_EXCL markers arbitrate, so the sets must be
    disjoint - across processes, with no marker, no fixture, no declaration
    in sight.
    """
    # Each child reserves its ports, publishes them, then HOLDS them until the
    # peer has published too. The barrier is what makes the claim meaningful:
    # without it a fast child can finish and release before the slow one even
    # starts, and any overlap in the sets would be legitimate reuse, not a
    # collision.
    script = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from vaultspec_a2a.tests.gateway_boot import free_port\n"
        "ports = [free_port() for _ in range(10)]\n"
        "Path(sys.argv[1]).write_text(json.dumps(ports))\n"
        "peer = Path(sys.argv[2])\n"
        "deadline = time.monotonic() + 120\n"
        "while not peer.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.05)\n"
        "assert peer.exists(), 'peer never published; holds did not overlap'\n"
    )
    env = dict(os.environ)
    env["VAULTSPEC_PROCS_HOME"] = str(tmp_path / "procs")

    def _spawn(tag: str, peer: str) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                str(tmp_path / f"{tag}.json"),
                str(tmp_path / f"{peer}.json"),
            ],
            env=env,
        )

    first, second = _spawn("one", "two"), _spawn("two", "one")
    assert first.wait(timeout=180) == 0
    assert second.wait(timeout=180) == 0
    one = set(json.loads((tmp_path / "one.json").read_text()))
    two = set(json.loads((tmp_path / "two.json").read_text()))
    assert len(one) == 10 and len(two) == 10
    assert one.isdisjoint(two), f"concurrent runs shared ports: {one & two}"


def test_effective_worker_count_splits_the_budget_across_peers() -> None:
    assert effective_worker_count(8, peers=0, cpu_budget=8) == 8
    assert effective_worker_count(8, peers=1, cpu_budget=8) == 4
    assert effective_worker_count(8, peers=3, cpu_budget=8) == 2
    # A starved box still admits one worker - a run always progresses.
    assert effective_worker_count(8, peers=7, cpu_budget=2) == 1
    # The request is a ceiling, never inflated.
    assert effective_worker_count(2, peers=0, cpu_budget=32) == 2


def test_second_session_is_admitted_degraded(tmp_path: Path) -> None:
    """While one session is live, a second distributed run reduces its workers.

    The first real pytest session registers and parks; the second, launched
    with a pinned four-core budget, must report one live peer and admit
    itself with two workers instead of four. Read from the second run's own
    report header - the operator-visible surface.
    """
    home = tmp_path / "procs"
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_hold.py").write_text(
        "import time\n\ndef test_hold() -> None:\n    time.sleep(20)\n"
    )
    (suite / "test_quick.py").write_text("def test_quick() -> None:\n    pass\n")
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env["VAULTSPEC_PROCS_HOME"] = str(home)
    env["VAULTSPEC_TEST_CPU_BUDGET"] = "4"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pytest",
            str(suite / "test_hold.py"),
            "-p",
            "vaultspec_a2a.testing.plugin",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=suite,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        # The holder's session marker appears once its configure ran.
        from ..leases import live_shared_holder_count
        from ..progress import ProgressDeadline, wait_for

        deadline = ProgressDeadline(idle_window_s=30.0)
        wait_for(
            lambda: live_shared_holder_count(SESSION_LEASE_KEY, home=home) or None,
            deadline=deadline,
            interval_s=0.25,
        )
        second = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(suite / "test_quick.py"),
                "-p",
                "vaultspec_a2a.testing.plugin",
                "-p",
                "no:cacheprovider",
                "-n",
                "4",
                "--dist=loadgroup",
            ],
            cwd=suite,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        holder.kill()
        holder.wait(timeout=60)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "1 live peer test session(s); workers 4 -> 2" in second.stdout, second.stdout
