"""Applying a package's layer marks, stated once for every package that does it.

The layer vocabulary is a partition, not a per-package taste: a test is ``core``
(domain logic) or ``middleware`` (infrastructure), and ``unit`` is an ORTHOGONAL
claim of purity carried on top. Two package conftests had written the same walk
over that partition independently, and they agreed only by upkeep - which is the
arrangement a marker vocabulary exists to prevent, since the whole point of the
marks is that one selection means one thing across the tree.

What varies between packages is DATA - which files are infrastructure, which are
not pure - so that is what a caller supplies. The walk itself lives here.

Purity is decided by two mechanisms that are complements rather than
alternatives, and dropping either loses real cases:

- A file that performs I/O in its OWN body - opening a database, spawning a
  child - is named by the caller, because nothing about the item reveals it.
- A test that acquires I/O by NAMING A FIXTURE reveals nothing in its body at
  all, and the fixture is usually defined in a ``conftest.py`` above it. That is
  asked of pytest per ITEM rather than per file, since a file-level exclusion
  would strip the claim from the pure tests that merely share a file with an
  impure one.

``unit`` is machine-readable, so a wrong claim is worse than no claim: a
selection that excludes impure tests silently INCLUDES anything neither
mechanism catches, and a run believed hermetic is not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .purity import uses_impure_fixture

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

__all__ = ["apply_layer_markers"]


def apply_layer_markers(
    items: Iterable[pytest.Item],
    *,
    package_dir: str,
    middleware_files: Collection[str],
    impure_files: Collection[str] = frozenset(),
) -> None:
    """Mark every item under *package_dir* by layer, and by purity where earned.

    Items outside *package_dir* are left alone: each package's conftest speaks
    only for the directory it sits in, and every hook receives the whole
    collected session.

    A file in *middleware_files* is infrastructure and takes that mark alone -
    ``unit`` is not offered there, because the layer already says the test drives
    real services. Everything else is ``core``, and additionally ``unit`` unless
    the file is named in *impure_files* or the item's resolved fixture closure
    reaches a fixture declared impure.
    """
    for item in items:
        if not str(item.path).startswith(package_dir):
            continue
        if item.path.name in middleware_files:
            item.add_marker(pytest.mark.middleware)
            continue
        item.add_marker(pytest.mark.core)
        if item.path.name not in impure_files and not uses_impure_fixture(item):
            item.add_marker(pytest.mark.unit)
