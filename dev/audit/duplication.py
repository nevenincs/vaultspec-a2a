#!/usr/bin/env python
"""The single duplication runner: invoke jscpd, parse it, classify it honestly.

This module owns the whole duplication measurement - source selection, command
construction, execution, timeout, parsing, and availability classification -
so there is deliberately no second jscpd invocation anywhere in the tree. A
measurement tool that duplicates itself is the defect it exists to detect.

The result has exactly three states, and the distinction between the first and
the third is the point of the module:

* :attr:`DuplicationOutcome.OBSERVED_ZERO` - jscpd ran, demonstrably inspected
  sources (``files_analysed > 0``), and reported no clones.
* :attr:`DuplicationOutcome.CLONES` - jscpd ran and reported clones.
* :attr:`DuplicationOutcome.UNAVAILABLE` - no signal at all: ``npx`` absent
  (the common case on a machine with no Node toolchain), a timeout, a non-zero
  exit, an unreadable report, or a report showing zero sources inspected.

The previous recipe shelled straight out to ``npx --yes jscpd@4`` and let the
harness read its exit code. ``npx`` exits 0 when it cannot find a package to
run, so on any machine without Node the duplication dimension reported exactly
like a clean tree. An unavailable scan is never an observed zero here.

Two limits are deliberate and recorded so neither is rediscovered as a defect:

* **Scope is production Python.** The test tiers are excluded because their
  duplication is fixture shape rather than duplicated authority, and the
  format is pinned to ``python`` because the package ships large JSON
  acceptance fixtures whose repeated payloads swamp every real clone. Pass
  ``--include-tests`` to widen it on demand.
* **jscpd matches token sequences.** A concept implemented twice in different
  syntax is invisible to it. A low percentage means little COPY-PASTE
  survives; it has never meant little duplication survives, and no change to
  this module can make it mean that.

The clone count is advisory debt, not a gate: this module exits 0 on findings
and only :data:`~dev.exit_codes.ADVISORY_BROKEN` when the scan could not run.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from dev.exit_codes import ADVISORY_BROKEN, OK
from dev.paths import PACKAGE, REPO_ROOT, TEST_TIERS, UTF_8
from dev.process import ToolUnavailableError, run_captured

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The pinned detector. A floating version would change the number under a
#: reader who changed nothing.
JSCPD_SPEC: Final[str] = "jscpd@4"

#: The tree scanned by the standing recipe.
SOURCE_ROOT: Final[str] = f"src/{PACKAGE}"

#: jscpd's own defaults (5 lines / 50 tokens) report formatting coincidences.
#: 20 lines at 70 tokens is the threshold at which a clone is a maintenance
#: liability rather than a similarity.
MIN_LINES: Final[str] = "20"
MIN_TOKENS: Final[str] = "70"

#: Glob patterns held out of the production scan.
TEST_IGNORE: Final[str] = ",".join(f"**/{tier}/**" for tier in TEST_TIERS)

#: The report filename jscpd's JSON reporter writes into its output directory.
REPORT_NAME: Final[str] = "jscpd-report.json"

#: How many clone groups the console report names before it says "... more".
CLONE_CAP: Final[int] = 20

#: A duplication scan over this tree takes well under a minute; five is slack.
TIMEOUT_SECONDS: Final[float] = 300.0


class DuplicationOutcome(StrEnum):
    """The three honest states a duplication scan can land in."""

    OBSERVED_ZERO = "observed_zero"
    CLONES = "clones"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True, order=True)
class CloneGroup:
    """One clone: the same token sequence found in two places.

    Args:
        lines: How many lines the clone spans.
        first_path: Repository-relative path of the first occurrence.
        first_start: One-based start line of the first occurrence.
        second_path: Repository-relative path of the second occurrence.
        second_start: One-based start line of the second occurrence.
    """

    lines: int
    first_path: str
    first_start: int
    second_path: str
    second_start: int

    def render(self) -> str:
        """Render the clone as one console line."""
        return (
            f"  {self.lines:>4} lines  {self.first_path}:{self.first_start}"
            f"  <->  {self.second_path}:{self.second_start}"
        )


@dataclass(frozen=True, slots=True)
class DuplicationResult:
    """A duplication scan's typed outcome.

    Construct through :meth:`observed`, or :meth:`unavailable`, so a result
    cannot claim a verdict it has no evidence for.
    """

    outcome: DuplicationOutcome
    files_analysed: int = 0
    duplicated_pct: float = 0.0
    groups: tuple[CloneGroup, ...] = ()
    reason: str = ""

    @classmethod
    def observed(
        cls,
        *,
        files_analysed: int,
        duplicated_pct: float,
        groups: tuple[CloneGroup, ...],
    ) -> DuplicationResult:
        """Build the outcome of a scan that demonstrably inspected sources.

        Args:
            files_analysed: How many source files jscpd reported inspecting.
            duplicated_pct: The duplicated-line percentage it reported.
            groups: Every clone it reported.

        Returns:
            A ``CLONES`` result when clones were found, ``OBSERVED_ZERO``
            otherwise.

        Raises:
            ValueError: When no file was inspected. A scan that read nothing
                has observed nothing, and calling that zero is the false green
                this class exists to prevent.
        """
        if files_analysed <= 0:
            msg = "observed requires a scan that demonstrably inspected sources"
            raise ValueError(msg)
        found = DuplicationOutcome.CLONES
        return cls(
            outcome=found if groups else DuplicationOutcome.OBSERVED_ZERO,
            files_analysed=files_analysed,
            duplicated_pct=duplicated_pct,
            groups=tuple(sorted(groups, reverse=True)),
        )

    @classmethod
    def unavailable(cls, reason: str) -> DuplicationResult:
        """Build the outcome of a scan that produced no signal.

        Args:
            reason: What went wrong, in one clause.

        Returns:
            The unavailable result.
        """
        return cls(outcome=DuplicationOutcome.UNAVAILABLE, reason=reason)

    @property
    def clone_count(self) -> int:
        """How many clones were reported."""
        return len(self.groups)

    def headline(self) -> str:
        """Render the one-line human summary of the outcome."""
        if self.outcome is DuplicationOutcome.UNAVAILABLE:
            return f"signal unavailable this cycle: {self.reason}"
        return (
            f"{self.clone_count} clone(s) across {self.files_analysed} source file(s) "
            f"({self.duplicated_pct:g}% of lines duplicated)"
        )


def jscpd_command(output_dir: Path, *, include_tests: bool = False) -> list[str]:
    """Build the one jscpd command line.

    Args:
        output_dir: Where the JSON reporter writes its report.
        include_tests: Scan the test tiers as well as production code.

    Returns:
        The argument vector.

    The JSON reporter is used rather than the console one on purpose: the
    console output is a box-drawing table whose column layout is a rendering
    decision, and parsing it makes the measurement hostage to a cosmetic
    release note.
    """
    argv = [
        "npx",
        "--yes",
        JSCPD_SPEC,
        SOURCE_ROOT,
        "--min-lines",
        MIN_LINES,
        "--min-tokens",
        MIN_TOKENS,
        "--format",
        "python",
        "--reporters",
        "json",
        "--output",
        str(output_dir),
        "--silent",
    ]
    if not include_tests:
        argv += ["--ignore", TEST_IGNORE]
    return argv


def _relative(path: str) -> str:
    """Render a jscpd-reported absolute path relative to the repository."""
    forward = path.replace("\\", "/")
    prefix = REPO_ROOT.as_posix() + "/"
    return forward.removeprefix(prefix)


def parse_report(payload: Any) -> DuplicationResult:
    """Turn jscpd's JSON report into the typed result.

    Args:
        payload: The decoded report document.

    Returns:
        The typed result, ``UNAVAILABLE`` when the report shows no source was
        inspected.
    """
    total = payload.get("statistics", {}).get("total", {})
    sources = int(total.get("sources", 0))
    if sources <= 0:
        return DuplicationResult.unavailable(
            "jscpd reported 0 source files inspected, so its 0 clones prove nothing",
        )

    groups: list[CloneGroup] = []
    for row in payload.get("duplicates", []):
        first, second = row.get("firstFile", {}), row.get("secondFile", {})
        groups.append(
            CloneGroup(
                lines=int(row.get("lines", 0)),
                first_path=_relative(str(first.get("name", "?"))),
                first_start=int(first.get("start", 0)),
                second_path=_relative(str(second.get("name", "?"))),
                second_start=int(second.get("start", 0)),
            ),
        )
    return DuplicationResult.observed(
        files_analysed=sources,
        duplicated_pct=float(total.get("percentage", 0.0)),
        groups=tuple(groups),
    )


def run_duplication_scan(
    repo_root: Path = REPO_ROOT,
    *,
    include_tests: bool = False,
    timeout: float = TIMEOUT_SECONDS,
) -> DuplicationResult:
    """Run jscpd over the production tree and classify the outcome.

    Args:
        repo_root: The tree to scan.
        include_tests: Scan the test tiers as well as production code.
        timeout: Seconds to wait before giving up on jscpd.

    Returns:
        The typed result. This is the single entry point for every duplication
        consumer.
    """
    with tempfile.TemporaryDirectory(prefix="jscpd-") as tmp:
        output_dir = Path(tmp)
        try:
            completed = run_captured(
                jscpd_command(output_dir, include_tests=include_tests),
                cwd=repo_root,
                timeout=timeout,
            )
        except ToolUnavailableError as exc:
            return DuplicationResult.unavailable(str(exc))

        report_path = output_dir / REPORT_NAME
        if not report_path.is_file():
            # npx exits 0 when it cannot resolve a package to run, so the
            # missing report - not the status - is what says the scan
            # did not happen.
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else "no diagnostic output"
            return DuplicationResult.unavailable(
                f"jscpd wrote no report (exit {completed.returncode}): {tail}",
            )

        try:
            payload = json.loads(report_path.read_text(encoding=UTF_8))
        except (OSError, json.JSONDecodeError) as exc:
            return DuplicationResult.unavailable(f"jscpd report was unreadable: {exc}")

    return parse_report(payload)


def render_console_report(
    result: DuplicationResult,
    *,
    full: bool = False,
    cap: int = CLONE_CAP,
) -> str:
    """Render the operator-facing console report.

    Args:
        result: The scan result.
        full: List every clone rather than the largest ``cap``.
        cap: How many clones to list when ``full`` is not set.

    Returns:
        The report text.
    """
    lines = [f"duplication: {result.headline()}"]
    if result.outcome is not DuplicationOutcome.CLONES:
        return lines[0]

    shown = result.groups if full else result.groups[:cap]
    lines += [group.render() for group in shown]
    if len(result.groups) > len(shown):
        lines.append(f"  ... {len(result.groups) - len(shown)} more (--full for all)")
    return "\n".join(lines)


def result_as_json(result: DuplicationResult) -> str:
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
            "files_analysed": result.files_analysed,
            "duplicated_pct": result.duplicated_pct,
            "clone_count": result.clone_count,
            "reason": result.reason,
            "clones": [
                {
                    "lines": g.lines,
                    "first": {"path": g.first_path, "line": g.first_start},
                    "second": {"path": g.second_path, "line": g.second_start},
                }
                for g in result.groups
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the duplication scan and print the reduced console report.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        :data:`OK` when the scan ran, clones and all, and
        :data:`ADVISORY_BROKEN` when it could not.
    """
    parser = argparse.ArgumentParser(
        description="Detect copy-paste clones, reporting how much was read.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="List every clone, uncapped.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Scan the test tiers as well as production code.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = run_duplication_scan(include_tests=args.include_tests)
    report = (
        result_as_json(result)
        if args.json
        else render_console_report(result, full=args.full)
    )
    print(report)
    return ADVISORY_BROKEN if result.outcome is DuplicationOutcome.UNAVAILABLE else OK


if __name__ == "__main__":
    raise SystemExit(main())
