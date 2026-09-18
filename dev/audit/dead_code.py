#!/usr/bin/env python
"""The single vulture runner: invoke it, parse it, classify it honestly.

``just audit-dead-code`` used to be ``uv run vulture`` and nothing else, which
left two questions unanswered that a reader of the result has to ask:

* **Did it look at anything?** vulture exits 0 both when it inspected the
  production tree and found nothing and when it inspected nothing at all - an
  emptied path, a mistyped config, a tree that was never checked out. The exit
  code alone cannot tell those apart, so this module counts the modules the
  configured paths actually offer and refuses to call a scan clean unless that
  count clears :data:`MINIMUM_OFFERED_MODULES`. The denominator travels with
  the verdict: a green that does not say how much it read is not a green.

* **How sure is it?** vulture reports a bare confidence percentage per finding
  and the repository's ``min_confidence`` is 60, which admits the whole class
  of maybes on purpose. Bucketing at 80% separates "this name appears nowhere"
  from "vulture could not see a reference it may well have missed".

vulture's own exit codes carry the rest of the classification: ``0`` clean,
``3`` found dead code, and anything else (``1`` invalid input, ``2`` invalid
arguments) a genuine tool error that must never read as clean.

A NOTE ON THIS TREE'S FINDINGS. vulture is a name-frequency heuristic with no
model of framework registration, so every FastAPI route handler, every typer
command, and every pytest hook in this repository is reported as unused - they
are reached by decorator, and their names appear exactly once. That is why this
target is advisory and why :mod:`dev.audit.unreachable_code` exists beside it:
the reachability audit walks the import graph from the shipped entry points and
treats a non-trivial decorator as a registration, so it answers the same
question without the false class.

See Also:
    :mod:`dev.audit.unreachable_code`
        The entrypoint-rooted reachability audit; it models what this cannot.
    :func:`run_dead_code_scan`
        The one entry point every dead-code consumer calls.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from dev.exit_codes import ADVISORY_BROKEN, OK
from dev.paths import REPO_ROOT
from dev.process import ToolUnavailableError, run_tool

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: The trees vulture is offered. ``[tool.vulture] paths`` in ``pyproject.toml``
#: is the authority for what it SCANS; this is the authority for what this
#: module counts, and the two are held equal by the guard test.
TARGETS: Final[tuple[str, ...]] = ("src/vaultspec_a2a",)

#: vulture's stable line shape: ``path:line: message (NN% confidence)``.
FINDING_LINE: Final = re.compile(
    r"^(?P<path>.+):(?P<line>\d+): (?P<message>.+) \((?P<confidence>\d+)% confidence",
)

#: The confidence at which a finding stops being a lead and becomes a claim.
HIGH_CONFIDENCE: Final[int] = 80

#: How many findings the console report names before it says "... more".
FINDING_CAP: Final[int] = 40

#: vulture's own statuses.
EXIT_CLEAN: Final[int] = 0
EXIT_FINDINGS: Final[int] = 3

#: The floor below which a clean scan proves nothing. The package offered 793
#: modules when this was set; the floor sits near half that, so ordinary churn
#: cannot trip it and a wholesale loss cannot hide behind a 0 exit status.
MINIMUM_OFFERED_MODULES: Final[int] = 400

#: A dead-code scan is cheap; one that has not answered in three minutes hung.
TIMEOUT_SECONDS: Final[float] = 180.0

_HIGH_LABEL: Final[str] = f"high (>={HIGH_CONFIDENCE}%)"
_MODERATE_LABEL: Final[str] = f"moderate (<{HIGH_CONFIDENCE}%)"


class DeadCodeOutcome(StrEnum):
    """The three honest states a vulture scan can land in."""

    CLEAN = "clean"
    FINDINGS = "findings"
    ERROR = "error"


@dataclass(frozen=True, slots=True, order=True)
class DeadCodeFinding:
    """One vulture finding.

    Args:
        path: Repository-relative, forward-slash path.
        line: One-based line number.
        message: vulture's own description, verbatim.
        confidence: vulture's confidence percentage.
    """

    path: str
    line: int
    message: str
    confidence: int


@dataclass(frozen=True, slots=True)
class DeadCodeResult:
    """A dead-code scan's typed outcome.

    Construct through :meth:`clean`, :meth:`from_findings`, or :meth:`error`
    rather than directly, so each outcome's binding to its evidence holds by
    construction rather than by a caller remembering to supply it.
    """

    outcome: DeadCodeOutcome
    modules_offered: int = 0
    findings: tuple[DeadCodeFinding, ...] = ()
    reason: str = ""

    @classmethod
    def clean(cls, *, modules_offered: int) -> DeadCodeResult:
        """Build the outcome of a scan that inspected modules and found nothing.

        Args:
            modules_offered: How many modules the scan was handed.

        Returns:
            The clean result.

        Raises:
            ValueError: When no module was offered, which is a scan that
                demonstrated nothing rather than a clean one.
        """
        if modules_offered <= 0:
            msg = "clean requires a scan that demonstrably inspected modules"
            raise ValueError(msg)
        return cls(outcome=DeadCodeOutcome.CLEAN, modules_offered=modules_offered)

    @classmethod
    def from_findings(
        cls,
        findings: tuple[DeadCodeFinding, ...],
        *,
        modules_offered: int,
    ) -> DeadCodeResult:
        """Build the outcome of a scan that found dead code.

        Args:
            findings: Every finding, already parsed.
            modules_offered: How many modules the scan was handed.

        Returns:
            The findings result.

        Raises:
            ValueError: When the finding set is empty.
        """
        if not findings:
            msg = "from_findings requires at least one finding"
            raise ValueError(msg)
        return cls(
            outcome=DeadCodeOutcome.FINDINGS,
            modules_offered=modules_offered,
            findings=tuple(sorted(findings)),
        )

    @classmethod
    def error(cls, reason: str) -> DeadCodeResult:
        """Build the outcome of a scan that produced no trustworthy result.

        Args:
            reason: What went wrong, in one clause.

        Returns:
            The error result.
        """
        return cls(outcome=DeadCodeOutcome.ERROR, reason=reason)

    @property
    def is_green(self) -> bool:
        """Whether this result honestly earns a green verdict."""
        return self.outcome is DeadCodeOutcome.CLEAN

    @property
    def count_by_confidence(self) -> dict[str, int]:
        """Return finding counts split at :data:`HIGH_CONFIDENCE`.

        vulture reports a bare percentage rather than a named severity, so
        this coarse split is the closest honest analogue. It is computed here
        rather than invented by each caller.
        """
        buckets = {_HIGH_LABEL: 0, _MODERATE_LABEL: 0}
        for finding in self.findings:
            key = (
                _HIGH_LABEL
                if finding.confidence >= HIGH_CONFIDENCE
                else _MODERATE_LABEL
            )
            buckets[key] += 1
        return {key: count for key, count in buckets.items() if count}

    def headline(self) -> str:
        """Render the one-line human summary of the outcome."""
        if self.outcome is DeadCodeOutcome.ERROR:
            return f"signal unavailable this cycle: {self.reason}"
        if self.outcome is DeadCodeOutcome.CLEAN:
            return f"no dead code found across {self.modules_offered} module(s)"
        breakdown = ", ".join(
            f"{count} {label}" for label, count in self.count_by_confidence.items()
        )
        return (
            f"{len(self.findings)} finding(s) across "
            f"{self.modules_offered} module(s) ({breakdown})"
        )


def offered_module_population(repo_root: Path = REPO_ROOT) -> int:
    """Count the Python modules :data:`TARGETS` actually offers vulture.

    Args:
        repo_root: The tree to count in.

    Returns:
        The module count. This BOUNDS the analysed population from above
        rather than measuring it: vulture applies its own ``exclude`` patterns
        after these paths are handed over, so an over-broad exclude is outside
        what this can see. A target that has been emptied, moved, or never
        checked out is inside it, and that is the degradation that makes a
        clean scan vacuous.
    """
    offered = 0
    for target in TARGETS:
        candidate = repo_root / target
        if candidate.is_file():
            offered += 1 if candidate.suffix == ".py" else 0
        elif candidate.is_dir():
            offered += sum(1 for _ in candidate.rglob("*.py"))
    return offered


def vulture_command() -> list[str]:
    """Build the one vulture command line, without the ``uv run`` prefix."""
    return ["vulture", "--config", "pyproject.toml"]


def parse_vulture_output(
    stdout: str, repo_root: Path = REPO_ROOT
) -> tuple[DeadCodeFinding, ...]:
    """Parse vulture's ``path:line: message (NN% confidence)`` lines.

    Args:
        stdout: vulture's captured standard output.
        repo_root: The root paths are rendered relative to.

    Returns:
        Every parsed finding, in stable order.
    """
    findings: list[DeadCodeFinding] = []
    for raw in stdout.splitlines():
        match = FINDING_LINE.match(raw.strip())
        if match is None:
            continue
        path = match["path"].replace("\\", "/")
        prefix = repo_root.as_posix() + "/"
        findings.append(
            DeadCodeFinding(
                path=path.removeprefix(prefix),
                line=int(match["line"]),
                message=match["message"],
                confidence=int(match["confidence"]),
            ),
        )
    return tuple(sorted(findings))


def run_dead_code_scan(
    repo_root: Path = REPO_ROOT,
    *,
    timeout: float = TIMEOUT_SECONDS,
) -> DeadCodeResult:
    """Run vulture over the production tree and classify the outcome.

    Args:
        repo_root: The tree to scan.
        timeout: Seconds to wait before giving up on vulture.

    Returns:
        The typed result. This is the single entry point for every dead-code
        consumer, so there is deliberately no second vulture invocation
        anywhere in the tree.
    """
    offered = offered_module_population(repo_root)
    if offered < MINIMUM_OFFERED_MODULES:
        return DeadCodeResult.error(
            f"vulture was offered {offered} Python module(s), under the "
            f"{MINIMUM_OFFERED_MODULES} the production tree must hold, so exit 0 "
            "would prove nothing about dead code",
        )

    try:
        completed = run_tool(vulture_command(), cwd=repo_root, timeout=timeout)
    except ToolUnavailableError as exc:
        return DeadCodeResult.error(str(exc))

    if completed.returncode == EXIT_CLEAN:
        return DeadCodeResult.clean(modules_offered=offered)

    if completed.returncode == EXIT_FINDINGS:
        findings = parse_vulture_output(completed.stdout, repo_root)
        if not findings:
            return DeadCodeResult.error(
                "vulture exited 3 (findings expected) but produced no "
                "parseable finding line",
            )
        return DeadCodeResult.from_findings(findings, modules_offered=offered)

    detail = (completed.stderr or completed.stdout or "").strip().splitlines()
    tail = detail[-1] if detail else "no diagnostic output"
    return DeadCodeResult.error(f"vulture exited {completed.returncode}: {tail}")


def render_console_report(
    result: DeadCodeResult,
    *,
    full: bool = False,
    cap: int = FINDING_CAP,
) -> str:
    """Render the operator-facing console report.

    Args:
        result: The scan result.
        full: List every finding rather than the first ``cap``.
        cap: How many findings to list when ``full`` is not set.

    Returns:
        The report text.
    """
    lines = [f"dead code: {result.headline()}"]
    if result.outcome is not DeadCodeOutcome.FINDINGS:
        return lines[0]

    # Highest confidence first: the top of a capped list should be the part
    # most worth reading, not whichever path sorts first.
    ranked = sorted(result.findings, key=lambda f: (-f.confidence, f.path, f.line))
    shown = ranked if full else ranked[:cap]
    lines += [f"  {f.confidence:>3}%  {f.path}:{f.line}  {f.message}" for f in shown]
    if len(ranked) > len(shown):
        lines.append(f"  ... {len(ranked) - len(shown)} more (--full for all)")
    return "\n".join(lines)


def result_as_json(result: DeadCodeResult) -> str:
    """Render the scan result as the machine-readable report.

    Args:
        result: The scan result.

    Returns:
        The JSON document.
    """
    return json.dumps(
        {
            "outcome": result.outcome.value,
            "headline": result.headline(),
            "modules_offered": result.modules_offered,
            "count_by_confidence": result.count_by_confidence,
            "reason": result.reason,
            "findings": [
                {
                    "path": f.path,
                    "line": f.line,
                    "message": f.message,
                    "confidence": f.confidence,
                }
                for f in result.findings
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the dead-code scan and print the reduced console report.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        :data:`OK` when the scan ran, findings and all, and
        :data:`ADVISORY_BROKEN` when it could not, so missing evidence is
        never read as a clean result.
    """
    parser = argparse.ArgumentParser(
        description="Scan for dead code, reporting the denominator with the verdict.",
    )
    parser.add_argument(
        "--full", action="store_true", help="List every finding, uncapped."
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = run_dead_code_scan()
    print(
        result_as_json(result)
        if args.json
        else render_console_report(result, full=args.full)
    )
    return ADVISORY_BROKEN if result.outcome is DeadCodeOutcome.ERROR else OK


if __name__ == "__main__":
    raise SystemExit(main())
