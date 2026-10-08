"""Fail while any shipped module is unreachable from a shipped entry point.

The reachability audit owns discovery; this gate owns only the verdict, and it
has no baseline, no namespace exclusion, and no intentional-disposition input.
Every live module finding is emitted and only an empty finding set is green.

That absence is deliberate. A gate with a baseline reports the DELTA against a
number someone once wrote down, so the debt it was standing over becomes
invisible the moment it is recorded - and the recorded number is the thing that
gets updated when the gate goes red. This gate can only be satisfied by
deleting the module or by giving it a caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dev.audit.unreachable_code import ModuleReach
from dev.paths import REPO_ROOT
from dev.quality.gate import gate_main, measured_reachability

if TYPE_CHECKING:
    from pathlib import Path

    from dev.audit.unreachable_code import ModuleFinding, UnreachableCodeResult

__all__ = [
    "NOT_REACHED",
    "UnreachableModuleVerdict",
    "evaluate",
    "main",
    "run_gate",
]

#: The classifications that are not "something an installed user runs reaches
#: this". A type-only module is included: its import never executes, so the
#: bytes ship and nothing loads them.
NOT_REACHED = frozenset({ModuleReach.UNREACHABLE, ModuleReach.TYPE_ONLY})


@dataclass(frozen=True, slots=True)
class UnreachableModuleVerdict:
    """The complete current set of modules no entry point reaches.

    Args:
        findings: Every module finding, in stable order.
    """

    findings: tuple[ModuleFinding, ...]

    @property
    def is_clean(self) -> bool:
        """Whether every shipped module is reachable."""
        return not self.findings

    def report(self) -> str:
        """Name every live finding without assigning it a development status."""
        if self.is_clean:
            return "unreachable-module coverage: no findings"
        lines = [
            f"unreachable-module coverage: {len(self.findings)} finding(s); "
            "expected zero",
        ]
        lines += [
            f"  + {f.module} ({f.reach.value}; {f.path})"
            + (f" [used by: {', '.join(f.used_by)}]" if f.used_by else "")
            for f in self.findings
        ]
        return "\n".join(lines)


def evaluate(result: UnreachableCodeResult) -> UnreachableModuleVerdict:
    """Project the audit's module findings into the zero-target gate.

    Args:
        result: The audit result.

    Returns:
        The verdict.
    """
    return UnreachableModuleVerdict(
        findings=tuple(
            sorted(
                (f for f in result.modules if f.reach in NOT_REACHED),
                key=lambda f: f.module,
            ),
        ),
    )


def run_gate(repo_root: Path = REPO_ROOT) -> UnreachableModuleVerdict:
    """Scan the real shipped tree, refusing an unavailable measurement.

    Args:
        repo_root: The repository to scan.

    Returns:
        The verdict.

    Raises:
        RuntimeError: When the scan could not run. A gate that could not
            measure must not report a pass.
    """
    return evaluate(measured_reachability(repo_root))


def main() -> int:
    """Print the live set and fail until it is empty.

    Returns:
        The exit code :func:`~dev.quality.gate.gate_main` maps the verdict
        onto.
    """
    return gate_main(run_gate)


if __name__ == "__main__":
    raise SystemExit(main())
