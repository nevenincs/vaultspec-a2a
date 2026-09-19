"""The marker repair applies a distribution's own opt-in, and only that.

Pyright resolves a ``py.typed`` marker from the package root it walks up to, and
a PEP 420 namespace package gives it no such root - so a distribution that ships
its marker at the namespace directory has published one no checker will read.
The repair materializes that marker where the checker looks for it.

These tests build real directory trees and run the real repair over them: what
is under test is a filesystem rule, so a filesystem is the honest fixture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev.doctor import markers, repair_markers

if TYPE_CHECKING:
    from pathlib import Path


def _package(root: Path, *, marker: bool = False) -> Path:
    """Create a regular package at *root*, optionally carrying a marker."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").touch()
    if marker:
        (root / "py.typed").touch()
    return root


def test_namespace_rooted_subpackage_gains_the_marker(tmp_path: Path) -> None:
    """The case pyright cannot resolve: no root package to inherit from."""
    namespace = tmp_path / "ns"
    namespace.mkdir()
    (namespace / "py.typed").touch()
    inner = _package(namespace / "graph")

    assert markers(tmp_path) == [inner]
    assert repair_markers(tmp_path) == 1
    assert (inner / "py.typed").is_file()


def test_regular_package_is_left_alone(tmp_path: Path) -> None:
    """A real root already gives the checker somewhere to read the marker."""
    root = _package(tmp_path / "regular", marker=True)
    _package(root / "sub")

    assert markers(tmp_path) == []
    assert repair_markers(tmp_path) == 0


def test_a_distribution_that_never_opted_in_is_untouched(tmp_path: Path) -> None:
    """Absent a published marker there is no opt-in to apply."""
    namespace = tmp_path / "ns"
    namespace.mkdir()
    _package(namespace / "graph")

    assert markers(tmp_path) == []
    assert repair_markers(tmp_path) == 0


def test_repair_is_idempotent(tmp_path: Path) -> None:
    """A second run creates nothing, so provisioning may call it every time."""
    namespace = tmp_path / "ns"
    namespace.mkdir()
    (namespace / "py.typed").touch()
    _package(namespace / "graph")

    assert repair_markers(tmp_path) == 1
    assert repair_markers(tmp_path) == 0
    assert markers(tmp_path) == []


def test_a_directory_that_is_not_a_package_is_not_marked(tmp_path: Path) -> None:
    """Data directories are not importable and must not collect markers."""
    namespace = tmp_path / "ns"
    namespace.mkdir()
    (namespace / "py.typed").touch()
    (namespace / "static").mkdir()

    assert markers(tmp_path) == []
