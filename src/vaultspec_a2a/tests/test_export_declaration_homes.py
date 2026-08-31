"""A module publishes what it declares, and a package publishes its own surface.

The companion to :mod:`test_canonical_homes`, which pins concepts that were given
one home. This pins the layer above: a name may be OFFERED by one module only.

The distinction that matters is not "does this module re-export" but WHO. A
package ``__init__`` re-exporting its own package's surface is the architecture
this project mandates - that is what a facade is for, and it is not what this
guards. An ordinary module publishing a name it merely imported is different: it
becomes a second place to import that name from, and consumers split across the
two homes without either looking wrong on its own.

Fourteen of these existed, and the recurring justification was convenience -
"one import surface", "the historical surface", "the same public API as before
the decomposition". Each cost the same thing: a reader searching for the owner
found no consumer, and two of them renamed the name on the way through, so a
reader searching for the consumer's spelling found no owner either.

Source is PARSED rather than imported. Several surfaces here are declared lazily
through a PEP 562 ``__getattr__`` and reveal nothing to import-time inspection,
and a declaration can be added without anything importing it - which is exactly
the case worth catching, since it is a second home nobody has wired up yet.

Reading whole-tree counts is the point of the floors below. Every assertion here
is an ABSENCE, and a scan that parsed nothing, decoded nothing, or found no
``__all__`` at all would satisfy every one of them.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[1]

# Floors, not expected values: they only have to be high enough that a scan which
# silently stopped working cannot pass. Set well under the present counts so
# ordinary growth and deletion never touch them.
_MIN_MODULES_PARSED = 600
_MIN_MODULES_DECLARING_EXPORTS = 200
_MIN_EXPORTED_NAMES = 1400


@dataclass(frozen=True)
class _Republication:
    """A module offering a name that some other module declares."""

    module: str
    name: str
    source: str

    def describe(self) -> str:
        renamed = "" if self.source.endswith(f"::{self.name}") else " UNDER A RENAME"
        return f"{self.module} publishes {self.name!r} from {self.source}{renamed}"


def _decode(path: Path) -> str:
    """Read *path* as text without assuming the platform default codec."""
    raw = path.read_bytes()
    for codec in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    msg = f"{path} could not be decoded by any candidate codec"
    raise AssertionError(msg)


def _dotted(path: Path) -> str:
    parts = list(path.relative_to(_SOURCE_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([_SOURCE_ROOT.name, *parts])


def _absolute_target(module: str, node: ast.ImportFrom, is_package: bool) -> str:
    """Resolve a possibly-relative ``from ... import`` to a dotted module path."""
    if node.level == 0:
        return node.module or ""
    parts = [part for part in module.split(".") if part]
    base = parts if is_package else parts[:-1]
    ascend = node.level - 1
    if ascend:
        base = base[:-ascend] if ascend <= len(base) else []
    tail = node.module.split(".") if node.module else []
    return ".".join([*base, *tail])


def _string_members(value: ast.expr) -> list[str]:
    if isinstance(value, ast.List | ast.Tuple | ast.Set):
        return [
            element.value
            for element in value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []


def _exported_names(tree: ast.Module) -> list[str] | None:
    """Return the literal ``__all__`` members, or None where none is declared."""
    declared = False
    names: list[str] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
        ) or (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            declared = True
            names.extend(_string_members(node.value))
    return names if declared else None


def _bindings(
    tree: ast.Module, module: str, is_package: bool
) -> tuple[dict[str, str], set[str]]:
    """Return (name -> declaring module for imported names, locally declared names)."""
    imported: dict[str, str] = {}
    local: set[str] = {"__doc__"}

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.TypeAlias):
                # PEP 695 `type X = ...`; a declaration ast.Assign never sees.
                if isinstance(node.name, ast.Name):
                    local.add(node.name.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    imported[bound] = f"{alias.name}::{alias.name}"
            elif isinstance(node, ast.ImportFrom):
                target = _absolute_target(module, node, is_package)
                for alias in node.names:
                    if alias.name != "*":
                        bound = alias.asname or alias.name
                        imported[bound] = f"{target}::{alias.name}"
            elif isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            ):
                local.add(node.name)
            elif isinstance(node, ast.Assign):
                for target_node in node.targets:
                    if isinstance(target_node, ast.Name):
                        local.add(target_node.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                local.add(node.target.id)
            elif isinstance(node, ast.If | ast.Try):
                visit(node.body)
                visit(getattr(node, "orelse", []))
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)
                visit(getattr(node, "finalbody", []))

    visit(tree.body)
    return imported, local


def _scan() -> tuple[list[_Republication], int, int, int]:
    """Return (findings, modules parsed, modules declaring __all__, names exported)."""
    findings: list[_Republication] = []
    parsed = declaring = exported = 0

    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(_decode(path))
        parsed += 1
        names = _exported_names(tree)
        if names is None:
            continue
        declaring += 1
        exported += len(names)
        # A package facade re-exporting its package's surface is the mandated
        # pattern, and is the subject of its own guard rather than this one.
        if path.name == "__init__.py":
            continue
        module = _dotted(path)
        imported, local = _bindings(tree, module, is_package=False)
        findings.extend(
            _Republication(module, name, imported[name])
            for name in names
            if name not in local and name in imported
        )

    return findings, parsed, declaring, exported


def test_no_ordinary_module_publishes_a_name_it_does_not_declare() -> None:
    """Every exported name is declared by the module that exports it."""
    findings, parsed, declaring, exported = _scan()

    assert parsed >= _MIN_MODULES_PARSED, (
        f"only {parsed} modules parsed; the scan below asserts an ABSENCE and a "
        "tree it cannot read satisfies it vacuously."
    )
    assert declaring >= _MIN_MODULES_DECLARING_EXPORTS, (
        f"only {declaring} modules declared __all__; the export reader has "
        "probably stopped recognising the declarations it is meant to check."
    )
    assert exported >= _MIN_EXPORTED_NAMES, (
        f"only {exported} exported names seen across {declaring} modules; too few "
        "for this tree, so the scan is not reaching what it claims to cover."
    )

    assert not findings, (
        "A module may publish only what it declares. Found "
        f"{len(findings)}:\n\n"
        + "\n".join(
            f"  - {finding.describe()}" for finding in sorted(findings, key=str)
        )
        + "\n\nImport the name from the module that declares it and drop it from "
        "this module's __all__. Keep the import where the module USES the name - "
        "an import that is consumed rather than re-offered is not a second home. "
        "If a module must genuinely offer someone else's name, say why in the "
        "code and record the exemption here, so the next sweep does not reopen it."
    )
