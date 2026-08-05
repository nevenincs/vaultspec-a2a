"""What a test may claim about its own purity, judged by a real pytest run.

A miniature suite is generated into an isolated rootdir and collected by the
real pytest CLI through the real shared marker home, and the marker sets are
read out of pytest's own collected items. Nothing is simulated: the items are
genuine, the closure is the one pytest resolved, and the marks are the ones a
run would actually select on.

The mechanism this covers cannot be exercised by calling the predicate with a
hand-built object. Purity is decided per ITEM during collection, and the defect
it exists to prevent is a per-file rule silently granting the claim to one live
test inside a file of pure ones - so the file layout is part of the subject.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# A conftest wired to the production shared home, so what is asserted below is
# the rule every package inherits rather than a copy of it written here.
_CONFTEST = '''
"""Mini-package conftest driving the production layer/purity mechanism."""

from pathlib import Path

import pytest

from vaultspec_a2a.testing import apply_layer_markers

_PACKAGE_DIR = str(Path(__file__).resolve().parent)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    apply_layer_markers(
        items,
        package_dir=_PACKAGE_DIR,
        middleware_files=frozenset({"test_infra.py"}),
        impure_files=frozenset({"test_named_impure.py"}),
    )
'''

# One file holding a pure test beside two that testify against themselves. The
# mixed file is the point: a per-file exclusion cannot separate these.
_MIXED = """
import pytest


def test_pure() -> None:
    assert True


@pytest.mark.service
def test_declares_service() -> None:
    assert True


@pytest.mark.resource("scratch-purity-forfeit")
def test_claims_a_resource() -> None:
    assert True


@pytest.mark.service
@pytest.mark.resource("scratch-purity-forfeit")
def test_declares_both() -> None:
    assert True
"""

_INFRA = """
def test_infrastructure() -> None:
    assert True
"""

_NAMED_IMPURE = """
def test_named_by_the_caller() -> None:
    assert True
"""

# Pins the child's rootdir to the generated suite, and it is load-bearing rather
# than tidiness. To match its command-line argument against collected nodes,
# pytest enumerates its ROOTDIR and lstats the entries. Without an ini file
# anywhere above it, a suite generated under the system temp directory makes that
# rootdir the system temp directory - hundreds of directories belonging to other
# projects on a shared machine, which other processes delete while the walk is
# in progress. The child then died mid-collection with a FileNotFoundError naming
# a stranger's directory, roughly one run in four, for a reason having nothing to
# do with markers. An ini file in the suite stops the walk at the suite.
_INI = """
[pytest]
"""

# Dumps the resolved marker set of every collected item. Reads pytest's state
# after every modifyitems hook rather than parsing the printed report, which is
# a rendering and has misattributed parametrized ids before.
_DUMPER = """
import json
import os


class Dump:
    def pytest_collection_finish(self, session):
        rows = {}
        for item in session.items:
            rows[item.nodeid.replace(chr(92), "/").split("::")[-1]] = sorted(
                {m.name for m in item.iter_markers()}
            )
        with open(os.environ["PURITY_DUMP"], "w", encoding="utf-8") as handle:
            json.dump(rows, handle)


def pytest_configure(config):
    config.pluginmanager.register(Dump())
"""


@pytest.fixture(scope="module")
def collected(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[str]]:
    """One real collection shared by every assertion in this module.

    Module-scoped because the subprocess pays a full interpreter and package
    import per run, and each assertion below reads the SAME collection - four
    private runs would cost four times as much to answer four questions about
    one result.
    """
    return _collect(tmp_path_factory.mktemp("purity"))


def _collect(tmp_path: Path) -> dict[str, list[str]]:
    """Collect the mini-suite with the real CLI and return its marker sets."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (suite / "test_mixed.py").write_text(_MIXED, encoding="utf-8")
    (suite / "test_infra.py").write_text(_INFRA, encoding="utf-8")
    (suite / "test_named_impure.py").write_text(_NAMED_IMPURE, encoding="utf-8")
    (suite / "pytest.ini").write_text(_INI, encoding="utf-8")
    (tmp_path / "dumper.py").write_text(_DUMPER, encoding="utf-8")

    dump = tmp_path / "markers.json"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env["PURITY_DUMP"] = str(dump)
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    # The child writes its own temporary files here rather than into the shared
    # machine temp directory, so a mini-run leaves nothing behind for the next
    # session to walk. This is containment, NOT the flake fix - isolating the
    # child's temp root was the first theory and it did not help, because what
    # the child chokes on is the directory its ARGUMENT lives under, which the
    # ini file above pins.
    for variable in ("TMPDIR", "TEMP", "TMP"):
        env[variable] = str(scratch)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(suite),
            "--collect-only",
            "-q",
            "--basetemp",
            str(scratch / "pytest"),
            # Loaded explicitly because this suite lives OUTSIDE the checkout and
            # never sees the repository root conftest that normally installs the
            # resource layer. Without it the resource mark would be inert and the
            # claim assertion below would pass for the wrong reason.
            "-p",
            "vaultspec_a2a.testing.plugin",
            "-p",
            "dumper",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert dump.is_file(), (
        f"the mini-suite did not collect (exit {result.returncode}); "
        f"stdout=\n{result.stdout}\nstderr=\n{result.stderr}"
    )
    rows: dict[str, list[str]] = json.loads(dump.read_text(encoding="utf-8"))
    # Floor: a dump that saw nothing would satisfy every assertion below by
    # having no counterexample in it.
    assert len(rows) == 6, f"expected six collected items, got {sorted(rows)}"
    return rows


def test_a_test_declaring_service_is_denied_the_purity_claim(
    collected: dict[str, list[str]],
) -> None:
    """The mark says it drives real services; that settles the purity question.

    This is the live defect the rule closes. Seven such tests sat in files also
    holding pure ones, so the package's file-level exclusion could not reach
    them, and a hermetic selection collected real live turns.
    """
    rows = collected
    assert "unit" not in rows["test_declares_service"]
    assert "core" in rows["test_declares_service"]


def test_a_test_claiming_a_resource_is_denied_the_purity_claim(
    collected: dict[str, list[str]],
) -> None:
    """A claim on a machine-global resource is testimony against purity.

    Nothing in the tree wears both today, so this is a guard rather than a
    defect proof - it forecloses the contradiction rather than repairing one.
    A test with nothing shared to touch would have nothing to claim.
    """
    rows = collected
    assert "unit" not in rows["test_claims_a_resource"]
    assert "unit" not in rows["test_declares_both"]


def test_a_pure_test_sharing_the_file_keeps_its_claim(
    collected: dict[str, list[str]],
) -> None:
    """The other direction, and the reason the rule is per item.

    Withholding is only correct if it is narrow. A rule that took the claim from
    the whole file would pass the two assertions above while silently costing
    every pure test in the module its place in the hermetic selection - a loss of
    COVERAGE, which is the failure nobody investigates.
    """
    rows = collected
    assert rows["test_pure"] == ["core", "unit"]


def test_the_two_older_mechanisms_still_decide_what_they_decided(
    collected: dict[str, list[str]],
) -> None:
    """The layer split and the caller-named impure file are unchanged.

    Asserted because this rule was added INSIDE the shared home every package
    routes through, so a mistake here would move markers far from this file.
    """
    rows = collected
    assert rows["test_infrastructure"] == ["middleware"]
    assert rows["test_named_by_the_caller"] == ["core"]
