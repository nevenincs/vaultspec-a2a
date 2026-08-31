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
from typing import TYPE_CHECKING

import pytest

from ..conftest import EXTERNAL_PREREQUISITES

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
_LOST_ACK = "src/vaultspec_a2a/service_tests/test_engine_broker_lost_ack_live.py"
_LIVE_PROVIDER_TESTS = (
    _LOST_ACK,
    "src/vaultspec_a2a/service_tests/test_dashboard_provider_catalog_live.py",
)
_QUIET_INI = "addopts=-ra --capture=sys"

# pytest's exit code for a command-line usage error.
_USAGE_ERROR = 4


def _pytest(
    *args: str,
    without: tuple[str, ...] = (),
    with_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a real nested pytest, optionally with env vars stripped."""
    env = {k: v for k, v in os.environ.items() if k not in without}
    if with_env is not None:
        env.update(with_env)
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


def test_absent_cross_repo_engine_is_disclosed_never_a_red_gate() -> None:
    """The cross-repo proof reports an absent dashboard, never a red gate.

    This is the whole point of the rule for the service tier: without the
    dashboard repository wired, the canonical service gate must not report a
    failure that says nothing about this repository's health.

    The proof reaches that outcome by being WITHHELD rather than skipped, and the
    distinction is not cosmetic. This proof is also billable, so cost gating
    deselects it before the skip path can run - which means the skip path for
    ``dashboard-engine`` is unreachable for as long as every proof needing it
    spends a credential. A bare deselection is silent, so the run would have been
    indistinguishable from one with nothing to withhold; the assertions below
    pin the disclosure that closes that hole, naming both the prerequisite and
    the runbook line that supplies it.
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
    assert "withheld 1 live proof(s)" in combined, combined
    assert "dashboard-engine" in combined, combined
    assert "VAULTSPEC_ENGINE_SERVE_CMD" in combined, combined


def test_live_provider_proofs_deselect_until_every_resource_is_declared() -> None:
    """An unapproved real-provider turn never becomes a passing pytest skip."""
    result = _pytest(
        "--override-ini",
        _QUIET_INI,
        "-m",
        "service",
        "--collect-only",
        "-q",
        *_LIVE_PROVIDER_TESTS,
        without=(
            "VAULTSPEC_ENGINE_SERVE_CMD",
            "VAULTSPEC_LIVE_PROVIDER_ID",
            "VAULTSPEC_LIVE_EXECUTION_MODE",
            "VAULTSPEC_LIVE_ENTRY_ID",
            "VAULTSPEC_LIVE_CONTROL_ID",
            "VAULTSPEC_LIVE_OPTION_ID",
        ),
    )
    combined = result.stdout + result.stderr
    # Withheld, disclosed, and NOT red. Exit 5 would be the same red gate the
    # rule refuses, reached through the exit status: a host with no dashboard
    # repository would fail the service tier over a resource it was never
    # expected to have. The proofs are still withheld - that is what the
    # deselection count and the absence of any skip prove - and the disclosure
    # is what keeps the withholding from being silent.
    assert result.returncode == pytest.ExitCode.OK, combined
    assert "2 deselected" in combined, combined
    assert "withheld 2 live proof(s)" in combined, combined
    assert "skipped" not in combined.casefold(), combined


def test_declared_live_provider_selector_fails_before_collection_when_unset() -> None:
    """A certification claim with no selector is a collection error, never a skip."""
    result = _pytest(
        "--require-prerequisite=provider-catalog-live-selection",
        "--collect-only",
        "-q",
        _LIVE_PROVIDER_TESTS[1],
        without=(
            "VAULTSPEC_LIVE_PROVIDER_ID",
            "VAULTSPEC_LIVE_EXECUTION_MODE",
            "VAULTSPEC_LIVE_ENTRY_ID",
            "VAULTSPEC_LIVE_CONTROL_ID",
            "VAULTSPEC_LIVE_OPTION_ID",
        ),
    )
    combined = result.stdout + result.stderr
    assert result.returncode == _USAGE_ERROR, combined
    assert "provider-catalog-live-selection" in combined, combined
    assert "VAULTSPEC_LIVE_OPTION_ID" in combined, combined


def test_live_provider_proofs_collect_only_after_all_resources_are_declared() -> None:
    """Collection requires explicit authorization, before either process can start."""
    required_env = {
        "VAULTSPEC_ENGINE_SERVE_CMD": sys.executable,
        "VAULTSPEC_LIVE_PROVIDER_ID": "collection-authorized",
        "VAULTSPEC_LIVE_EXECUTION_MODE": "collection-authorized",
        "VAULTSPEC_LIVE_ENTRY_ID": "collection-authorized",
        "VAULTSPEC_LIVE_CONTROL_ID": "collection-authorized",
        "VAULTSPEC_LIVE_OPTION_ID": "collection-authorized",
    }
    result = _pytest(
        "--override-ini",
        _QUIET_INI,
        "-m",
        "service",
        "--require-prerequisite=dashboard-engine",
        "--require-prerequisite=provider-catalog-live-selection",
        "--collect-only",
        "-q",
        *_LIVE_PROVIDER_TESTS,
        with_env=required_env,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "test_production_engine_recovers_lost_run_start_ack_exactly_once" in combined
    assert "test_dashboard_catalog_selection_completes_and_replays" in combined
    assert "deselected" not in combined.casefold(), combined
    assert "skipped" not in combined.casefold(), combined


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
