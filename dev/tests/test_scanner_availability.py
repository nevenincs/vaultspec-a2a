"""Prove no scanner can report "found nothing" when it means "reported nothing".

This is the one property every instrument under :mod:`dev.audit` and
:mod:`dev.quality` shares, and the one each of them got wrong before it was
rewritten: an absent tool, a tool that read no files, a checker that printed
nothing, a probe whose child died mid-run. Every case below is the exact shape
that used to read as green.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from dev.audit.dead_code import (
    DeadCodeOutcome,
    DeadCodeResult,
    offered_module_population,
    parse_vulture_output,
    run_dead_code_scan,
)
from dev.audit.duplication import (
    DuplicationOutcome,
    DuplicationResult,
    parse_report,
    run_duplication_scan,
)
from dev.exit_codes import ADVISORY_BROKEN
from dev.paths import REPO_ROOT
from dev.process import ToolUnavailableError, run_captured
from dev.quality.import_load_probe import parse_worker_output
from dev.quality.types import CheckerUnavailableError, require_report

if TYPE_CHECKING:
    from pathlib import Path


# --- dead code -------------------------------------------------------------


def test_an_empty_tree_is_an_error_not_a_clean_scan(tmp_path: Path) -> None:
    """vulture exits 0 over nothing; a floor is what tells that from clean."""
    result = run_dead_code_scan(tmp_path)
    assert result.outcome is DeadCodeOutcome.ERROR
    assert "prove nothing" in result.reason
    assert not result.is_green


def test_a_clean_result_cannot_be_built_without_a_denominator() -> None:
    """The invariant holds by construction, not by a caller remembering it."""
    with pytest.raises(ValueError, match="demonstrably inspected"):
        DeadCodeResult.clean(modules_offered=0)


def test_the_real_tree_clears_the_floor() -> None:
    """A floor nobody can clear would make the scan permanently unavailable."""
    assert offered_module_population(REPO_ROOT) > 0


def test_vulture_output_parses_into_findings() -> None:
    """The line shape is the contract between vulture and the confidence split."""
    findings = parse_vulture_output(
        "src/pkg/thing.py:12: unused import 'Cursor' (90% confidence)\n"
        "not a finding line\n"
        "src/pkg/other.py:3: unused variable 'x' (60% confidence, 2 lines)\n",
    )
    assert [(f.path, f.line, f.confidence) for f in findings] == [
        ("src/pkg/other.py", 3, 60),
        ("src/pkg/thing.py", 12, 90),
    ]


def test_confidence_buckets_split_at_the_declared_threshold() -> None:
    """A bare percentage is not a severity; this is the closest honest analogue."""
    findings = parse_vulture_output(
        "a.py:1: unused import 'A' (90% confidence)\n"
        "b.py:2: unused variable 'b' (60% confidence)\n",
    )
    result = DeadCodeResult.from_findings(findings, modules_offered=10)
    assert result.count_by_confidence == {"high (>=80%)": 1, "moderate (<80%)": 1}


# --- duplication -----------------------------------------------------------


def test_a_report_showing_no_sources_is_unavailable() -> None:
    """jscpd inspecting nothing is not jscpd finding nothing."""
    result = parse_report({"statistics": {"total": {"sources": 0}}, "duplicates": []})
    assert result.outcome is DuplicationOutcome.UNAVAILABLE
    assert "prove nothing" in result.reason


def test_a_report_showing_sources_and_no_clones_is_an_observed_zero() -> None:
    """Green is reachable, and says how much it read."""
    result = parse_report(
        {"statistics": {"total": {"sources": 42, "percentage": 0.0}}, "duplicates": []},
    )
    assert result.outcome is DuplicationOutcome.OBSERVED_ZERO
    assert result.files_analysed == 42


def test_an_observed_result_cannot_be_built_without_a_denominator() -> None:
    """Same invariant as the dead-code scan, enforced the same way."""
    with pytest.raises(ValueError, match="demonstrably inspected"):
        DuplicationResult.observed(files_analysed=0, duplicated_pct=0.0, groups=())


def test_an_empty_tree_yields_an_unavailable_duplication_scan(tmp_path: Path) -> None:
    """There is no source root to scan, so there is no measurement."""
    result = run_duplication_scan(tmp_path, timeout=120.0)
    assert result.outcome is DuplicationOutcome.UNAVAILABLE


# --- type checking ---------------------------------------------------------


def test_an_empty_checker_stream_is_refused() -> None:
    """A clean run is not silent; silence means no report was produced."""
    completed = subprocess.CompletedProcess(
        args=["ty"],
        returncode=1,
        stdout="",
        stderr="error: could not resolve the project\n",
    )
    with pytest.raises(CheckerUnavailableError, match="produced no report"):
        require_report("", completed, "ty")


def test_a_non_empty_checker_stream_is_accepted() -> None:
    """An empty JSON array IS a report: zero diagnostics, honestly measured."""
    completed = subprocess.CompletedProcess(
        args=["ty"], returncode=0, stdout="[]", stderr=""
    )
    require_report("[]", completed, "ty")


# --- process layer ---------------------------------------------------------


def test_an_absent_executable_raises_rather_than_returning_a_status() -> None:
    """Collapsing "missing" into an exit code is how a missing scanner reads green."""
    with pytest.raises(ToolUnavailableError, match="not on PATH"):
        run_captured(["this-executable-does-not-exist-anywhere"])


def test_a_timeout_raises_rather_than_returning_a_status() -> None:
    """A tool that never answered has not answered "nothing"."""
    with pytest.raises(ToolUnavailableError, match="timeout"):
        run_captured([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.0)


# --- import loadability ----------------------------------------------------


def test_a_module_the_child_never_resolved_is_attributed() -> None:
    """A hard crash names the module it died in, not the 300 candidates."""
    stdout = "start\talpha\t\nok\talpha\t\nstart\tbeta\t\n"
    loaded, failures = parse_worker_output(stdout, ["alpha", "beta", "gamma"])
    assert loaded == 1
    detail = {f.module: f.detail for f in failures}
    assert "interpreter died" in detail["beta"]
    assert "never attempted" in detail["gamma"]


def test_the_worker_reports_a_failing_import_and_keeps_going() -> None:
    """One break must not hide the ones behind it - run against the real worker."""
    completed = run_captured(
        [
            sys.executable,
            "-m",
            "dev.quality.import_load_worker",
            "json",
            "a_module_that_does_not_exist",
            "csv",
        ],
        cwd=REPO_ROOT,
        timeout=120.0,
    )
    loaded, failures = parse_worker_output(
        completed.stdout,
        ["json", "a_module_that_does_not_exist", "csv"],
    )
    assert loaded == 2
    assert [f.module for f in failures] == ["a_module_that_does_not_exist"]
    assert "ModuleNotFoundError" in failures[0].detail


# --- the contract itself ---------------------------------------------------


def test_advisory_broken_is_distinct_from_success() -> None:
    """The whole mechanism rests on this number not being zero."""
    assert ADVISORY_BROKEN != 0
