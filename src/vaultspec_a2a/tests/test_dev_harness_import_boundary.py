"""No shipped module may import the development harness.

``dev/`` is the repository's own tooling - guards, health reports, the just
module namespace, the task runner. It imports ``vaultspec_a2a`` freely, and
that direction is the sanctioned one: the harness inspects the product.

The reverse edge must never exist, for two independent reasons, either of
which alone would justify this guard:

- **It would break every install.** The wheel packages ``src/vaultspec_a2a``
  and nothing else, so ``dev`` is absent from an installed distribution
  entirely. A production module importing it resolves perfectly from a source
  checkout - where the whole repository is present - and raises ``ImportError``
  the moment the package is installed. The failure is invisible exactly where
  the code is written and fatal exactly where nobody is watching it run.
- **It would invert the layering.** Shipped code that reaches into the
  development harness has become aware of scaffolding that is not part of the
  product. The dependency runs one way by design; a cycle here means the
  product cannot be reasoned about, built, or shipped without the tooling that
  is supposed to observe it from outside.

The scan covers the WHOLE package tree, test trees included. A test living
under ``src/`` that imports the harness has the same problem as any other
module there: it is inside the distribution root, and the boundary is a
property of the directory, not of whether a file happens to be exercised in
CI. Work that genuinely needs the harness belongs in the repository-root
``tests/`` tree, which sits outside the package.

Type-checking-only imports count. They do not execute at runtime, but they
name a package an installed distribution cannot resolve, and the distance
between a guarded import and an unguarded one is a single edit.

The scan asserts what it visited. Source is read as BYTES and handed to the
parser, which honours a file's own encoding declaration rather than the
platform default, and the module and import counts are asserted so a scan that
died partway cannot return "no violations found" - on an exhaustiveness check,
a partial answer and a wrong answer are the same answer.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

_PACKAGE_ROOT: Final = Path(__file__).resolve().parents[1]
_SOURCE_ROOT: Final = _PACKAGE_ROOT.parent
_PROJECT_ROOT: Final = _SOURCE_ROOT.parent
_HARNESS: Final = "dev"

_MINIMUM_MODULES: Final = 100
"""Floor on package modules scanned; the tree holds well over twice this."""

_MINIMUM_IMPORT_STATEMENTS: Final = 500
"""Floor on import statements the scan must actually visit.

A walker that quietly stopped visiting would report no violations and look
identical to a clean tree. This is the assertion that tells them apart.
"""


def _absolute_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the root package of every ABSOLUTE import *node* performs.

    Relative imports are skipped: they resolve inside ``vaultspec_a2a`` by
    construction and can never reach a sibling top-level package.
    """
    if isinstance(node, ast.Import):
        return [alias.name.split(".", 1)[0] for alias in node.names]
    if node.level or not node.module:
        return []
    return [node.module.split(".", 1)[0]]


def test_no_packaged_module_imports_the_development_harness() -> None:
    """Nothing under ``src/`` may import ``dev``."""
    harness = _PROJECT_ROOT / _HARNESS / "__init__.py"
    assert harness.is_file(), (
        f"the development harness must be importable at {harness}; without it "
        "this guard is asserting a boundary against a package that does not "
        "exist, and would pass for the wrong reason"
    )

    modules = sorted(_PACKAGE_ROOT.rglob("*.py"))
    visited_imports = 0
    violations: list[str] = []
    for path in modules:
        # Bytes, not text: the parser honours the file's own encoding
        # declaration, where a platform-default decode would raise on a source
        # file that is legal Python and abandon the scan mid-tree.
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            visited_imports += 1
            if _HARNESS not in _absolute_roots(node):
                continue
            site = path.relative_to(_PROJECT_ROOT).as_posix()
            violations.append(f"{site}:{node.lineno}")

    assert len(modules) >= _MINIMUM_MODULES, (
        f"only {len(modules)} modules were scanned, which is fewer than this "
        "package has; the scan did not reach the whole tree, and a partial "
        "exhaustiveness check reports no violations for the wrong reason"
    )
    assert visited_imports >= _MINIMUM_IMPORT_STATEMENTS, (
        f"only {visited_imports} import statements were visited, so the walker "
        "is not doing its job; an empty violation list from a walker that "
        "visits nothing is indistinguishable from a clean tree"
    )
    listing = "\n  ".join(sorted(violations))
    assert not violations, (
        f"these packaged modules import the {_HARNESS!r} development harness, "
        "which the wheel does not ship and which sits on the wrong side of the "
        f"dependency edge:\n  {listing}\n\n"
        "The harness may import the product; the product may never import the "
        "harness. Move the shared mechanism into the package, or move the "
        f"importing module out to the repository-root tests/ tree - do not add "
        f"{_HARNESS!r} to the distribution to make this pass."
    )
