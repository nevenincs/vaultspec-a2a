"""Collection-time behaviour of the resource-aware execution plugin.

Driven as a REAL pytest subprocess against real temporary test files, because
the defect these guard is a crash inside ``pytest_collection_modifyitems``
itself. Calling the hook directly with hand-built items would not reproduce it:
the failure needs pytest's own collection to have produced the item set, and it
aborts the whole run with INTERNALERROR rather than failing a test, so only a
real run observes it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _run_collect(directory: Path) -> subprocess.CompletedProcess[str]:
    """Collect *directory* in a real pytest subprocess with the plugin loaded.

    ``-p no:cacheprovider`` keeps the probe from writing a cache into the
    temporary tree. The plugin is named EXPLICITLY because this collects a
    directory outside the checkout: it is not a pytest11 entry point (that
    would auto-load it into every consumer's session), so it arrives through
    the repository root conftest, and conftest discovery walks up from the test
    file rather than the working directory. Without naming it these probes
    collected with no plugin present - so every "collection does not crash"
    assertion held trivially, proving nothing about the hook they name.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "vaultspec_a2a.testing.plugin",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            str(directory),
        ],
        capture_output=True,
        text=True,
        cwd=str(directory),
        check=False,
    )


def _write(directory: Path, body: str) -> None:
    (directory / "test_probe.py").write_text(body, encoding="utf-8")


def test_a_lone_exclusive_resource_collects(tmp_path: Path) -> None:
    """One test declaring exactly ONE exclusive resource must still collect.

    A key claimed by a single test forms a union-find component of one. That
    component has to be registered before the component snapshot is taken,
    otherwise the group lookup for that key raises ``KeyError`` and pytest
    aborts collection with INTERNALERROR - taking the entire suite down, not
    just the offending test.
    """
    _write(
        tmp_path,
        "import pytest\n"
        "\n"
        '@pytest.mark.resource("scratch-solo")\n'
        "def test_solo() -> None:\n"
        "    assert True\n",
    )

    result = _run_collect(tmp_path)

    assert "INTERNALERROR" not in result.stdout + result.stderr, (
        f"collection crashed:\n{result.stdout}\n{result.stderr}"
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "1 test collected" in result.stdout, result.stdout


def test_merged_exclusive_resources_collect(tmp_path: Path) -> None:
    """Overlapping multi-key claims still merge into one component.

    The companion to the lone-key case: registering every key must not break
    the merging the union-find exists to do. Two tests sharing one key of a
    two-key claim belong to a single group.
    """
    _write(
        tmp_path,
        "import pytest\n"
        "\n"
        '@pytest.mark.resource("scratch-left")\n'
        '@pytest.mark.resource("scratch-shared")\n'
        "def test_one() -> None:\n"
        "    assert True\n"
        "\n"
        '@pytest.mark.resource("scratch-shared")\n'
        '@pytest.mark.resource("scratch-right")\n'
        "def test_two() -> None:\n"
        "    assert True\n",
    )

    result = _run_collect(tmp_path)

    assert "INTERNALERROR" not in result.stdout + result.stderr, (
        f"collection crashed:\n{result.stdout}\n{result.stderr}"
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "2 tests collected" in result.stdout, result.stdout


@pytest.mark.parametrize("declaration", ["", '@pytest.mark.resource("scratch-a")\n'])
def test_collection_survives_with_and_without_claims(
    tmp_path: Path, declaration: str
) -> None:
    """An undeclared test and a declared one both collect.

    Undeclared tests are the bulk of the suite and take no group at all; this
    pins that the grouping pass stays a no-op for them rather than reaching the
    lookup that previously raised.
    """
    _write(
        tmp_path,
        "import pytest\n\n"
        + declaration
        + "def test_probe() -> None:\n    assert True\n",
    )

    result = _run_collect(tmp_path)

    assert "INTERNALERROR" not in result.stdout + result.stderr, (
        f"collection crashed:\n{result.stdout}\n{result.stderr}"
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_plugin_survives_a_wholesale_addopts_override() -> None:
    """A lane that replaces addopts entirely still runs under the plugin.

    The toolchain's service target reaches the service tier by overriding
    ``addopts`` wholesale (``--override-ini``), which once silently disabled
    every lease, group, and admission because the plugin rode in addopts. The
    plugin is deliberately NOT a pytest11 entry point - that would auto-load it
    into every consumer's pytest session, refusing their distribution choices
    and writing leases under their home - so the repository root conftest loads
    it instead.

    That is why the guard suite is written INSIDE the checkout. Conftest
    discovery walks up from the TEST FILE, not from the working directory, so a
    suite in a temp directory never reaches the root conftest and runs with no
    plugin at all. Written there, this guard passed or failed for reasons
    having nothing to do with addopts - which is the same false-subject defect
    it exists to catch.
    """
    repo_root = Path(__file__).resolve().parents[4]
    guard_dir = repo_root / ".pytest-addopts-guard"
    guard_dir.mkdir(exist_ok=True)
    guard = guard_dir / "test_guard.py"
    guard.write_text(
        "def test_guard(resource_leases) -> None:\n    assert resource_leases == {}\n",
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(guard),
                "--override-ini",
                "addopts=--durations=10 --showlocals -ra --capture=sys",
                "-p",
                "no:cacheprovider",
                "-q",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=180,
            check=False,
        )
    finally:
        shutil.rmtree(guard_dir, ignore_errors=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
