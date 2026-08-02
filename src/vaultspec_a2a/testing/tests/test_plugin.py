"""Collection-time behaviour of the resource-aware execution plugin.

Driven as a REAL pytest subprocess against real temporary test files, because
the defect these guard is a crash inside ``pytest_collection_modifyitems``
itself. Calling the hook directly with hand-built items would not reproduce it:
the failure needs pytest's own collection to have produced the item set, and it
aborts the whole run with INTERNALERROR rather than failing a test, so only a
real run observes it.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_PLUGIN = "vaultspec_a2a.testing.plugin"


def _run_collect(directory: Path) -> subprocess.CompletedProcess[str]:
    """Collect *directory* in a real pytest subprocess with the plugin loaded.

    ``-p no:cacheprovider`` keeps the probe from writing a cache into the
    temporary tree, and the explicit ``-p`` mirrors how the repository loads the
    plugin in ``addopts``.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            _PLUGIN,
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
