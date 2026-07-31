"""Gate: intra-package imports must be relative.

The repository mandate is that every import *within* ``vaultspec_a2a`` uses a
relative form (``from . import utils``, ``from ..core import Registry``), with
absolute imports reserved for third-party dependencies. An absolute self-import
pins a module to the package's current layout, so a rename that a relative
import would follow silently becomes an ``ImportError`` instead.

Ruff's ``TID252`` enforces the opposite convention and there is no stock rule
for this direction, which is why the check lives here. It walks the AST rather
than matching text, so a match is a real ``import`` statement and never a
mention inside a string, a docstring, or a comment.

Run through the harness::

    just dev lint imports

An import that genuinely must be absolute - a runtime plugin lookup, a lazy
module path resolved by name - is exempted with a trailing ``# absolute-import-ok``
comment on the offending line.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: The package whose internals must import themselves relatively.
PACKAGE = "vaultspec_a2a"

#: Source root scanned by the gate.
ROOT = Path("src") / PACKAGE

#: Trailing comment that exempts a single line.
ALLOW = "absolute-import-ok"


def _offending_lines(tree: ast.Module) -> list[tuple[int, str]]:
    """Return every absolute self-import in one parsed module.

    Args:
        tree: The parsed module.

    Returns:
        ``(lineno, statement)`` pairs, in source order.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `level > 0` is already relative, which is the required form.
            if node.level == 0 and node.module and _is_self(node.module):
                found.append((node.lineno, f"from {node.module} import ..."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _is_self(alias.name):
                    found.append((node.lineno, f"import {alias.name}"))
    return sorted(found)


def _is_self(module: str) -> bool:
    """Return whether a dotted module path names this package."""
    return module == PACKAGE or module.startswith(f"{PACKAGE}.")


def main() -> int:
    """Scan the package and report every absolute self-import.

    Returns:
        0 when the package is clean, 1 when any violation remains, and 2 when
        the source root is missing (which means the gate was run from the
        wrong directory and must not report a false pass).
    """
    if not ROOT.is_dir():
        print(
            f"{ROOT} not found - run this from the repository root.",
            file=sys.stderr,
        )
        return 2

    violations: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            print(f"{path}: could not parse: {exc}", file=sys.stderr)
            return 2
        for lineno, statement in _offending_lines(tree):
            source = lines[lineno - 1] if lineno <= len(lines) else ""
            if ALLOW in source:
                continue
            violations.append(f"{path}:{lineno}: {statement}")

    if violations:
        print(
            f"{len(violations)} absolute intra-package import(s) found. "
            f"Use a relative import, or annotate the line with # {ALLOW}:",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
