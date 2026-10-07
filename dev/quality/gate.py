"""The exit-code end of every zero-target quality gate.

Each gate in this package measures something different and ends the same way:
a measurement that could not be taken exits :data:`~dev.exit_codes.TOOL_BROKEN`
with its reason on stderr, a clean verdict prints its report to stdout and
exits :data:`~dev.exit_codes.OK`, and findings print to stderr and exit
:data:`~dev.exit_codes.FAILED`. That ending is written here once, so no gate
can read an unavailable measurement as a pass or route its findings somewhere
the others do not.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Protocol

from dev.audit.unreachable_code import UnreachableCodeOutcome, run_unreachable_code_scan
from dev.exit_codes import FAILED, OK, TOOL_BROKEN
from dev.paths import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from dev.audit.unreachable_code import UnreachableCodeResult

__all__ = ["GateVerdict", "emit_verdict", "gate_main", "measured_reachability"]


class GateVerdict(Protocol):
    """What a gate's measurement returns: a cleanliness bit and its report."""

    @property
    def is_clean(self) -> bool:
        """Whether the measured population is empty."""
        ...

    def report(self) -> str:
        """Render the operator-facing console report."""
        ...


def emit_verdict(*, clean: bool, report: str) -> int:
    """Print a gate's report on the stream its verdict calls for.

    Args:
        clean: Whether the gate found nothing.
        report: The rendered report.

    Returns:
        :data:`OK` when clean, otherwise :data:`FAILED`.
    """
    stream = sys.stdout if clean else sys.stderr
    stream.write(report + "\n")
    return OK if clean else FAILED


def gate_main[V: GateVerdict](
    measure: Callable[[], V],
    render: Callable[[V], str] | None = None,
) -> int:
    """Take a gate's measurement and turn it into the contract's exit code.

    Args:
        measure: The gate's measurement. It raises :class:`RuntimeError` when
            the measurement could not be taken.
        render: How to render the verdict, when that is not its own
            :meth:`GateVerdict.report`.

    Returns:
        :data:`OK` when clean, :data:`FAILED` on findings, and
        :data:`TOOL_BROKEN` when the measurement could not be taken.
    """
    try:
        verdict = measure()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return TOOL_BROKEN
    report = verdict.report() if render is None else render(verdict)
    return emit_verdict(clean=verdict.is_clean, report=report)


def measured_reachability(repo_root: Path = REPO_ROOT) -> UnreachableCodeResult:
    """Run the reachability audit for a gate, refusing an unavailable scan.

    Args:
        repo_root: The repository to scan.

    Returns:
        The audit result, which the gate projects into its own verdict.

    Raises:
        RuntimeError: When the scan could not run. A gate that could not
            measure must not report a pass.
    """
    result = run_unreachable_code_scan(repo_root)
    if result.outcome is UnreachableCodeOutcome.ERROR:
        msg = f"reachability scan unavailable, coverage unproven: {result.reason}"
        raise RuntimeError(msg)
    return result
