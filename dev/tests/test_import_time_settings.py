"""No production module reads a setting while it is being imported.

The settings singletons are built at the first read of a value, which is what
keeps a refused configuration - a named file that is not there, a value of the
wrong shape - out of an importer's traceback and puts it at the entry point
that can name it. A single module-level `settings.x` defeats that for every
importer downstream of it: the worker is started as `python -m
vaultspec_a2a.worker`, so one such read in the telemetry package turned a
misconfigured worker into a traceback from inside pydantic-settings.

This walks the real syntax trees rather than grepping, because the reads that
matter are not only assignments: a decorator argument, a default argument and
a class attribute are all evaluated while the module is imported.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from dev.paths import PACKAGE_ROOT, REPO_ROOT, is_test_code

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: The singletons. Reading one of these at module scope builds it there.
_SINGLETONS = frozenset({"settings", "domain_config"})


def _import_time_nodes(node: ast.AST) -> list[ast.AST]:
    """Return the parts of *node* evaluated while the module is imported."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        # A body is not, but a decorator and a default argument are.
        defaults = [*node.args.defaults, *node.args.kw_defaults]
        return [*node.decorator_list, *(d for d in defaults if d is not None)]
    if isinstance(node, ast.ClassDef):
        return list(node.decorator_list)
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return []
    return [node]


def _reads_in(body: list[ast.stmt]) -> Iterator[tuple[int, str]]:
    """Yield every singleton attribute read evaluated at import, with its line."""
    for statement in body:
        if isinstance(statement, ast.ClassDef):
            # A class body runs at import, so its attributes count too.
            yield from _reads_in(statement.body)
        for evaluated in _import_time_nodes(statement):
            for node in ast.walk(evaluated):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in _SINGLETONS
                ):
                    yield node.lineno, f"{node.value.id}.{node.attr}"


def _production_modules() -> Iterator[Path]:
    # Test code is not a production import chain: a test module is imported by
    # a session that has already declared the environment it runs in.
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if not is_test_code(path.relative_to(PACKAGE_ROOT)):
            yield path


def test_no_production_module_reads_a_setting_at_import() -> None:
    found = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{line} reads {read}"
        for path in _production_modules()
        for line, read in _reads_in(ast.parse(path.read_text(encoding="utf-8")).body)
    ]
    assert not found, (
        "these run while their module is imported, so a refused configuration "
        "reaches an importer instead of the entry point that can name it:\n"
        + "\n".join(found)
    )
