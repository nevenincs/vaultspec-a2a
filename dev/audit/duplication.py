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

The previous recipe shelled straight out to ``npx --yes jscpd@4``, a floating
major version fetched ad hoc on every run, and let the harness read its exit
code. ``npx`` exits 0 when it cannot find a package to run, so on any machine
without Node the duplication dimension reported exactly like a clean tree. An
unavailable scan is never an observed zero here.

The detector is now pinned as an exact ``package.json`` devDependency
(:data:`JSCPD_VERSION`) and invoked as ``npx jscpd`` with no version spec, so
the call resolves the locally installed binary rather than fetching whatever
the spec allows that day. jscpd 5 is a full rewrite (Rust, not the old Node
implementation); its JSON report schema stayed compatible, but its path
reporting did not - run bare it reports a path relative to whichever scanned
root happens to contain it, which is ambiguous across more than one root, so
every invocation passes ``--absolute`` and :func:`_relative` strips both the
Windows extended-length prefix (``\\\\?\\``) and the repository root.

Two scans share this module, by design - "no second jscpd invocation
anywhere in the tree" means every caller, not just the first one written:

* :func:`run_duplication_scan` - the advisory measurement. **Scope is
  production Python.** The test tiers are excluded because their duplication
  is fixture shape rather than duplicated authority, and the format is pinned
  to ``python`` because the package ships large JSON acceptance fixtures
  whose repeated payloads swamp every real clone. Pass ``--include-tests`` to
  widen it on demand. This scan is advisory debt, not a gate: it exits 0 on
  findings and only :data:`~dev.exit_codes.ADVISORY_BROKEN` when it could not
  run.
* :func:`run_blocking_duplication_scan` - the blocking gate (Q.2). Scans
  every tier, plus :data:`TOOLING_ROOT` (``dev/``), and blocks on any clone
  that :data:`BASELINE_PATH` does not adjudicate. A clone the baseline no
  longer matches - because the surrounding code moved, not because the clone
  was fixed - fails the same way a genuinely new one does, so the baseline
  cannot silently drift from what it claims to describe.

One limit holds for both: **jscpd matches token sequences.** A concept
implemented twice in different syntax is invisible to it. A low percentage
means little COPY-PASTE survives; it has never meant little duplication
survives, and no change to this module can make it mean that. The sibling
AST structural-duplication guard (``tests/test_structural_duplication.py``)
is the complementary check that catches a clone renamed past jscpd's reach.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from dev.exit_codes import ADVISORY_BROKEN, FAILED, OK, TOOL_BROKEN
from dev.paths import PACKAGE, REPO_ROOT, TEST_TIERS, UTF_8
from dev.process import ToolUnavailableError, run_captured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: The pinned detector version. Kept in sync with the exact devDependency in
#: ``package.json``/``package-lock.json`` by
#: ``test_the_pinned_version_matches_package_json`` - a floating version
#: would change the number under a reader who changed nothing.
JSCPD_VERSION: Final[str] = "5.4.0"

#: The tree scanned by the standing advisory recipe.
SOURCE_ROOT: Final[str] = f"src/{PACKAGE}"

#: The repository's own tooling, additionally scanned by the blocking gate.
TOOLING_ROOT: Final[str] = "dev"

#: The blocking gate's adjudicated baseline. Every clone it does not name -
#: new or, just as much, one the current scan can no longer find at the
#: recorded location - fails the gate; see :func:`load_baseline`.
BASELINE_PATH: Final[Path] = REPO_ROOT / "dev" / "audit" / "duplication-baseline.json"

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


def jscpd_command(
    output_dir: Path,
    *,
    roots: Sequence[str] = (SOURCE_ROOT,),
    include_tests: bool = False,
) -> list[str]:
    """Build the one jscpd command line.

    Args:
        output_dir: Where the JSON reporter writes its report.
        roots: The paths jscpd scans, relative to the repository root.
        include_tests: Scan the test tiers as well as production code.

    Returns:
        The argument vector.

    The JSON reporter is used rather than the console one on purpose: the
    console output is a box-drawing table whose column layout is a rendering
    decision, and parsing it makes the measurement hostage to a cosmetic
    release note. ``npx jscpd`` carries no version spec and no ``--yes``: the
    pinned ``package.json`` devDependency is what npx resolves, so a missing
    install fails loudly instead of silently fetching one. ``--absolute`` is
    unconditional because jscpd 5 reports a bare path relative to whichever
    scanned root contains it, which more than one root makes ambiguous.
    """
    argv = [
        "npx",
        "jscpd",
        *roots,
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
        "--no-tips",
        "--absolute",
    ]
    if not include_tests:
        argv += ["--ignore", TEST_IGNORE]
    return argv


def _relative(path: str) -> str:
    """Render a jscpd-reported absolute path relative to the repository.

    ``--absolute`` on Windows renders through the extended-length prefix
    (``\\\\?\\Y:\\...``), which :meth:`Path.as_posix`-style comparison never
    produces, so it is stripped before the repository-root prefix is.
    """
    forward = path.replace("\\", "/").removeprefix("//?/")
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
    roots: Sequence[str] = (SOURCE_ROOT,),
    include_tests: bool = False,
    timeout: float = TIMEOUT_SECONDS,
) -> DuplicationResult:
    """Run jscpd over the given tree(s) and classify the outcome.

    Args:
        repo_root: The checkout jscpd runs from; *roots* are relative to it.
        roots: The paths jscpd scans. Defaults to the shipped package alone.
        include_tests: Scan the test tiers as well as production code.
        timeout: Seconds to wait before giving up on jscpd.

    Returns:
        The typed result. This is the single entry point for every duplication
        consumer.
    """
    # The report is scratch inside the scanned checkout's ignored .tmp-* space,
    # never the system temporary directory.
    scratch = repo_root / ".tmp-duplication"
    scratch.mkdir(exist_ok=True)
    try:
        return _scan(
            repo_root,
            scratch,
            roots=roots,
            include_tests=include_tests,
            timeout=timeout,
        )
    finally:
        # Only an empty root is removed: a concurrent scan may still own a child.
        with contextlib.suppress(OSError):
            scratch.rmdir()


def _scan(
    repo_root: Path,
    scratch: Path,
    *,
    roots: Sequence[str],
    include_tests: bool,
    timeout: float,
) -> DuplicationResult:
    with tempfile.TemporaryDirectory(prefix="jscpd-", dir=scratch) as tmp:
        output_dir = Path(tmp)
        try:
            completed = run_captured(
                jscpd_command(output_dir, roots=roots, include_tests=include_tests),
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


@dataclass(frozen=True, slots=True)
class BaselineEntry:
    """One adjudicated clone the blocking gate must not re-report as new.

    Args:
        category: A key into the baseline's ``categories`` reasons.
        lines: How many lines the clone spans, as last adjudicated.
        first_path: Repository-relative path of the first occurrence.
        first_start: One-based start line of the first occurrence.
        second_path: Repository-relative path of the second occurrence.
        second_start: One-based start line of the second occurrence.
        note: An optional entry-specific detail beyond the category reason.
    """

    category: str
    lines: int
    first_path: str
    first_start: int
    second_path: str
    second_start: int
    note: str = ""

    def key(self) -> _CloneKey:
        """The identity :func:`_clone_key` must reproduce for this to match."""
        return (
            frozenset(
                {
                    (self.first_path, self.first_start),
                    (self.second_path, self.second_start),
                }
            ),
            self.lines,
        )


@dataclass(frozen=True, slots=True)
class Baseline:
    """The blocking gate's adjudicated exceptions, grouped by reason."""

    categories: Mapping[str, str]
    entries: tuple[BaselineEntry, ...]


#: A clone's identity for baseline matching: the two occurrences as an
#: UNORDERED pair, plus the span. Unordered because jscpd's own ordering of
#: "first" versus "second" is not a guarantee this module can lean on across
#: runs or versions, and a swap must still match the same baseline entry.
_CloneKey = tuple[frozenset[tuple[str, int]], int]


def _clone_key(group: CloneGroup) -> _CloneKey:
    """The same identity :meth:`BaselineEntry.key` computes, from a live clone."""
    return (
        frozenset(
            {
                (group.first_path, group.first_start),
                (group.second_path, group.second_start),
            }
        ),
        group.lines,
    )


def load_baseline(path: Path = BASELINE_PATH) -> Baseline:
    """Load and validate the blocking gate's adjudicated baseline.

    Args:
        path: Where the baseline file lives.

    Returns:
        The typed baseline.

    Raises:
        ValueError: The file is malformed: a category with no reason, or an
            entry naming a category the file does not declare. A baseline
            entry with no explanation is exactly the silent debt this gate
            exists to keep visible, so a malformed one is refused rather than
            silently loaded as empty.
    """
    payload = cast("dict[str, Any]", json.loads(path.read_text(encoding=UTF_8)))
    raw_categories = payload.get("categories", {})
    if not isinstance(raw_categories, dict):
        msg = f"{path}: every category needs a non-empty string reason"
        raise ValueError(msg)
    # Cast rather than rely on the isinstance narrowing above: pyright narrows
    # an Any-typed JSON value checked against the bare `dict` class to
    # `dict[Unknown, Unknown]`, which would propagate into every value read
    # from it, including the ones about to be validated as `str` below.
    # A JSON object's keys are always `str`; only the reason needs checking.
    categories = cast("dict[str, Any]", raw_categories)
    if not all(
        isinstance(reason, str) and reason.strip() for reason in categories.values()
    ):
        msg = f"{path}: every category needs a non-empty string reason"
        raise ValueError(msg)

    entries: list[BaselineEntry] = []
    for item in payload.get("accepted", []):
        raw = cast("dict[str, Any]", item)
        category = raw["category"]
        if category not in categories:
            msg = f"{path}: entry names undeclared category {category!r}"
            raise ValueError(msg)
        entries.append(
            BaselineEntry(
                category=category,
                lines=int(raw["lines"]),
                first_path=str(raw["first"]["path"]),
                first_start=int(raw["first"]["start"]),
                second_path=str(raw["second"]["path"]),
                second_start=int(raw["second"]["start"]),
                note=str(raw.get("note", "")),
            )
        )
    return Baseline(categories=categories, entries=tuple(entries))


@dataclass(frozen=True, slots=True)
class BlockingDuplicationResult:
    """The blocking gate's typed outcome (Q.2)."""

    outcome: DuplicationOutcome
    baseline_size: int = 0
    new_clones: tuple[CloneGroup, ...] = ()
    stale_entries: tuple[BaselineEntry, ...] = ()
    reason: str = ""

    @property
    def ok(self) -> bool:
        """Whether the gate passes: a real scan, nothing new, nothing stale."""
        return (
            self.outcome is not DuplicationOutcome.UNAVAILABLE
            and not self.new_clones
            and not self.stale_entries
        )

    def headline(self) -> str:
        """Render the one-line human summary of the outcome."""
        if self.outcome is DuplicationOutcome.UNAVAILABLE:
            return f"signal unavailable this cycle: {self.reason}"
        return (
            f"baseline holds {self.baseline_size} adjudicated clone(s); "
            f"{len(self.new_clones)} new, {len(self.stale_entries)} stale"
        )


def diff_against_baseline(
    groups: Sequence[CloneGroup], baseline: Baseline
) -> tuple[tuple[CloneGroup, ...], tuple[BaselineEntry, ...]]:
    """Split *groups* into the ones the baseline misses and the entries it wastes.

    Pure and jscpd-free on purpose: this is the whole adjudication judgement,
    separated from running the scan so it can be proven directly against
    constructed data.

    Args:
        groups: The clones a scan reported.
        baseline: The adjudicated baseline to check them against.

    Returns:
        A ``(new_clones, stale_entries)`` pair. ``new_clones`` is every group
        with no matching baseline entry. ``stale_entries`` is every baseline
        entry that matched no group - the code it described has moved or been
        fixed, so it no longer describes anything real.
    """
    by_key = {entry.key(): entry for entry in baseline.entries}
    matched: set[_CloneKey] = set()
    new_clones: list[CloneGroup] = []
    for group in groups:
        key = _clone_key(group)
        if key in by_key:
            matched.add(key)
        else:
            new_clones.append(group)
    stale = tuple(entry for key, entry in by_key.items() if key not in matched)
    return tuple(new_clones), stale


def run_blocking_duplication_scan(
    repo_root: Path = REPO_ROOT,
    *,
    baseline_path: Path = BASELINE_PATH,
    timeout: float = TIMEOUT_SECONDS,
) -> BlockingDuplicationResult:
    """Scan every tier plus :data:`TOOLING_ROOT`, blocking on what the baseline misses.

    Args:
        repo_root: The checkout to scan.
        baseline_path: Where the adjudicated baseline lives.
        timeout: Seconds to wait before giving up on jscpd.

    Returns:
        The typed blocking result. :attr:`BlockingDuplicationResult.ok` is the
        gate's whole verdict: a real scan that reported no clone the baseline
        does not name, and matched every entry the baseline declares. A
        baseline entry matching no current clone is reported exactly like a
        new one - the code that clone described has moved, so the baseline no
        longer describes anything real until a human looks again.
    """
    result = run_duplication_scan(
        repo_root,
        roots=(SOURCE_ROOT, TOOLING_ROOT),
        include_tests=True,
        timeout=timeout,
    )
    if result.outcome is DuplicationOutcome.UNAVAILABLE:
        return BlockingDuplicationResult(outcome=result.outcome, reason=result.reason)

    baseline = load_baseline(baseline_path)
    new_clones, stale = diff_against_baseline(result.groups, baseline)
    return BlockingDuplicationResult(
        outcome=result.outcome,
        baseline_size=len(baseline.entries),
        new_clones=new_clones,
        stale_entries=stale,
    )


def render_blocking_report(result: BlockingDuplicationResult) -> str:
    """Render the blocking gate's operator-facing console report."""
    lines = [f"duplication (blocking): {result.headline()}"]
    for group in result.new_clones:
        lines.append("  NEW    " + group.render().strip())
    for entry in result.stale_entries:
        lines.append(
            f"  STALE  [{entry.category}] {entry.first_path}:{entry.first_start}"
            f"  <->  {entry.second_path}:{entry.second_start}"
            " - baseline entry matches no current clone"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the duplication scan and print the reduced console report.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        For the advisory scan (default): :data:`OK` when the scan ran, clones
        and all, and :data:`ADVISORY_BROKEN` when it could not. For
        ``--blocking``: :data:`OK` when the baseline accounts for every
        clone, :data:`FAILED` on a new or stale entry, and :data:`TOOL_BROKEN`
        when the scan itself could not run.
    """
    parser = argparse.ArgumentParser(
        description="Detect copy-paste clones, reporting how much was read.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="List every clone, uncapped. Ignored with --blocking.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Scan the test tiers as well as production code. Ignored with "
        "--blocking, which always does.",
    )
    parser.add_argument(
        "--blocking",
        action="store_true",
        help="Run the Q.2 blocking gate instead: every tier plus dev/, "
        "against the adjudicated baseline.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.blocking:
        blocking = run_blocking_duplication_scan()
        print(render_blocking_report(blocking))
        if blocking.outcome is DuplicationOutcome.UNAVAILABLE:
            return TOOL_BROKEN
        return OK if blocking.ok else FAILED

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
