"""PEP 561 marker repair for namespace-rooted distributions.

PEP 561 states that a ``py.typed`` marker "applies recursively: if a top-level
package includes it, all its sub-packages MUST support type checking as well".
Pyright declines to implement that clause - the request was closed "as designed"
- and resolves the marker only from the package root it walks up to.

For a regular package that costs nothing: the root is a real package, the walk
finds the marker there, and every subpackage inherits it. For a PEP 420
namespace package there is no such root. Each subpackage is its own resolution
root, so a distribution that ships its marker at the namespace directory has
published a marker no type checker will ever read, and every module under it
type-checks as ``Unknown``.

This repair materializes the marker the distribution already published into the
subpackages that need to carry it themselves. It invents no policy and names no
package: the distribution's own marker is the opt-in, and the only packages
touched are those whose parent is a namespace directory carrying one. A
distribution that never opted in is never touched.

The repair targets the environment, not the tree: markers live in
``site-packages`` and are erased by each ``uv sync``, so this runs after
provisioning rather than being recorded anywhere in the repository.
"""

from __future__ import annotations

import sysconfig
from pathlib import Path

__all__ = ["markers", "repair_markers"]


def _site_packages() -> Path:
    """The interpreter's third-party install directory."""
    return Path(sysconfig.get_paths()["purelib"])


def _is_namespace_root(directory: Path) -> bool:
    """Whether *directory* is a PEP 420 namespace package rather than a package.

    A namespace directory has no ``__init__.py``. That absence is exactly what
    denies a type checker the package root it would otherwise read the marker
    from.
    """
    return not (directory / "__init__.py").exists()


def _unmarked_subpackages(root: Path) -> list[Path]:
    """Regular subpackages under *root* that carry no marker of their own."""
    found: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        if candidate.name == "__pycache__" or not candidate.is_dir():
            continue
        if not (candidate / "__init__.py").exists():
            continue
        if (candidate / "py.typed").exists():
            continue
        found.append(candidate)
    return found


def markers(site_packages: Path | None = None) -> list[Path]:
    """Subpackage directories that need a marker they do not have.

    Args:
        site_packages: The install directory to scan, or ``None`` for this
            interpreter's own.

    Returns:
        The directories to write a marker into, in a stable order.
    """
    base = _site_packages() if site_packages is None else site_packages
    needed: list[Path] = []
    for marker in sorted(base.glob("*/py.typed")):
        root = marker.parent
        if not _is_namespace_root(root):
            continue
        needed.extend(_unmarked_subpackages(root))
    return needed


def repair_markers(site_packages: Path | None = None) -> int:
    """Write the missing markers and report how many were created.

    Idempotent: a marker that already exists is left alone, so a repeat run
    creates nothing and reports zero.

    Args:
        site_packages: The install directory to repair, or ``None`` for this
            interpreter's own.

    Returns:
        The number of markers created.
    """
    created = 0
    for package in markers(site_packages):
        (package / "py.typed").touch()
        created += 1
    return created
