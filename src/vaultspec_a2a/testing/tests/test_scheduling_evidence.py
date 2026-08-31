"""End-to-end scheduling evidence through real pytest subprocess runs.

Each test generates a miniature suite in an isolated rootdir, runs it with the
real pytest CLI and the real plugin under ``-n 2 --dist=loadgroup``, and judges
the outcome from artifacts the mini-tests wrote to disk: wall-clock intervals
and xdist worker ids. Nothing is simulated - real workers, real leases in an
isolated machine-global home, real sleeps.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_RECORDER = """
import json, os, time
from pathlib import Path

import pytest


def _record(tag: str) -> None:
    out = Path(os.environ["EVIDENCE_DIR"])
    start = time.time()
    time.sleep(1.0)
    end = time.time()
    (out / (tag + ".json")).write_text(json.dumps({
        "start": start,
        "end": end,
        "worker": os.environ.get("PYTEST_XDIST_WORKER", "main"),
    }))


@pytest.mark.resource("scratch-evidence-pair")
def test_pair_first() -> None:
    _record("pair_first")


@pytest.mark.resource("scratch-evidence-pair")
def test_pair_second() -> None:
    _record("pair_second")


@pytest.mark.resource("scratch-evidence-other")
def test_other_first() -> None:
    _record("other_first")


@pytest.mark.resource("scratch-evidence-other")
def test_other_second() -> None:
    _record("other_second")
"""


def _run_pytest(
    suite_dir: Path,
    *extra_args: str,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env.update(env_overrides or {})
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(suite_dir),
            # Loaded explicitly because this runs OUTSIDE the checkout. The
            # plugin is deliberately not a pytest11 entry point - that would
            # auto-load it into every consumer's session - so the repository
            # root conftest loads it instead, and a suite generated into a temp
            # directory never sees that conftest. Without this the mini-suites
            # run with no resource layer at all, and every assertion that a
            # violation is REFUSED passes for the wrong reason: nothing was
            # there to refuse it.
            "-p",
            "vaultspec_a2a.testing.plugin",
            "-p",
            "no:cacheprovider",
            "-q",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        # LOAD-BEARING, not cosmetic. With no ini file anywhere above a suite
        # generated into the system temp directory, the child resolves its
        # rootdir from the working directory - so running here makes it the
        # suite. Drop this and the rootdir becomes the checkout, the argument
        # then sits outside it, and pytest descends from the drive root
        # enumerating the system temp directory on the way: measured at 18-26s
        # per collection instead of under a second, and failing outright when
        # another process deletes one of the tens of thousands of entries
        # mid-walk (1 run in 4). A sibling module hit exactly that.
        cwd=suite_dir,
        env=env,
    )


def _overlaps(one: dict[str, float], two: dict[str, float]) -> bool:
    return one["start"] < two["end"] and two["start"] < one["end"]


def test_contended_pair_serializes_and_disjoint_groups_run_concurrently(
    tmp_path: Path,
) -> None:
    """The owner's acceptance shape, measured on the wall clock.

    Four one-second tests in two exclusive groups under two workers. The
    worker-id assertions prove PLACEMENT specifically - the scheduler put each
    group on one worker. The non-overlap of a contended pair is guaranteed by
    two independent layers (same-worker serial execution AND the lease taken
    per test), so its timing evidence confirms the outcome without attributing
    it to either layer alone; the cross-group overlap is what only correct
    placement can produce.
    """
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_evidence.py").write_text(_RECORDER)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    completed = _run_pytest(
        suite,
        "-n",
        "2",
        "--dist=loadgroup",
        env_overrides={
            "EVIDENCE_DIR": str(evidence),
            "VAULTSPEC_PROCS_HOME": str(tmp_path / "procs"),
            # Pin the admission budget: this proof NEEDS its two workers, and
            # on a loaded box the capacity-derived count would rightly degrade
            # them away. The explicit operator budget is the sanctioned knob.
            "VAULTSPEC_TEST_CPU_BUDGET": "8",
        },
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    intervals = {
        stem: json.loads((evidence / f"{stem}.json").read_text())
        for stem in ("pair_first", "pair_second", "other_first", "other_second")
    }
    pair = (intervals["pair_first"], intervals["pair_second"])
    other = (intervals["other_first"], intervals["other_second"])
    # Same exclusive resource -> same worker, strictly sequenced.
    assert pair[0]["worker"] == pair[1]["worker"], intervals
    assert other[0]["worker"] == other[1]["worker"], intervals
    assert not _overlaps(pair[0], pair[1]), f"contended pair overlapped: {pair}"
    assert not _overlaps(other[0], other[1]), f"contended pair overlapped: {other}"
    # Disjoint groups -> different workers, genuinely concurrent.
    assert pair[0]["worker"] != other[0]["worker"], intervals
    assert any(_overlaps(a, b) for a in pair for b in other), (
        f"disjoint groups never overlapped - the run was fully serial: {intervals}"
    )


def test_blind_distribution_modes_are_refused(tmp_path: Path) -> None:
    """``-n`` without ``--dist=loadgroup`` must abort before running anything."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_noop.py").write_text("def test_noop() -> None:\n    pass\n")
    completed = _run_pytest(suite, "-n", "2")
    assert completed.returncode != 0
    assert "requires --dist=loadgroup" in completed.stdout + completed.stderr


def test_group_names_merge_overlapping_exclusive_sets(tmp_path: Path) -> None:
    """Declarations sharing any key collapse into one transitive group."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_groups.py").write_text(
        "import pytest\n\n"
        "MERGED = 'res:scratch-gx+scratch-gy+scratch-gz'\n\n"
        "def _group(request):\n"
        "    return request.node.get_closest_marker('xdist_group')\n\n"
        "@pytest.mark.resource('scratch-gx')\n"
        "@pytest.mark.resource('scratch-gy')\n"
        "def test_xy(request) -> None:\n"
        "    assert _group(request).args[0] == MERGED\n\n"
        "@pytest.mark.resource('scratch-gy')\n"
        "@pytest.mark.resource('scratch-gz')\n"
        "def test_yz(request) -> None:\n"
        "    assert _group(request).args[0] == MERGED\n\n"
        "@pytest.mark.resource('scratch-alone', shared=True)\n"
        "def test_shared_only_gets_no_group(request) -> None:\n"
        "    assert _group(request) is None\n"
    )
    completed = _run_pytest(
        suite,
        env_overrides={"VAULTSPEC_PROCS_HOME": str(tmp_path / "procs")},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_undeclared_live_tier_tests_join_the_serial_catchall(
    tmp_path: Path,
) -> None:
    """An undeclared test under a live-tier directory is never distributed."""
    suite = tmp_path / "suite"
    live_dir = suite / "service_tests"
    live_dir.mkdir(parents=True)
    (live_dir / "test_undeclared.py").write_text(
        "def test_undeclared(request) -> None:\n"
        "    marker = request.node.get_closest_marker('xdist_group')\n"
        "    assert marker is not None\n"
        "    assert marker.args[0] == 'undeclared-live-serial'\n"
    )
    completed = _run_pytest(
        suite,
        env_overrides={"VAULTSPEC_PROCS_HOME": str(tmp_path / "procs")},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_backstop_timeout_derives_from_the_claimed_resource(
    tmp_path: Path,
) -> None:
    """A live-lane claim raises the item's timeout ceiling to the spec's value."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_backstop.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.resource('claude-cli-lane')\n"
        "def test_backstop(request) -> None:\n"
        "    marker = request.node.get_closest_marker('timeout')\n"
        "    assert marker is not None and marker.args[0] == 1800\n"
    )
    completed = _run_pytest(
        suite,
        env_overrides={"VAULTSPEC_PROCS_HOME": str(tmp_path / "procs")},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_unknown_resource_keys_fail_collection_loudly(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_typo.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.resource('loopback-stak')\n"
        "def test_typo() -> None:\n"
        "    pass\n"
    )
    completed = _run_pytest(
        suite,
        env_overrides={"VAULTSPEC_PROCS_HOME": str(tmp_path / "procs")},
    )
    assert completed.returncode != 0
    assert "loopback-stak" in completed.stdout + completed.stderr


def test_registry_backed_fixture_refuses_undeclared_use(tmp_path: Path) -> None:
    """Asking for a stack-backed fixture without declaring the stack fails."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_undeclared_fixture.py").write_text(
        "def test_wants_gateway(gateway_endpoint) -> None:\n    pass\n"
    )
    completed = _run_pytest(
        suite,
        env_overrides={"VAULTSPEC_PROCS_HOME": str(tmp_path / "procs")},
    )
    assert completed.returncode != 0
    assert "without declaring" in completed.stdout + completed.stderr
