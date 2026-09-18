"""Fail while an unused top-level symbol or an orphaned test remains.

The reachability audit answers the top-level symbol question exactly - an
import of the defining module, a use inside it, or a string naming it, and
nothing else - so its symbol findings are a verdict rather than a lead, and
this gate takes every one of them.

A symbol whose only reader is its own unit test is still a finding here, and
that asymmetry is the point: code kept alive by the test written for it is the
shape dead code takes in a tree with a test suite. The audit's ``used by:
tests`` label says so on the line, which is enough for a reader to decide
whether to delete the pair or give the symbol a caller.

Like its sibling gates this has no baseline and no exclusion list.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dev.audit.unreachable_code import UnreachableCodeOutcome, run_unreachable_code_scan
from dev.exit_codes import FAILED, OK, TOOL_BROKEN
from dev.paths import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    from dev.audit.unreachable_code import (
        SymbolFinding,
        TestFinding,
        UnreachableCodeResult,
    )


@dataclass(frozen=True, slots=True)
class UnusedSymbolVerdict:
    """The complete live unused-symbol and orphaned-test populations.

    Args:
        symbols: Every unused top-level symbol.
        orphan_tests: Every test module whose subjects are all findings.
    """

    symbols: tuple[SymbolFinding, ...]
    orphan_tests: tuple[TestFinding, ...]

    @property
    def is_clean(self) -> bool:
        """Whether both populations are empty."""
        return not self.symbols and not self.orphan_tests

    def report(self) -> str:
        """Name every symbol and orphaned-test finding."""
        if self.is_clean:
            return "unused-symbol coverage: no findings"
        lines = [
            "unused-symbol coverage: "
            f"{len(self.symbols)} unused symbol(s), "
            f"{len(self.orphan_tests)} orphaned test module(s); expected zero",
        ]
        lines += [
            f"  + {f.path}:{f.line} {f.kind.value} {f.name}"
            + (f" [used by: {', '.join(f.used_by)}]" if f.used_by else "")
            for f in self.symbols
        ]
        lines += [f"  + test:{f.module} ({f.path})" for f in self.orphan_tests]
        return "\n".join(lines)


def evaluate(result: UnreachableCodeResult) -> UnusedSymbolVerdict:
    """Project the audit's symbol and test findings into the zero-target gate.

    Args:
        result: The audit result.

    Returns:
        The verdict. Nothing is excluded: no package, no status, no identity.
    """
    return UnusedSymbolVerdict(
        symbols=tuple(sorted(result.symbols, key=lambda f: (f.module, f.name, f.line))),
        orphan_tests=tuple(sorted(result.tests, key=lambda f: f.module)),
    )


def run_gate(repo_root: Path = REPO_ROOT) -> UnusedSymbolVerdict:
    """Measure the live tree, refusing an unavailable scan.

    Args:
        repo_root: The repository to scan.

    Returns:
        The verdict.

    Raises:
        RuntimeError: When the scan could not run.
    """
    result = run_unreachable_code_scan(repo_root)
    if result.outcome is UnreachableCodeOutcome.ERROR:
        msg = f"reachability scan unavailable, coverage unproven: {result.reason}"
        raise RuntimeError(msg)
    return evaluate(result)


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
