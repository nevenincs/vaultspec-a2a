"""The ``python -m dev.doctor`` entry point.

Usage::

    python -m dev.doctor required
    python -m dev.doctor docker
    python -m dev.doctor docker-optional
    python -m dev.doctor pep561
    python -m dev.doctor check

``check`` is the everyday form: required tools gate, Docker only reports.
"""

from __future__ import annotations

import argparse

from dev.doctor._docker import docker_optional, docker_required
from dev.doctor._pep561 import repair_markers
from dev.doctor._tools import node, required


def _pep561() -> int:
    """Restore the PEP 561 markers a namespace-rooted distribution published."""
    created = repair_markers()
    if created:
        print(f"pep561: created {created} marker(s)")
    return 0


#: The selectable checks, mapped to the callable that performs each one.
CHECKS = {
    "required": required,
    "node": node,
    "docker": docker_required,
    "docker-optional": docker_optional,
    "pep561": _pep561,
}


def _check() -> int:
    """Diagnose required tools and report optional Docker support."""
    code = required()
    docker_optional()
    return code


def main(argv: list[str] | None = None) -> int:
    """Dispatch one diagnosis and return its exit code.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        The exit code of the selected check.
    """
    parser = argparse.ArgumentParser(
        prog="python -m dev.doctor",
        description="Diagnose the tools this development harness needs.",
    )
    parser.add_argument(
        "check",
        nargs="?",
        default="check",
        choices=["check", *CHECKS],
        help="which diagnosis to run (default: check)",
    )
    args = parser.parse_args(argv)
    if args.check == "check":
        return _check()
    return CHECKS[args.check]()


if __name__ == "__main__":
    raise SystemExit(main())
