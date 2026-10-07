"""The repository's filesystem anchors, stated once.

Every instrument beneath ``dev/`` that reads the tree needs the same handful of
answers - where the repository root is, where the shipped package lives, which
trees hold source and which directories hold test code, and what encoding to
read source with - and each one that derived them itself derived them slightly
differently. ``Path(__file__).parents[2]`` is correct from ``dev/audit/`` and
wrong from ``dev/``, and a module that guesses from :func:`os.getcwd` reports a
different tree depending on where it was invoked.

This module is stdlib-only and imports nothing else from ``dev`` so that an
instrument which runs before the virtual environment exists can depend on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = [
    "PACKAGE",
    "PACKAGE_PATH",
    "PACKAGE_ROOT",
    "PYTHON_PATHS",
    "REPO_ROOT",
    "SKIPPED_DIRS",
    "SRC_ROOT",
    "TEST_SUPPORT",
    "TEST_TIERS",
    "UTF_8",
    "is_test_code",
    "is_test_path",
    "repo_relative",
]

#: The repository root. Anchored to this file's location rather than to the
#: working directory: an instrument invoked from a subdirectory, from an
#: editor, or from a pre-commit hook must measure the same tree.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: The source root the shipped distribution is built from.
SRC_ROOT: Final[Path] = REPO_ROOT / "src"

#: The shipped import package.
PACKAGE: Final[str] = "vaultspec_a2a"

#: The shipped package's directory.
PACKAGE_ROOT: Final[Path] = SRC_ROOT / PACKAGE

#: :data:`PACKAGE_ROOT` relative to the repository root, in forward-slash form:
#: the spelling a tool takes on its command line when it runs from the root.
PACKAGE_PATH: Final[str] = PACKAGE_ROOT.relative_to(REPO_ROOT).as_posix()

#: Python trees that carry committed source and are therefore linted and type
#: checked. Naming the trees rather than the repository root is what stops a
#: new top-level folder from linting itself into an exception by simply
#: existing.
PYTHON_PATHS: Final[tuple[str, ...]] = ("src", "dev", "docs", "scripts", "packaging")

#: The encoding every source and report file is read and written with. Named
#: rather than defaulted because Windows' default is the ANSI code page, which
#: silently mangles any non-ASCII source this tree contains.
UTF_8: Final[str] = "utf-8"

#: Directory names no scan descends into.
SKIPPED_DIRS: Final[frozenset[str]] = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"},
)

#: The test tiers carried inside the shipped package, as directory names.
#: A path with any of these as a component is test code, wherever it sits.
TEST_TIERS: Final[tuple[str, ...]] = (
    "tests",
    "service_tests",
    "desktop_tests",
    "acceptance",
)

#: The shipped package's shared test-support package. It is not a tier -
#: nothing in it is collected - but it is test code all the same, so a rule
#: that holds product code to a stricter standard than tests does not apply
#: to it.
TEST_SUPPORT: Final[str] = "testing"


def repo_relative(path: Path, root: Path = REPO_ROOT) -> str:
    """Render a path relative to the repository, in forward-slash form.

    Args:
        path: The path to render.
        root: The root to render it against.

    Returns:
        The repository-relative POSIX form, or the absolute POSIX form when
        the path lies outside ``root``. Never a backslash: a report whose
        paths differ between Windows and Linux cannot be diffed across runs.
    """
    resolved = path if path.is_absolute() else (root / path)
    try:
        return resolved.resolve().relative_to(root).as_posix()
    except ValueError:
        return resolved.as_posix()


def is_test_path(path: Path) -> bool:
    """Return whether a path is test code by virtue of where it sits.

    Args:
        path: The path to classify.

    Returns:
        True when any component names a test tier, or the file itself follows
        pytest's ``test_*``/``conftest`` naming. Matching on components rather
        than on the two top-level directories is what covers the per-package
        ``*/tests/`` layout this repository actually uses.
    """
    if any(part in TEST_TIERS for part in path.parts):
        return True
    return path.name.startswith("test_") or path.name == "conftest.py"


def is_test_code(path: Path) -> bool:
    """Return whether a path is test code or the support code tests share.

    Args:
        path: The path to classify.

    Returns:
        True when :func:`is_test_path` holds, or when any component names
        :data:`TEST_SUPPORT`. An import-graph analysis keeps the support
        package in view, because the tiers import it; a scan that ranks or
        gates PRODUCT code does not, because it is no more product code than
        the tests it serves.
    """
    return is_test_path(path) or TEST_SUPPORT in path.parts
