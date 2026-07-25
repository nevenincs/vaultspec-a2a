"""Real-behaviour proof of the repository's external-prerequisite rule.

The rule lives in the root conftest because every suite has to obey the same
one, so these tests drive it the way a caller does - real ``pytest`` processes
with real declarations and a real environment - rather than inspecting it. No
mock, fake, or monkeypatch: the subprocess environment is constructed
explicitly, which is how a certification job supplies or withholds a
prerequisite in the first place.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..conftest import EXTERNAL_PREREQUISITES

REPO_ROOT = Path(__file__).resolve().parents[3]
_LOST_ACK = "src/vaultspec_a2a/service_tests/test_engine_broker_lost_ack_live.py"
_QUIET_INI = "addopts=-ra --capture=sys"

# pytest's exit code for a command-line usage error.
_USAGE_ERROR = 4


def _pytest(
    *args: str, without: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Run a real nested pytest, optionally with env vars stripped."""
    env = {k: v for k, v in os.environ.items() if k not in without}
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def test_every_prerequisite_names_what_is_missing_and_how_to_supply_it() -> None:
    """The rule's whole value is the reason text, so hold it to a shape."""
    ids = [prerequisite.id for prerequisite in EXTERNAL_PREREQUISITES]
    assert len(ids) == len(set(ids)), ids
    for prerequisite in EXTERNAL_PREREQUISITES:
        reason = prerequisite.absence_reason()
        assert prerequisite.what in reason
        assert prerequisite.supply in reason
        assert "unavailable" in reason
        # A caller-probed prerequisite is the only kind allowed to omit a probe,
        # and it must still say how to supply itself.
        assert prerequisite.supply.strip()
        assert prerequisite.probe is None or callable(prerequisite.probe)


def test_unknown_declaration_is_a_usage_error() -> None:
    """A typo in a certification job must not silently declare nothing."""
    result = _pytest(
        "--require-prerequisite=not-a-prerequisite", "--collect-only", "-q"
    )
    assert result.returncode == _USAGE_ERROR, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "unknown prerequisites: not-a-prerequisite" in combined, combined
    assert "dashboard-engine" in combined, combined


def test_declaring_an_absent_prerequisite_aborts_before_collection() -> None:
    """A guarantee that is false fails the run rather than skipping quietly."""
    result = _pytest(
        "--require-prerequisite=dashboard-engine",
        "--collect-only",
        "-q",
        without=("VAULTSPEC_ENGINE_SERVE_CMD",),
    )
    assert result.returncode == _USAGE_ERROR, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "prerequisites this host does not have: dashboard-engine" in combined
    assert "VAULTSPEC_ENGINE_SERVE_CMD" in combined, combined


def test_absent_cross_repo_engine_skips_instead_of_failing() -> None:
    """The cross-repo proof reports an absent dashboard, never a red gate.

    This is the whole point of the rule for the service tier: without the
    dashboard repository wired, the canonical service gate must not report a
    failure that says nothing about this repository's health.
    """
    result = _pytest(
        "--override-ini",
        _QUIET_INI,
        "-m",
        "service",
        _LOST_ACK,
        without=("VAULTSPEC_ENGINE_SERVE_CMD",),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "1 skipped" in combined, combined
    assert "VAULTSPEC_ENGINE_SERVE_CMD" in combined, combined


def test_a_gate_that_skips_despite_its_declaration_fails_the_session(
    tmp_path: Path,
) -> None:
    """The second net: a suite whose own gate disagrees with the probe.

    Configure-time probing catches a prerequisite that is simply missing. It
    cannot catch a suite that skips anyway - a stale import-time PATH lookup, a
    gate keyed on something narrower than the probe. That drift is exactly what
    silently emptied the provider suite in CI, so the session-end rule fails the
    run on it. Reproduced against a real skip in a real nested session: the rule
    loads as a plugin outside this repository, where nothing else can explain
    the outcome.
    """
    target = tmp_path / "test_gate_that_skips.py"
    target.write_text(
        "import pytest\n\n\n"
        "def test_gate() -> None:\n"
        '    pytest.skip("codex CLI not on PATH")\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "vaultspec_a2a.conftest",
            "--require-prerequisite=codex-cli",
            "-ra",
            str(target),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    combined = result.stdout + result.stderr
    # Nothing failed, and yet the session must not report success.
    assert "1 skipped" in combined, combined
    assert result.returncode != 0, combined
    assert "declared prerequisites that did not run" in combined, combined
    assert "codex-cli" in combined, combined
