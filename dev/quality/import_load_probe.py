"""Prove every shipped production module actually imports.

Static analysis can prove that a module is REFERENCED. It cannot prove the
module loads: a stale import of a dependency that removed a symbol, a
module-level constant that raises, a circular import between two packages that
only bites in one direction - none of those are visible to a parser, and each
one is an ``ImportError`` for whoever happens to reach that module first.

The repository already had a case of exactly this shape: ``mcp`` 2.0 removed
``mcp.server.fastmcp`` while the server still imported it, and the break was
found by the type checker rather than by anything asking "does this load?".

So this gate asks directly. It hands every governed module to an isolated
child process, which imports each one and reports every outcome on its own
flushed line. Two properties follow from that shape:

* A module that RAISES is reported with its exception, and the run continues,
  so one break does not hide the twelve behind it.
* A module that KILLS the interpreter - a segfault, an ``os._exit`` at import
  time - is still attributed, because the child announces each module before
  attempting it. A probe that could not name the module it died in would send
  a reader looking through 300 candidates.

The test tiers are out of scope: pytest collection already imports them, and
importing a test module outside a pytest session fails for reasons that say
nothing about the shipped tree. Alembic's migration environment is out of
scope for the same kind of reason - ``env.py`` reads ``alembic.context``,
which only exists inside a migration run, so importing it standalone proves
nothing and fails every time.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dev.exit_codes import FAILED, OK, TOOL_BROKEN
from dev.paths import PACKAGE_ROOT, REPO_ROOT, is_test_path
from dev.process import ToolUnavailableError, run_tool
from dev.quality.import_load_worker import SEPARATOR
from dev.quality.source_import_analysis import (
    alembic_script_location,
    iter_python_files,
    module_name_for,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: Importing three hundred modules pulls in the whole dependency tree; two
#: minutes is generous and a probe that has not answered by then has hung.
TIMEOUT_SECONDS: Final[float] = 600.0

#: The floor below which a clean probe proves nothing. The production tree
#: offered 302 modules when this was set.
MINIMUM_GOVERNED_MODULES: Final[int] = 150


@dataclass(frozen=True, slots=True, order=True)
class LoadFailure:
    """One module that did not import.

    Args:
        module: The dotted module name.
        detail: The exception summary, or why it could not be attributed.
    """

    module: str
    detail: str


@dataclass(frozen=True, slots=True)
class LoadProbeResult:
    """The probe's typed outcome.

    Args:
        attempted: How many modules the child was asked to import.
        loaded: How many imported cleanly.
        failures: Every module that did not.
        reason: Why the probe could not run, when it could not.
    """

    attempted: int = 0
    loaded: int = 0
    failures: tuple[LoadFailure, ...] = ()
    reason: str = ""

    @property
    def is_available(self) -> bool:
        """Whether the probe produced a measurement at all."""
        return not self.reason

    @property
    def is_clean(self) -> bool:
        """Whether every governed module imported."""
        return self.is_available and not self.failures

    def headline(self) -> str:
        """Render the one-line human summary of the outcome."""
        if not self.is_available:
            return f"signal unavailable this cycle: {self.reason}"
        if self.is_clean:
            return f"all {self.loaded} governed module(s) import cleanly"
        return (
            f"{len(self.failures)} of {self.attempted} governed module(s) "
            "failed to import"
        )

    def report(self) -> str:
        """Render the operator-facing console report."""
        lines = [f"import loadability: {self.headline()}"]
        lines += [f"  + {f.module}: {f.detail}" for f in self.failures]
        return "\n".join(lines)


def governed_modules(
    package_root: Path = PACKAGE_ROOT,
    repo_root: Path = REPO_ROOT,
) -> tuple[str, ...]:
    """Return every production module the probe is responsible for.

    Args:
        package_root: The shipped package's directory.
        repo_root: The repository root, used to resolve the migration tree.

    Returns:
        Each module's dotted name, in stable order, with the test tiers and
        the Alembic migration tree held out.
    """
    migrations = alembic_script_location(repo_root)
    names: list[str] = []
    for path in iter_python_files(package_root):
        if is_test_path(path):
            continue
        if migrations is not None and migrations in path.resolve().parents:
            continue
        names.append(module_name_for(path, repo_root / "src"))
    return tuple(sorted(set(names)))


def parse_worker_output(
    stdout: str,
    attempted: Sequence[str],
) -> tuple[int, tuple[LoadFailure, ...]]:
    """Read the child's result lines.

    Args:
        stdout: The child's captured standard output.
        attempted: The modules it was asked to import.

    Returns:
        ``(loaded, failures)``. A module the child announced but never
        resolved is reported as a failure that killed the interpreter, which
        is the case a plain exit-code check cannot see at all.
    """
    loaded: set[str] = set()
    failures: list[LoadFailure] = []
    started: list[str] = []
    for line in stdout.splitlines():
        status, _, rest = line.partition(SEPARATOR)
        module, _, detail = rest.partition(SEPARATOR)
        if status == "start":
            started.append(module)
        elif status == "ok":
            loaded.add(module)
        elif status == "fail":
            failures.append(LoadFailure(module, detail or "no detail reported"))

    resolved = loaded | {failure.module for failure in failures}
    unresolved = [name for name in started if name not in resolved]
    failures += [
        LoadFailure(
            name,
            "the interpreter died during this import; no exception was raised",
        )
        for name in unresolved
    ]
    never_started = [
        name for name in attempted if name not in started and name not in resolved
    ]
    failures += [
        LoadFailure(name, "never attempted; the probe stopped before reaching it")
        for name in never_started
    ]
    return len(loaded), tuple(sorted(failures))


def run_probe(
    repo_root: Path = REPO_ROOT,
    *,
    timeout: float = TIMEOUT_SECONDS,
) -> LoadProbeResult:
    """Import every governed module in an isolated child process.

    Args:
        repo_root: The repository to probe.
        timeout: Seconds to wait before giving up on the child.

    Returns:
        The typed result.
    """
    modules = governed_modules(repo_root / "src" / PACKAGE_ROOT.name, repo_root)
    if len(modules) < MINIMUM_GOVERNED_MODULES:
        return LoadProbeResult(
            reason=(
                f"the probe found {len(modules)} governed module(s), under the "
                f"{MINIMUM_GOVERNED_MODULES} the production tree must hold, so a "
                "clean run would prove nothing"
            ),
        )

    try:
        completed = run_tool(
            ["python", "-m", "dev.quality.import_load_worker", *modules],
            cwd=repo_root,
            timeout=timeout,
        )
    except ToolUnavailableError as exc:
        return LoadProbeResult(reason=str(exc))

    loaded, failures = parse_worker_output(completed.stdout, modules)
    if not loaded and not failures:
        tail = (completed.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else "no output"
        return LoadProbeResult(reason=f"the probe produced no result lines: {detail}")
    return LoadProbeResult(attempted=len(modules), loaded=loaded, failures=failures)


def result_as_json(result: LoadProbeResult) -> str:
    """Render the probe result as the machine-readable report.

    Args:
        result: The probe result.

    Returns:
        The JSON document.
    """
    return json.dumps(
        {
            "available": result.is_available,
            "headline": result.headline(),
            "attempted": result.attempted,
            "loaded": result.loaded,
            "reason": result.reason,
            "failures": [
                {"module": f.module, "detail": f.detail} for f in result.failures
            ],
        },
        indent=2,
        ensure_ascii=False,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe and report.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        :data:`OK` when every module loads, :data:`FAILED` when one does not,
        and :data:`TOOL_BROKEN` when the probe could not run.
    """
    parser = argparse.ArgumentParser(
        description="Prove every shipped production module imports.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the result as JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = run_probe()
    report = result_as_json(result) if args.json else result.report()
    stream = sys.stdout if result.is_clean else sys.stderr
    stream.write(report + "\n")

    if not result.is_available:
        return TOOL_BROKEN
    return OK if result.is_clean else FAILED


if __name__ == "__main__":
    raise SystemExit(main())
