"""Every text and count bound on the edge schemas points at a named constant.

A bare ``max_length=256`` or ``_Text(256)`` compiles and runs exactly like
``max_length=MAX_FOO_CHARS``, so nothing short of reading the source catches a
restated bound drifting from its sibling. Q.5(d) of the anti-duplication guard
sweep named this scanner and left it unwritten - the files it covers carried
roughly two dozen bare literals at the time, which would have failed the guard
immediately, so the guard waited on the sweep that pointed each one at a name.
That sweep is done; this is the guard.

Scoped to the three files (and the one package) a published text or count
bound is ever spelled in: ``api/schemas/`` (every production module, not its
tests), ``ipc/schemas.py`` and ``streaming/sse_frames.py``. A name may be
declared PRIVATE to the module that uses it - this guard does not require a
shared home, only a name - so long as it is a name and not a literal repeated
at its use.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeIs

_SOURCE_ROOT = Path(__file__).resolve().parents[1]

#: Every source file a published bound on the versioned or IPC edge may be
#: spelled in. ``api/schemas`` is walked as a package (its tests excluded);
#: the other two are exact files.
_SCANNED_PATHS: Final[tuple[Path, ...]] = (
    _SOURCE_ROOT / "api" / "schemas",
    _SOURCE_ROOT / "ipc" / "schemas.py",
    _SOURCE_ROOT / "streaming" / "sse_frames.py",
)

#: Keyword arguments whose value, if a bare integer literal, restates a bound
#: that belongs to a name.
_BOUND_KEYWORDS: Final[frozenset[str]] = frozenset({"max_length", "le"})

#: Callables whose first positional argument, if a bare integer literal,
#: restates a text-field character cap.
_BOUND_CALLEES: Final[frozenset[str]] = frozenset({"_Text"})


@dataclass(frozen=True, slots=True)
class _LiteralBound:
    path: str
    line: int
    detail: str


def _production_modules() -> list[Path]:
    """Every production ``.py`` file under the scanned paths."""
    modules: list[Path] = []
    for target in _SCANNED_PATHS:
        if target.is_file():
            modules.append(target)
            continue
        modules.extend(
            path
            for path in sorted(target.rglob("*.py"))
            if "tests" not in path.relative_to(target).parts
        )
    return modules


def _is_int_literal(node: ast.expr) -> TypeIs[ast.Constant]:
    """Whether *node* is a bare ``int`` constant (never a ``bool``)."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def _callee_name(node: ast.expr) -> str | None:
    """The bare name of a call target, for ``Name`` and ``Attribute`` alike."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal_bounds_in(path: Path) -> list[_LiteralBound]:
    """Every bare-literal bound a single module's call sites spell out."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    relative = path.relative_to(_SOURCE_ROOT).as_posix()
    found: list[_LiteralBound] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in _BOUND_KEYWORDS and _is_int_literal(keyword.value):
                found.append(
                    _LiteralBound(
                        path=relative,
                        line=node.lineno,
                        detail=f"{keyword.arg}={keyword.value.value}",
                    )
                )
        name = _callee_name(node.func)
        if name in _BOUND_CALLEES and node.args and _is_int_literal(node.args[0]):
            found.append(
                _LiteralBound(
                    path=relative,
                    line=node.lineno,
                    detail=f"{name}({node.args[0].value})",
                )
            )
    return found


def test_edge_schemas_carry_no_bare_literal_bound() -> None:
    """Q.5(d): no max_length=<int> / le=<int> / _Text(<int>) literal survives.

    A visited-files floor keeps this from passing vacuously on a mis-rooted
    scan: the scanned paths cover six production modules today, so a count
    far below that would mean the scan found nothing to look at rather than
    nothing to flag.
    """
    modules = _production_modules()
    assert len(modules) >= 5, (
        f"only {len(modules)} production module(s) were scanned; "
        "the scan root looks wrong"
    )

    violations = [bound for module in modules for bound in _literal_bounds_in(module)]

    assert violations == [], "\n".join(
        [
            "bare literal bounds found; point each at a named constant:",
            *(f"  {bound.path}:{bound.line} — {bound.detail}" for bound in violations),
        ]
    )
