"""The ``python -m dev.health`` entry point.

Usage::

    python -m dev.health            # ranked worst-offender report
    python -m dev.health --json     # the same data, machine-readable
    python -m dev.health --census   # every offender, not just the worst

Always exits 0. This is an instrument, not a gate.
"""

from __future__ import annotations

import argparse
import sys

from dev.health.report import (
    GATED,
    PACKAGE,
    TOP_N,
    Dimension,
    measure,
    render_census,
    render_json,
    render_report,
)


def main(argv: list[str] | None = None) -> int:
    """Measure the package and print the requested rendering.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        Always 0 - see the module docstring.
    """
    parser = argparse.ArgumentParser(
        prog="python -m dev.health",
        description="Rank the worst offenders across every code-health dimension.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="emit the report as JSON")
    group.add_argument(
        "--census",
        action="store_true",
        help="list every offender rather than the worst few",
    )
    group.add_argument(
        "--gate",
        metavar="DIMENSION",
        nargs="?",
        const="",
        help=(
            "exit 1 when a dimension has any offender; names one dimension, or "
            f"gates all of {', '.join(GATED)} when given no value"
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=TOP_N,
        help=f"how many offenders to list per dimension (default {TOP_N})",
    )
    args = parser.parse_args(argv)

    if not PACKAGE.is_dir():
        print(
            f"{PACKAGE} not found - run this from the repository root.",
            file=sys.stderr,
        )
        return 0

    dimensions = measure()
    if args.json:
        print(render_json(dimensions))
    elif args.census:
        print(render_census(dimensions))
    elif args.gate is not None:
        return _gate(dimensions, args.gate, top_n=args.top)
    else:
        print(render_report(dimensions, top_n=args.top))
    return 0


def _gate(dimensions: list[Dimension], selected: str, *, top_n: int) -> int:
    """Report the selected dimensions and exit non-zero when any has offenders.

    Args:
        dimensions: The measured dimensions.
        selected: One dimension key, or ``""`` for every gated dimension.
        top_n: How many offenders to list per dimension.

    Returns:
        1 when any selected dimension has an offender, otherwise 0. Unlike
        every other rendering here, this one is a GATE - it is what makes
        ``just dev lint cyclomatic`` fail a build.
    """
    keys = (selected,) if selected else GATED
    known = {d.key for d in dimensions}
    unknown = [key for key in keys if key not in known]
    if unknown:
        print(
            f"unknown health dimension(s): {', '.join(unknown)}\n"
            f"  dimensions: {', '.join(sorted(known))}",
            file=sys.stderr,
        )
        return 2

    chosen = [d for d in dimensions if d.key in set(keys)]
    print(render_report(chosen, top_n=top_n, gating=True))
    breached = [d for d in chosen if d.offenders]
    if breached:
        print(
            "\nGATE FAILED: "
            + ", ".join(f"{d.title} ({len(d.offenders)} over)" for d in breached),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
