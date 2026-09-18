"""Fail while a published name has no consumer anywhere in the tree.

``__all__`` is a promise that a name is part of a module's public surface. A
name on that list which nothing imports is one of two things, and both are
defects: a surface nobody asked for, or a surface somebody stopped using and
nobody retired.

This is the narrowest of the three coverage gates and the one with the
clearest fix. It joins two facts the reachability audit and the source tree
already hold - the names each module publishes, and the names production code
imports - and reports the difference. A name is cleared by ANY importer in the
tree, including a test: the question here is whether the published surface is
consumed at all, not whether it is consumed by shipped code. The stricter
question is :mod:`dev.quality.unused_symbol_coverage`'s, and asking it twice
would report one defect as two.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dev.audit.unreachable_code import declared_exports
from dev.exit_codes import FAILED, OK, TOOL_BROKEN
from dev.paths import PACKAGE_ROOT, REPO_ROOT, repo_relative
from dev.quality.source_import_analysis import (
    UnreadableSourceError,
    imported_symbols,
    load_modules,
    repo_source_roots,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True, order=True)
class UnconsumedExport:
    """One published name with no importer.

    Args:
        path: Repository-relative path of the publishing module.
        module: The publishing module's dotted name.
        name: The published name.
    """

    path: str
    module: str
    name: str


@dataclass(frozen=True, slots=True)
class UnconsumedExportVerdict:
    """The complete live unconsumed-export population.

    Args:
        findings: Every unconsumed export, in stable order.
        exports_scanned: How many published names were checked.
    """

    findings: tuple[UnconsumedExport, ...]
    exports_scanned: int

    @property
    def is_clean(self) -> bool:
        """Whether every published name has an importer."""
        return not self.findings

    def report(self) -> str:
        """Name every current finding, with the denominator it was found in."""
        if self.is_clean:
            return (
                f"unconsumed-export coverage: no findings across "
                f"{self.exports_scanned} published name(s)"
            )
        lines = [
            f"unconsumed-export coverage: {len(self.findings)} finding(s) across "
            f"{self.exports_scanned} published name(s); expected zero",
        ]
        lines += [f"  + {f.path}:{f.name}" for f in self.findings]
        return "\n".join(lines)


def run_gate(
    repo_root: Path = REPO_ROOT,
    package_root: Path = PACKAGE_ROOT,
) -> UnconsumedExportVerdict:
    """Measure the live package's published surface against its importers.

    Args:
        repo_root: The repository to scan.
        package_root: The shipped package's directory.

    Returns:
        The verdict.

    Raises:
        RuntimeError: When any source file could not be parsed. A partial
            parse would report a smaller finding set than the tree warrants
            and read as an improvement.
    """
    try:
        shipped = load_modules(package_root, src_root=repo_root / "src")
        consumers = dict(shipped)
        for root in repo_source_roots(repo_root):
            consumers.update(load_modules(root, src_root=repo_root))
    except UnreadableSourceError as exc:
        msg = f"export scan unavailable, coverage unproven: {exc}"
        raise RuntimeError(msg) from exc

    imported: set[tuple[str, str]] = set()
    for module in consumers.values():
        imported.update(imported_symbols(module))

    findings: list[UnconsumedExport] = []
    scanned = 0
    for name, module in shipped.items():
        # A package `__init__` is a FACADE, and the repository's architecture
        # mandates it: a sub-module re-exports its public API there so
        # consumers import from the package root rather than deep into the
        # hierarchy. Its consumers are therefore outside this tree by design -
        # the dashboard imports `vaultspec_a2a.api`, nothing in `src/` does -
        # so measuring a facade against in-tree importers reports the pattern
        # working as 386 defects. The modules BEHIND the facade are still
        # measured, which is where an abandoned surface actually accumulates.
        if module.is_package_init:
            continue
        for exported in sorted(declared_exports(module.tree)):
            scanned += 1
            if (name, exported) in imported:
                continue
            findings.append(
                UnconsumedExport(
                    path=repo_relative(module.path),
                    module=name,
                    name=exported,
                ),
            )
    return UnconsumedExportVerdict(tuple(sorted(findings)), scanned)


def main() -> int:
    """Print the live set and fail until it is empty.

    Returns:
        :data:`OK` when clean, :data:`FAILED` on findings, and
        :data:`TOOL_BROKEN` when the measurement could not be taken.
    """
    try:
        verdict = run_gate()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return TOOL_BROKEN
    stream = sys.stdout if verdict.is_clean else sys.stderr
    stream.write(verdict.report() + "\n")
    return OK if verdict.is_clean else FAILED


if __name__ == "__main__":
    raise SystemExit(main())
