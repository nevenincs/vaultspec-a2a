"""Tests for the storage-anchor gate.

The gate's whole value is discrimination: it must catch a path anchored to the
repository while clearing the package-data and configuration forms that look
similar. Every case below parses real source through the real ``ast`` module and
calls the real gate functions, and the last case runs the gate as a real
subprocess against this repository.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from dev.guards import storage_anchors

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse(source: str) -> ast.Module:
    """Parse a source fragment the way the gate parses a real module."""
    return ast.parse(source)


def test_a_walk_that_escapes_the_package_is_reported() -> None:
    """The defect this gate exists for: a walk up to the source tree."""
    tree = _parse("ROOT = Path(__file__).resolve().parent.parent.parent.parent\n")
    found = storage_anchors._walk_violations(tree, Path("control/config.py"))
    assert len(found) == 1, found
    assert "escapes the package root" in found[0][1]


def test_a_walk_that_stops_at_the_package_root_is_allowed() -> None:
    """Bundled package data is resolved this way and must not be reported."""
    tree = _parse('BIN = Path(__file__).resolve().parent.parent / "bin"\n')
    assert storage_anchors._walk_violations(tree, Path("providers/factory.py")) == []


def test_a_walk_inside_the_package_is_allowed() -> None:
    """The shallow form used for a module's own asset directory."""
    tree = _parse('RULES = Path(__file__).parent / "presets" / "rules"\n')
    assert storage_anchors._walk_violations(tree, Path("context/rules.py")) == []


def test_the_budget_follows_module_depth_rather_than_a_fixed_number() -> None:
    """A deeper module may take more steps before it leaves the package."""
    source = "ROOT = Path(__file__).resolve().parent.parent.parent\n"
    shallow = storage_anchors._walk_violations(_parse(source), Path("a/mod.py"))
    deep = storage_anchors._walk_violations(_parse(source), Path("a/b/c/mod.py"))
    assert len(shallow) == 1, "three steps escape a module two parts deep"
    assert deep == [], "three steps stay inside a module four parts deep"


def test_a_chain_is_reported_once_at_its_full_length() -> None:
    """Inner nodes of a parent chain must not each report a shorter walk."""
    tree = _parse("ROOT = Path(__file__).parent.parent.parent.parent.parent\n")
    found = storage_anchors._walk_violations(tree, Path("control/config.py"))
    assert len(found) == 1, found
    assert "walk of 5 parents" in found[0][1]


def test_working_directory_reads_are_reported() -> None:
    """Both spellings of "wherever the process happened to start"."""
    tree = _parse("a = Path.cwd()\nb = os.getcwd()\n")
    found = storage_anchors._cwd_violations(tree)
    assert [lineno for lineno, _ in found] == [1, 2], found


def test_an_unrelated_cwd_attribute_is_not_reported() -> None:
    """The gate keys on the real call, not on the word."""
    tree = _parse("value = config.cwd\nother = shutil.which('cwd')\n")
    assert storage_anchors._cwd_violations(tree) == []


def test_project_root_reads_are_reported_outside_its_defining_module() -> None:
    """Reading the anchor elsewhere is how it becomes a storage root."""
    tree = _parse("root = settings.project_root\n")
    found = storage_anchors._project_root_violations(tree, Path("providers/factory.py"))
    assert len(found) == 1, found


def test_project_root_is_allowed_in_the_module_that_defines_it() -> None:
    """Its own definition site is not a violation of its own rule."""
    tree = _parse("root = self.project_root\n")
    assert (
        storage_anchors._project_root_violations(tree, Path("control/config.py")) == []
    )


def test_test_modules_are_out_of_scope() -> None:
    """Tests legitimately build paths against the checkout they run in."""
    assert storage_anchors._is_test_module(Path("control/tests/test_config.py"))
    assert storage_anchors._is_test_module(Path("testing/plugin.py"))
    assert not storage_anchors._is_test_module(Path("control/config.py"))


def test_the_gate_passes_against_this_repository() -> None:
    """The real invariant, run the way the harness runs it.

    Exit 0 means every remaining violation is one of the explicitly deferred
    modules. A new anchor in production code fails this test.
    """
    result = subprocess.run(
        [sys.executable, "dev/guards/storage_anchors.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"the storage-anchor gate failed:\n{result.stderr}\n{result.stdout}"
    )


def test_every_deferred_module_still_exists() -> None:
    """A deferred entry naming a module that is gone is stale debt bookkeeping."""
    package = REPO_ROOT / storage_anchors.ROOT
    missing = [key for key in storage_anchors.DEFERRED if not (package / key).is_file()]
    assert missing == [], (
        f"deferred entries name modules that no longer exist: {missing}"
    )


def test_the_gate_refuses_to_pass_from_the_wrong_directory() -> None:
    """A gate that silently passes when it scanned nothing is worse than none."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "dev" / "guards" / "storage_anchors.py")],
        cwd=REPO_ROOT / "dev",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 2, result.stdout + result.stderr
