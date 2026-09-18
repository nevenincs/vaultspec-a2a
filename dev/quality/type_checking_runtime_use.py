"""Fail when a TYPE_CHECKING-only import is referenced at runtime.

A name imported under ``if TYPE_CHECKING:`` does not exist when the module
runs. Referencing it anywhere the interpreter actually evaluates is a
``NameError`` on the first execution of that line - and because the guard
exists to break an import cycle or to keep an optional dependency optional,
the line that raises is usually one a test does not cover and a type checker
is happy with, since to the checker the name is perfectly in scope.

Ruff's ``TC`` rules move imports INTO the guard. Nothing in the stock rule set
checks the other direction, which is why this lives here.

What counts as a safe position depends on one line in the module:

* With ``from __future__ import annotations``, every annotation is a string at
  runtime and is never evaluated, so a guarded name in an annotation is
  correct and idiomatic - it is the whole point of the guard.
* WITHOUT that import, annotations are evaluated as the definition executes,
  so the same code raises. This scan applies the weaker rule only to the
  modules that earned it, rather than assuming the future import everywhere
  and silently passing the modules that lack it.

A reference inside the guarded block itself is always safe: that block only
runs under a type checker, where the name exists.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dev.exit_codes import FAILED, OK, TOOL_BROKEN
from dev.paths import PACKAGE_ROOT, REPO_ROOT, repo_relative
from dev.quality.source_import_analysis import (
    UnreadableSourceError,
    load_modules,
    type_checking_guarded_nodes,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from dev.quality.source_import_analysis import SourceModule


@dataclass(frozen=True, slots=True, order=True)
class RuntimeUse:
    """One runtime reference to a name that only exists under type checking.

    Args:
        path: Repository-relative path.
        line: One-based line of the reference.
        name: The referenced name.
        position: Where the reference sits, for the reader's diagnosis.
    """

    path: str
    line: int
    name: str
    position: str


@dataclass(frozen=True, slots=True)
class RuntimeUseVerdict:
    """The complete live population of runtime uses of guarded names.

    Args:
        findings: Every runtime use, in stable order.
        modules_scanned: How many modules were read.
        guarded_names: How many guarded bindings were checked.
    """

    findings: tuple[RuntimeUse, ...]
    modules_scanned: int
    guarded_names: int

    @property
    def is_clean(self) -> bool:
        """Whether no guarded name is referenced at runtime."""
        return not self.findings

    def report(self) -> str:
        """Render the operator-facing console report."""
        scope = (
            f"{self.guarded_names} guarded import(s) across "
            f"{self.modules_scanned} module(s)"
        )
        if self.is_clean:
            return f"type-checking runtime use: no findings across {scope}"
        lines = [
            f"type-checking runtime use: {len(self.findings)} finding(s) across "
            f"{scope}; expected zero",
        ]
        lines += [
            f"  + {f.path}:{f.line} {f.name} ({f.position})" for f in self.findings
        ]
        return "\n".join(lines)


def has_future_annotations(tree: ast.Module) -> bool:
    """Return whether a module defers annotation evaluation.

    Args:
        tree: The parsed module.

    Returns:
        True when ``from __future__ import annotations`` is present.
    """
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def guarded_bindings(tree: ast.Module, guarded: frozenset[int]) -> dict[str, int]:
    """Return the names bound by imports inside the TYPE_CHECKING guard.

    Args:
        tree: The parsed module.
        guarded: The guarded node ids.

    Returns:
        Each bound name mapped to the line that binds it. An aliased import
        binds its alias, which is the name a later reference would use.
    """
    bindings: dict[str, int] = {}
    for node in ast.walk(tree):
        if id(node) not in guarded or not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for alias in node.names:
            bound = alias.asname or alias.name.partition(".")[0]
            bindings.setdefault(bound, node.lineno)
    return bindings


def runtime_bindings(tree: ast.Module, guarded: frozenset[int]) -> frozenset[str]:
    """Return every name the module also binds outside the TYPE_CHECKING guard.

    Args:
        tree: The parsed module.
        guarded: The guarded node ids.

    Returns:
        Each such name.

    This is what makes the scan conservative, and it has to be. The idiomatic
    pattern for a guarded import that IS needed at runtime is to import it
    again locally inside the function that needs it - ``worker_management``
    guards ``httpx`` at module level and re-imports it inside five functions -
    and a scan without this clears none of those. Proving that a particular
    reference is reached by a particular local import needs real scope
    analysis; until then a name bound anywhere at runtime is not reported,
    which trades false negatives for a finding set a reader can trust.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        match node:
            case ast.Import() | ast.ImportFrom():
                names.update(
                    alias.asname or alias.name.partition(".")[0] for alias in node.names
                )
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
            case ast.arg():
                names.add(node.arg)
            case ast.Name() if isinstance(node.ctx, ast.Store | ast.Del):
                names.add(node.id)
            case ast.ExceptHandler() if node.name:
                names.add(node.name)
            case _:
                continue
    return frozenset(names)


def _subtree(*expressions: ast.expr | None) -> set[int]:
    """Return the ids of every node beneath the given expressions."""
    ids: set[int] = set()
    for expression in expressions:
        if expression is not None:
            ids.update(id(child) for child in ast.walk(expression))
    return ids


def lazy_nodes(tree: ast.Module) -> frozenset[int]:
    """Return the ids of every node Python evaluates lazily, or not at all.

    Args:
        tree: The parsed module.

    Returns:
        The ``id()`` of every node inside a PEP 695 type-parameter bound or
        default, and inside a ``type X = ...`` alias value.

    These are evaluated only when something reads ``__bound__`` or resolves the
    alias, which nothing in normal execution does, so a guarded name is
    correct there whether or not the module defers its annotations.
    ``def f[T: Callable[..., object]](...)`` is the shape this clears.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.TypeAlias):
            ids |= _subtree(node.value)
        for param in getattr(node, "type_params", ()):
            ids |= _subtree(
                getattr(param, "bound", None),
                getattr(param, "default_value", None),
            )
    return frozenset(ids)


def unevaluated_annotations(tree: ast.Module, *, deferred: bool) -> frozenset[int]:
    """Return the ids of every node in an annotation Python never evaluates.

    Args:
        tree: The parsed module.
        deferred: Whether the module carries ``from __future__ import
            annotations``.

    Returns:
        The ``id()`` of every node in a safe annotation position.

    With the future import, that is every annotation. Without it, only the
    annotations of LOCAL variables inside a function body: PEP 526 stores a
    module-level or class-level annotation in ``__annotations__`` and
    evaluates it there and then, and a signature annotation is evaluated when
    the ``def`` executes, but a local ``x: T = ...`` annotation is never
    evaluated at all. Treating all four alike reports four false positives per
    test module that annotates a local with a guarded type.
    """
    ids: set[int] = set()

    def visit(node: ast.AST, *, in_function: bool) -> None:
        if isinstance(node, ast.AnnAssign) and (deferred or in_function):
            ids.update(_subtree(node.annotation))
        if deferred:
            if isinstance(node, ast.arg):
                ids.update(_subtree(node.annotation))
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                ids.update(_subtree(node.returns))
        inside = in_function or isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for child in ast.iter_child_nodes(node):
            visit(child, in_function=inside)

    visit(tree, in_function=False)
    return frozenset(ids)


def scan_module(module: SourceModule) -> tuple[tuple[RuntimeUse, ...], int]:
    """Find every runtime reference to a guarded name in one module.

    Args:
        module: The module to scan.

    Returns:
        ``(findings, guarded_binding_count)``.
    """
    guarded = type_checking_guarded_nodes(module.tree)
    bindings = guarded_bindings(module.tree, guarded)
    if not bindings:
        return (), 0

    bindings = {
        name: line
        for name, line in bindings.items()
        if name not in runtime_bindings(module.tree, guarded)
    }
    if not bindings:
        return (), 0

    deferred = has_future_annotations(module.tree)
    safe = unevaluated_annotations(module.tree, deferred=deferred) | lazy_nodes(
        module.tree,
    )

    findings: list[RuntimeUse] = []
    for node in ast.walk(module.tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if node.id not in bindings or id(node) in guarded or id(node) in safe:
            continue
        position = (
            "annotation, evaluated eagerly" if not deferred else "runtime expression"
        )
        findings.append(
            RuntimeUse(
                path=repo_relative(module.path),
                line=node.lineno,
                name=node.id,
                position=position,
            ),
        )
    return tuple(findings), len(bindings)


def run_gate(
    repo_root: Path = REPO_ROOT,
    package_root: Path = PACKAGE_ROOT,
) -> RuntimeUseVerdict:
    """Scan the shipped package for runtime uses of guarded names.

    Args:
        repo_root: The repository to scan.
        package_root: The shipped package's directory.

    Returns:
        The verdict.

    Raises:
        RuntimeError: When any source file could not be parsed.
    """
    try:
        modules = load_modules(package_root, src_root=repo_root / "src")
    except UnreadableSourceError as exc:
        msg = f"scan unavailable, runtime-use coverage unproven: {exc}"
        raise RuntimeError(msg) from exc

    findings: list[RuntimeUse] = []
    guarded_total = 0
    for module in modules.values():
        module_findings, guarded_count = scan_module(module)
        findings += module_findings
        guarded_total += guarded_count
    return RuntimeUseVerdict(
        findings=tuple(sorted(findings)),
        modules_scanned=len(modules),
        guarded_names=guarded_total,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scan and report.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        :data:`OK` when clean, :data:`FAILED` on findings, and
        :data:`TOOL_BROKEN` when the measurement could not be taken.
    """
    parser = argparse.ArgumentParser(
        description="Find runtime references to TYPE_CHECKING-only imports.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        verdict = run_gate()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return TOOL_BROKEN

    if args.json:
        print(
            json.dumps(
                {
                    "clean": verdict.is_clean,
                    "modules_scanned": verdict.modules_scanned,
                    "guarded_names": verdict.guarded_names,
                    "findings": [
                        {
                            "path": f.path,
                            "line": f.line,
                            "name": f.name,
                            "position": f.position,
                        }
                        for f in verdict.findings
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
        )
    else:
        stream = sys.stdout if verdict.is_clean else sys.stderr
        stream.write(verdict.report() + "\n")
    return OK if verdict.is_clean else FAILED


if __name__ == "__main__":
    raise SystemExit(main())
