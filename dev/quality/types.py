#!/usr/bin/env python
"""Signal-only type-check harness wrapping ty and basedpyright.

Two checkers run behind one verdict: ``ty`` across every Python tree the
repository lints, and ``basedpyright`` in strict mode across the subset its
``[tool.basedpyright]`` configuration declares. Their raw output is a flat
several-hundred-line dump apiece, in two different shapes, which is why this
module exists between them and the reader:

* On success: silent, exit 0. Green is not reported.
* On failure: a compact summary grouped by rule and by file - never the raw
  dump - plus a pointer to the full-detail command. Exit 1.
* With ``--count``: only the aggregate finding count, exit 0. The integer is
  then the sole machine signal, which is what the health census consumes.
* With ``--full``: every diagnostic verbatim, one actionable line each, exit 0.

Both checkers are read through their JSON output rather than their human
output, so the summary cannot drift when either tool reformats its console
rendering.

The load-bearing rule is :func:`require_report`. A clean run is NOT silent -
``ty`` prints an empty JSON array and basedpyright an object with an empty
diagnostic list - so an empty stream means the checker never produced a report
at all. Read as zero diagnostics, a crashed or un-startable checker reports
green over a run that never happened. Every collector here refuses it.

``--platforms`` re-runs ``ty`` once per target platform. ``ty`` resolves
``sys.platform`` against the machine it runs on, so an unguarded
platform-specific call passes for everyone on that platform and fails only on
the others' runners; sweeping all three makes the answer the same everywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from dev.exit_codes import FAILED, OK, TOOL_BROKEN
from dev.paths import repo_relative
from dev.process import ToolUnavailableError, run_tool

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Iterable, Sequence

#: Python trees `ty` is pointed at. Kept identical to ``dev.toolchain``'s
#: PYTHON_PATHS; the two are asserted equal by this module's guard test rather
#: than imported, because ``dev.toolchain`` imports the runner and this module
#: must stay importable from a bare interpreter.
PYTHON_PATHS: Final[tuple[str, ...]] = ("src", "dev", "docs", "scripts", "packaging")

#: Platforms swept by ``--platforms``.
PLATFORMS: Final[tuple[str, ...]] = ("linux", "darwin", "win32")

#: How many rules and files the grouped summary names before it says "... more".
TOP_RULES: Final[int] = 12
TOP_FILES: Final[int] = 12

#: Ceiling on one checker's runtime. A type checker that has not answered in
#: five minutes has hung, and a hung gate is a broken gate.
TIMEOUT_SECONDS: Final[float] = 300.0


@dataclass(frozen=True, slots=True, order=True)
class Diagnostic:
    """One normalised type-checker finding.

    Args:
        checker: The checker that reported it, including any platform tag.
        rule: The checker's own rule name, verbatim.
        path: Repository-relative, forward-slash path.
        line: One-based line number.
        message: The first line of the checker's message.
    """

    checker: str
    path: str
    line: int
    rule: str
    message: str


class CheckerUnavailableError(RuntimeError):
    """A checker did not produce a report, so its silence proves nothing."""


def require_report(
    payload: str,
    result: subprocess.CompletedProcess[str],
    checker: str,
) -> None:
    """Refuse an empty checker stream instead of reading it as zero diagnostics.

    Args:
        payload: The checker's stripped stdout.
        result: The completed process, whose stderr carries the diagnosis.
        checker: The checker's name, for the error message.

    Raises:
        CheckerUnavailableError: When the stream is empty. Every checker here
            prints a report even when it finds nothing, so an empty stream
            means no report was produced - not that there was nothing to
            report.
    """
    if payload:
        return
    detail = (result.stderr or "").strip().splitlines()
    tail = detail[-1] if detail else "no diagnostic output"
    msg = f"{checker} produced no report (exit {result.returncode}): {tail}"
    raise CheckerUnavailableError(msg)


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a checker in the locked tooling profile, capturing both streams.

    Args:
        argv: The checker command and its arguments.

    Returns:
        The completed process. A non-zero status is expected - it is how a
        checker reports findings - so nothing is raised on it.

    Raises:
        CheckerUnavailableError: When the checker could not be launched or did
            not finish inside :data:`TIMEOUT_SECONDS`.
    """
    try:
        return run_tool(argv, timeout=TIMEOUT_SECONDS)
    except ToolUnavailableError as exc:
        raise CheckerUnavailableError(str(exc)) from exc


def _parse_json(
    payload: str,
    result: subprocess.CompletedProcess[str],
    checker: str,
) -> Any:
    """Parse a checker's JSON report, surfacing the raw stream when it is not JSON.

    Args:
        payload: The checker's stripped stdout.
        result: The completed process, whose stderr is echoed on failure.
        checker: The checker's name, for the error message.

    Returns:
        The decoded payload.

    Raises:
        CheckerUnavailableError: When the stream is not JSON, which means the
            checker printed something other than the report it was asked for.
    """
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        sys.stderr.write(payload[:2000])
        sys.stderr.write(result.stderr)
        msg = f"{checker} emitted an unparseable report: {exc}"
        raise CheckerUnavailableError(msg) from exc


def _norm(path: str) -> str:
    """Normalise a checker-reported path to the repository-relative POSIX form."""
    return repo_relative(Path(path.replace("\\", "/")))


def collect_ty(platform: str | None = None) -> list[Diagnostic]:
    """Run ``ty`` and parse its GitLab-JSON diagnostics.

    Args:
        platform: A ``--python-platform`` value to check against, or ``None``
            for the host platform.

    Returns:
        Every diagnostic, tagged with the platform when one was named.
    """
    argv = ["ty", "check", "--output-format", "gitlab", "--color", "never"]
    if platform is not None:
        argv += ["--python-platform", platform]
    argv += list(PYTHON_PATHS)

    checker = "ty" if platform is None else f"ty[{platform}]"
    result = _run(argv)
    payload = result.stdout.strip()
    require_report(payload, result, checker)
    rows = _parse_json(payload, result, checker)

    diagnostics: list[Diagnostic] = []
    for row in rows:
        location = row.get("location", {})
        begin = location.get("positions", {}).get("begin", {})
        diagnostics.append(
            Diagnostic(
                checker=checker,
                path=_norm(str(location.get("path", "?"))),
                line=int(begin.get("line", 0)),
                rule=str(row.get("check_name", "unknown")),
                message=str(row.get("description", "")).splitlines()[0],
            ),
        )
    return diagnostics


def collect_basedpyright() -> list[Diagnostic]:
    """Run ``basedpyright`` in its declared strict configuration and parse the JSON.

    ``--project`` names ``pyproject.toml`` explicitly so a stray
    ``pyrightconfig.json`` appearing beside it cannot win discovery and quietly
    widen or relax the checked surface. ``--pythonpath`` names the running
    interpreter, because basedpyright otherwise auto-detects a ``.venv`` beside
    the working directory and reports a phantom ``reportMissingImports``
    cascade whenever it runs against a tree that has none.

    Returns:
        Every error-severity diagnostic. Warnings and hints are excluded: the
        strict configuration promotes what this repository gates on to error.
    """
    result = _run(
        [
            "basedpyright",
            "--project",
            "pyproject.toml",
            "--pythonpath",
            sys.executable,
            "--outputjson",
        ],
    )
    payload = result.stdout.strip()
    require_report(payload, result, "basedpyright")
    report = _parse_json(payload, result, "basedpyright")

    diagnostics: list[Diagnostic] = []
    for row in report.get("generalDiagnostics", []):
        if row.get("severity") != "error":
            continue
        start = row.get("range", {}).get("start", {})
        diagnostics.append(
            Diagnostic(
                checker="basedpyright",
                path=_norm(str(row.get("file") or "?")),
                # basedpyright reports zero-based lines; every other surface
                # in this repository - editors, ty, ruff - is one-based.
                line=int(start.get("line", -1)) + 1,
                rule=str(row.get("rule") or "error"),
                message=str(row.get("message") or "").splitlines()[0],
            ),
        )
    return diagnostics


def collect(*, platforms: bool = False, strict: bool = True) -> list[Diagnostic]:
    """Collect every checker's diagnostics.

    Args:
        platforms: Sweep ``ty`` across every target platform instead of
            checking only the host's.
        strict: Include the basedpyright strict pass.

    Returns:
        Every diagnostic, sorted into a stable order so two runs over an
        unchanged tree produce byte-identical output.
    """
    diagnostics: list[Diagnostic] = []
    if platforms:
        for platform in PLATFORMS:
            diagnostics += collect_ty(platform)
    else:
        diagnostics += collect_ty()
    if strict:
        diagnostics += collect_basedpyright()
    return sorted(diagnostics)


def _group(diagnostics: Iterable[Diagnostic], checker: str) -> list[str]:
    """Render one checker's rule and file breakdown.

    Args:
        diagnostics: Every diagnostic across every checker.
        checker: The checker whose subset to render.

    Returns:
        The report lines, or an empty list when this checker found nothing.
    """
    subset = [d for d in diagnostics if d.checker == checker]
    if not subset:
        return []

    lines = [f"\n{checker} ({len(subset)} diagnostics)"]
    for label, counter in (
        ("by rule", Counter(d.rule for d in subset)),
        ("worst files", Counter(d.path for d in subset)),
    ):
        top = TOP_RULES if label == "by rule" else TOP_FILES
        lines.append(f"  {label}:")
        # `most_common` ties arbitrarily; sorting by (-count, key) makes the
        # ordering a function of the findings rather than of dict insertion.
        ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        lines += [f"    {count:>6}  {key}" for key, count in ranked[:top]]
        if len(ranked) > top:
            lines.append(f"    {'':>6}  ... {len(ranked) - top} more")
    return lines


def render_summary(diagnostics: Sequence[Diagnostic]) -> str:
    """Render the grouped failure summary.

    Args:
        diagnostics: Every diagnostic collected.

    Returns:
        The full console report.
    """
    checkers = sorted({d.checker for d in diagnostics})
    breakdown = ", ".join(
        f"{sum(1 for d in diagnostics if d.checker == c)} {c}" for c in checkers
    )
    lines = [f"check-types: {len(diagnostics)} diagnostics ({breakdown})"]
    for checker in checkers:
        lines += _group(diagnostics, checker)
    lines.append("\nFull detail: just audit-types")
    return "\n".join(lines)


def render_full(diagnostics: Sequence[Diagnostic]) -> str:
    """Render every diagnostic as one actionable line each.

    Args:
        diagnostics: Every diagnostic collected.

    Returns:
        One ``path:line: checker[rule] message`` line per finding.
    """
    return "\n".join(
        f"{d.path}:{d.line}: {d.checker}[{d.rule}] {d.message}" for d in diagnostics
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the type checkers and emit signal-only output.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        :data:`OK` when clean or when measuring, :data:`FAILED` on findings,
        and :data:`TOOL_BROKEN` when a checker did not produce a report.
    """
    parser = argparse.ArgumentParser(
        description="Signal-only ty + basedpyright harness.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--full",
        action="store_true",
        help="Print every diagnostic verbatim; exit 0.",
    )
    mode.add_argument(
        "--count",
        action="store_true",
        help="Print only the aggregate count; exit 0.",
    )
    parser.add_argument(
        "--platforms",
        action="store_true",
        help="Sweep ty across every target platform instead of the host's.",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Skip the basedpyright strict pass.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        diagnostics = collect(platforms=args.platforms, strict=not args.no_strict)
    except CheckerUnavailableError as exc:
        print(
            f"check-types: measurement unavailable, type correctness unproven: {exc}",
            file=sys.stderr,
        )
        return TOOL_BROKEN

    if args.count:
        print(len(diagnostics))
        return OK

    if args.full:
        print(render_full(diagnostics) if diagnostics else "no type diagnostics.")
        if diagnostics:
            print(f"\n{len(diagnostics)} type diagnostics (advisory).")
        return OK

    if not diagnostics:
        return OK

    print(render_summary(diagnostics))
    return FAILED


if __name__ == "__main__":
    raise SystemExit(main())
