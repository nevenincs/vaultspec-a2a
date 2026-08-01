"""Rank the worst offenders across every measurable code-health dimension.

Six dimensions are measured here, each against the published industry default
for its metric rather than against this tree's current worst value:

============ ========= ==================================================
Dimension    Threshold Source of the threshold
============ ========= ==================================================
cyclomatic   10        McCabe's own recommendation; the flake8, ruff, and
                       SonarQube default. REPORTED here, GATED by ruff's
                       ``C901`` - radon scores strictly higher because it
                       also counts boolean operators, ternaries, and
                       comprehensions. See :data:`GATED`.
maintain.    20        Radon's own A/B boundary for the Maintainability
                       Index; below 20 is documented as hard to maintain.
module LOC   1000      Pylint's ``max-module-lines`` default, and this
                       repository's own stated module-size mandate.
statements   50        Pylint ``R0915`` / ruff ``PLR0915`` default.
arguments    5         Pylint ``R0913`` / ruff ``PLR0913`` default.
nesting      5         Ruff ``PLR1702`` default.
============ ========= ==================================================

Cyclomatic complexity and the Maintainability Index come from ``radon``'s
library API rather than by parsing its command output - the numbers are the
tool's own, and there is no text format in between to drift. The four
structural dimensions are counted directly from the AST.

Cognitive complexity is deliberately ABSENT. It is a distinct metric from
cyclomatic complexity - it measures how much state a reader must hold, not how
many paths exist - and ``complexipy`` is its implementation here. Restating it
in this module would mean reimplementing a scoring specification, and the two
copies would disagree the first time either moved. Run ``just dev lint
complexity`` for that dimension.
"""

from __future__ import annotations

import ast
import importlib
import json
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import Protocol

    class _RadonBlock(Protocol):
        @property
        def lineno(self) -> int: ...

        @property
        def name(self) -> str: ...

        @property
        def complexity(self) -> int: ...

    class _CCVisit(Protocol):
        def __call__(self, code: str, **kwargs: object) -> Sequence[_RadonBlock]: ...

    class _MIVisit(Protocol):
        def __call__(self, code: str, multi: bool) -> float: ...


cc_visit = cast("_CCVisit", importlib.import_module("radon.complexity").cc_visit)
mi_visit = cast("_MIVisit", importlib.import_module("radon.metrics").mi_visit)

#: The production package measured by every dimension below.
PACKAGE = Path("src") / "vaultspec_a2a"

#: How many worst offenders each dimension lists in the default report.
TOP_N = 10

#: Industry-default limits. See the module docstring for each one's provenance.
MAX_CYCLOMATIC = 10
MIN_MAINTAINABILITY = 20
MAX_MODULE_LINES = 1000
MAX_STATEMENTS = 50
MAX_ARGUMENTS = 5
MAX_NESTING = 5

#: A dimension is RED when any offender exceeds the threshold by this factor.
#: Below it the dimension is AMBER: real debt, but within reach of a normal
#: refactor rather than a rewrite.
RED_FACTOR = 2.0


@dataclass(frozen=True)
class Offender:
    """One measured entity that exceeds a dimension's threshold.

    Args:
        locator: ``path:line`` for a block, or ``path`` for a whole module.
        name: The function, method, or module name.
        value: The measured value.
    """

    locator: str
    name: str
    value: float


@dataclass
class Dimension:
    """One measured dimension and everything that exceeds its threshold.

    Args:
        key: Machine-readable dimension name.
        title: Human-readable heading.
        threshold: The industry-default limit.
        unit: What the value counts, for the report line.
        lower_is_better: False for the Maintainability Index, where a HIGHER
            score is healthier and the threshold is a floor rather than a
            ceiling.
        offenders: Everything past the threshold, worst first.
        measured: How many entities were measured in total.
    """

    key: str
    title: str
    threshold: float
    unit: str
    lower_is_better: bool = True
    offenders: list[Offender] = field(default_factory=list[Offender])
    measured: int = 0

    @property
    def worst(self) -> float | None:
        """Return the single worst measured value, or None when clean."""
        return self.offenders[0].value if self.offenders else None

    @property
    def status(self) -> str:
        """Return ``GREEN``, ``AMBER``, or ``RED`` for this dimension."""
        if not self.offenders:
            return "GREEN"
        worst = self.offenders[0].value
        if self.lower_is_better:
            breached = worst >= self.threshold * RED_FACTOR
        else:
            breached = worst <= self.threshold / RED_FACTOR
        return "RED" if breached else "AMBER"

    def add(self, locator: str, name: str, value: float) -> None:
        """Record one entity, keeping it only when it breaches the threshold."""
        self.measured += 1
        over = (
            value > self.threshold if self.lower_is_better else value < self.threshold
        )
        if over:
            self.offenders.append(Offender(locator, name, value))

    def finalize(self) -> None:
        """Sort offenders worst-first."""
        self.offenders.sort(key=lambda o: o.value, reverse=self.lower_is_better)


def _python_files(root: Path) -> Iterator[Path]:
    """Yield every production ``.py`` file beneath ``root``, tests excluded.

    Test modules are excluded on purpose. A guard test that walks the AST of
    every module to prove a structural invariant scores badly on every
    dimension here, because branching over a syntax tree is what such a test
    IS. Ranking production code against production thresholds keeps the report
    pointed at debt someone can actually pay down.
    """
    for path in sorted(root.rglob("*.py")):
        # Matches `tests`, `service_tests`, `desktop_tests`, and any future
        # tier named the same way. Listing the directories individually is how
        # `desktop_tests` leaked into the production ranking the first time.
        if any(part == "tests" or part.endswith("_tests") for part in path.parts):
            continue
        yield path


def _nesting_depth(node: ast.AST) -> int:
    """Return the maximum nested block depth inside one function body."""
    nesting = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.With,
        ast.AsyncWith,
        ast.Try,
    )

    def walk(current: ast.AST, depth: int) -> int:
        deepest = depth
        for child in ast.iter_child_nodes(current):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            child_depth = depth + 1 if isinstance(child, nesting) else depth
            deepest = max(deepest, walk(child, child_depth))
        return deepest

    return walk(node, 0)


def _count_statements(node: ast.AST) -> int:
    """Return the number of statements in one function body."""
    return sum(1 for child in ast.walk(node) if isinstance(child, ast.stmt)) - 1


def _count_arguments(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return a function's parameter count, excluding ``self`` and ``cls``."""
    args = node.args
    total = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    total += 1 if args.vararg else 0
    total += 1 if args.kwarg else 0
    first = (args.posonlyargs or args.args or [None])[0]
    if first is not None and first.arg in {"self", "cls"}:
        total -= 1
    return total


def measure(root: Path = PACKAGE) -> list[Dimension]:
    """Measure every dimension over the production package.

    Args:
        root: The package root to walk.

    Returns:
        Every dimension, offenders sorted worst-first.
    """
    cyclomatic = Dimension(
        "cyclomatic", "Cyclomatic complexity (radon)", MAX_CYCLOMATIC, "paths"
    )
    maintainability = Dimension(
        "maintainability",
        "Maintainability index",
        MIN_MAINTAINABILITY,
        "MI",
        lower_is_better=False,
    )
    module_lines = Dimension("module-lines", "Module length", MAX_MODULE_LINES, "lines")
    statements = Dimension(
        "statements", "Function length", MAX_STATEMENTS, "statements"
    )
    arguments = Dimension("arguments", "Parameter count", MAX_ARGUMENTS, "arguments")
    nesting = Dimension("nesting", "Nesting depth", MAX_NESTING, "levels")

    for path in _python_files(root):
        text = path.read_text(encoding="utf-8")
        posix = path.as_posix()

        module_lines.add(posix, path.name, len(text.splitlines()))

        # A module radon cannot score is skipped rather than failing the run:
        # this is an instrument, and one unparseable file must not cost the
        # ranking of the other 246.
        with suppress(SyntaxError, ValueError):
            maintainability.add(posix, path.name, mi_visit(text, multi=True))

        with suppress(SyntaxError):
            for block in cc_visit(text):
                cyclomatic.add(f"{posix}:{block.lineno}", block.name, block.complexity)

        try:
            tree = ast.parse(text, filename=posix)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            locator = f"{posix}:{node.lineno}"
            statements.add(locator, node.name, _count_statements(node))
            arguments.add(locator, node.name, _count_arguments(node))
            nesting.add(locator, node.name, _nesting_depth(node))

    dimensions = [
        cyclomatic,
        maintainability,
        module_lines,
        statements,
        arguments,
        nesting,
    ]
    for dimension in dimensions:
        dimension.finalize()
    return dimensions


def _format_value(value: float) -> str:
    """Render a measured value without a trailing ``.0`` on whole numbers."""
    return f"{value:.1f}" if value % 1 else f"{int(value)}"


def render_report(
    dimensions: Sequence[Dimension], top_n: int = TOP_N, *, gating: bool = False
) -> str:
    """Render the human-readable ranked report.

    Args:
        dimensions: The measured dimensions.
        top_n: How many offenders to list per dimension.
        gating: Whether the caller will exit non-zero on a finding. The banner
            must say which of the two this run is, because the same text under
            both consequences is how a reader learns to distrust the banner.

    Returns:
        The full report text.
    """
    banner = (
        "Code-health GATE - a dimension with any offender fails this run."
        if gating
        else "Code-health report - MEASUREMENT ONLY, always exits 0."
    )
    lines = [
        banner,
        "Thresholds are published industry defaults, not this tree's current worst.",
        "",
    ]

    width = max(len(d.title) for d in dimensions)
    lines.append("SUMMARY")
    for dimension in dimensions:
        comparator = "<=" if dimension.lower_is_better else ">="
        worst = dimension.worst
        worst_text = "-" if worst is None else _format_value(worst)
        lines.append(
            f"  {dimension.status:<5}  {dimension.title:<{width}}  "
            f"{len(dimension.offenders):>4} over  "
            f"(limit {comparator} {_format_value(dimension.threshold)}, "
            f"worst {worst_text}, {dimension.measured} measured)"
        )

    for dimension in dimensions:
        if not dimension.offenders:
            continue
        lines.extend(["", f"{dimension.title.upper()} - worst {top_n}"])
        for offender in dimension.offenders[:top_n]:
            lines.append(
                f"  {_format_value(offender.value):>6} {dimension.unit:<11} "
                f"{offender.name}  ({offender.locator})"
            )
        remaining = len(dimension.offenders) - top_n
        if remaining > 0:
            lines.append(f"  ... and {remaining} more over the limit")

    lines.extend(
        [
            "",
            "Cognitive complexity is measured separately by 'just lint complexity'",
            "(complexipy, Sonar limit 15); duplication by 'just audit duplication'",
            "and dead code by 'just audit dead-code'.",
        ]
    )
    return "\n".join(lines)


def render_census(dimensions: Sequence[Dimension]) -> str:
    """Render the full distribution behind each dimension.

    Args:
        dimensions: The measured dimensions.

    Returns:
        The census text - every offender, not just the worst.
    """
    lines = ["Code-health census - every entity past its threshold.", ""]
    for dimension in dimensions:
        lines.append(
            f"{dimension.title} (limit {_format_value(dimension.threshold)}, "
            f"{dimension.measured} measured, {len(dimension.offenders)} over)"
        )
        for offender in dimension.offenders:
            lines.append(
                f"  {_format_value(offender.value):>6}  {offender.name}  "
                f"({offender.locator})"
            )
        lines.append("")
    return "\n".join(lines)


#: Dimensions that GATE when :mod:`dev.health` is run with ``--gate``.
#:
#: The gate and the report are the same measurement - the gate simply refuses
#: to exit 0 - so the two can never disagree about a number.
#:
#: ``cyclomatic`` is deliberately ABSENT, though this module measures it. Ruff's
#: ``C901`` already gates that dimension from ``just lint limits``, and the two
#: tools do not agree: on
#: ``control/permission_service.py::_authorize_permission_response`` radon
#: scores 26 and ruff scores 15, because radon also counts boolean operators,
#: ternaries, and comprehensions while ruff counts only ``if``/``elif``/loops.
#: Both numbers are correct for their own definition, but two gates at one
#: threshold claiming one name is worse than either alone - a burndown would not
#: know which number it was driving to zero. Ruff owns the gate because the
#: conventional ceiling of 10 is calibrated against its mccabe definition;
#: radon's stricter reading stays here as a ranking signal.
GATED = ("module-lines", "statements", "arguments", "nesting")


def render_json(dimensions: Sequence[Dimension]) -> str:
    """Render the machine-readable report.

    Args:
        dimensions: The measured dimensions.

    Returns:
        A JSON document keyed by dimension.
    """
    payload = {
        dimension.key: {
            "title": dimension.title,
            "threshold": dimension.threshold,
            "lower_is_better": dimension.lower_is_better,
            "status": dimension.status,
            "measured": dimension.measured,
            "over": len(dimension.offenders),
            "worst": dimension.worst,
            "offenders": [
                {
                    "locator": offender.locator,
                    "name": offender.name,
                    "value": offender.value,
                }
                for offender in dimension.offenders
            ],
        }
        for dimension in dimensions
    }
    return json.dumps(payload, indent=2)
