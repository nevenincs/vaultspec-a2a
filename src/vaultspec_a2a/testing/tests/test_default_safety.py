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
from ..ports import free_port
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
        "from vaultspec_a2a.lifecycle import load_procs_config\n"
        "from vaultspec_a2a.testing.ports import free_port\n"
        "ports = [free_port() for _ in range(10)]\n"
        "band = load_procs_config().role('scratch').band\n"
        "assert all(p in band for p in ports), (\n"
        "    'allocation fell back to ephemeral candidates; the reservation '\n"
        "    'path this proof exists to exercise never ran: %r' % ports)\n"
        "Path(sys.argv[1]).write_text(json.dumps(ports))\n"
        "peer = Path(sys.argv[2])\n"
        "deadline = time.monotonic() + 120\n"
        "while not peer.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.05)\n"
        "assert peer.exists(), 'peer never published; holds did not overlap'\n"
    )
    env = dict(os.environ)
    env["VAULTSPEC_A2A_PROCS_HOME"] = str(tmp_path / "procs")

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

    The first real pytest session registers and PARKS UNTIL RELEASED; the
    second, launched with a pinned four-core budget, must report one live peer
    and admit itself with two workers instead of four. Read from the second
    run's own report header - the operator-visible surface.

    The holder is held by an observed condition, not by a fixed sleep. What the
    proof requires is that the holder's session lease outlive the second run's
    admission, and how long that takes is a property of the host: booting four
    xdist workers costs a moment on an idle box and tens of seconds under a
    concurrent suite. A sleep long enough for the loaded case is dead time in
    every other run, and one short enough to be cheap silently inverts the
    proof - the holder exits first, the second run sees no peer, and the
    assertion below fails for a reason that has nothing to do with admission.
    """
    home = tmp_path / "procs"
    suite = tmp_path / "suite"
    suite.mkdir()
    release_file = tmp_path / "release-the-holder"
    # The cap is a safety net against an orphaned holder - a parent killed
    # between the spawn and its `finally` - and never the mechanism: the parent
    # releases this holder the moment the second session has been observed.
    (suite / "test_hold.py").write_text(
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        "\n"
        "def test_hold() -> None:\n"
        "    release = Path(os.environ['VAULTSPEC_A2A_TEST_HOLD_RELEASE'])\n"
        "    deadline = time.monotonic() + 900\n"
        "    while not release.exists() and time.monotonic() < deadline:\n"
        "        time.sleep(0.1)\n"
    )
    (suite / "test_quick.py").write_text("def test_quick() -> None:\n    pass\n")
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env["VAULTSPEC_A2A_PROCS_HOME"] = str(home)
    env["VAULTSPEC_A2A_TEST_CPU_BUDGET"] = "4"
    env["VAULTSPEC_A2A_TEST_HOLD_RELEASE"] = str(release_file)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pytest",
            str(suite / "test_hold.py"),
            # Named explicitly: these suites live outside the checkout,
            # and the plugin loads from the repository root conftest rather
            # than a pytest11 entry point, so conftest discovery from the
            # test file never reaches it. Without this the holder registers
            # no session lease at all and the wait below stalls against a
            # peer that was never admitted.
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
        from ..children import child_tree_progress, run_child
        from ..leases import live_shared_holder_count
        from ..progress import LivenessWatch, ProgressDeadline, wait_for

        # The holder's own work is the progress signal, so a cold pytest boot on
        # a loaded host is never mistaken for a holder that failed to register.
        # A holder that EXITED fails the wait within one interval instead, since
        # its marker can no longer appear.
        deadline = ProgressDeadline(
            idle_window_s=30.0,
            watches=(
                LivenessWatch(
                    label="the holding pytest session",
                    verdict=lambda: (
                        None
                        if holder.poll() is None
                        else f"the holder exited with {holder.returncode}"
                    ),
                ),
            ),
        )
        wait_for(
            lambda: live_shared_holder_count(SESSION_LEASE_KEY, home=home) or None,
            deadline=deadline,
            fingerprint=lambda: child_tree_progress(holder.pid),
            interval_s=0.25,
        )
        second = run_child(
            [
                sys.executable,
                "-m",
                "pytest",
                str(suite / "test_quick.py"),
                # The admitting run needs the plugin for the same reason the
                # holder does, and more pointedly: the worker-count verdict this
                # test reads comes from the plugin's own report header, so
                # without it there is no header to read and no admission to
                # observe.
                "-p",
                "vaultspec_a2a.testing.plugin",
                "-p",
                "no:cacheprovider",
                "-n",
                "4",
                "--dist=loadgroup",
            ],
            what="the second, degraded-admission pytest session",
            cwd=suite,
            env=env,
        )
    finally:
        # Released before the kill so the holder ends the way a session ends -
        # unconfigure, lease release - rather than only under a signal.
        release_file.write_text("released", encoding="utf-8")
        holder.kill()
        holder.wait(timeout=60)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "1 live peer test session(s); workers 4 -> 2" in second.stdout, second.stdout


def test_held_reservations_are_heartbeated_past_the_ttl() -> None:
    """A process-lifetime hold survives the reservation TTL.

    Registry liveness reclaims a marker older than its TTL regardless of pid,
    and a suite runs far longer than the TTL, so the hold is only real if its
    marker's mtime keeps advancing. The marker is genuinely aged past the TTL
    on disk; one refresh pass must bring it back to LIVE as the allocator
    judges it.
    """
    import os
    import time

    from ...lifecycle import now_ms
    from ...lifecycle.registry import RESERVATION_TTL_MS, _reservation_is_live
    from ..ports import _HELD_RESERVATIONS, _refresh_held_markers_once, free_port

    port = free_port()
    reservation = next(r for r in _HELD_RESERVATIONS if r.port == port)
    stale_s = (RESERVATION_TTL_MS + 60_000) / 1000
    old = time.time() - stale_s
    os.utime(reservation.path, times=(old, old))
    assert _reservation_is_live(reservation.path, now=now_ms()) is False
    _refresh_held_markers_once()
    assert _reservation_is_live(reservation.path, now=now_ms()) is True
