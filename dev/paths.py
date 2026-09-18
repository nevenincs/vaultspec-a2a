"""The repository's filesystem anchors, stated once.

Every instrument beneath ``dev/`` that reads the tree needs the same three
answers - where the repository root is, where the shipped package lives, and
what encoding to read source with - and each one that derived them itself
derived them slightly differently. ``Path(__file__).parents[2]`` is correct
from ``dev/audit/`` and wrong from ``dev/``, and a module that guesses from
:func:`os.getcwd` reports a different tree depending on where it was invoked.

This module is stdlib-only and imports nothing else from ``dev`` so that an
instrument which runs before the virtual environment exists can depend on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

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
