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
    PACKAGE,
    TOP_N,
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
    else:
        print(render_report(dimensions, top_n=args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
