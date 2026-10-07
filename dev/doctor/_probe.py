"""Shared primitives for probing an external tool and reporting the verdict.

The probes in this package all have the same shape: run an executable through
:func:`dev.process.run_captured` to learn its version, and either report
success or explain how to install the thing that is missing. Expressing that
shape once is what keeps the individual checks declarative.
"""

from __future__ import annotations

import re
import sys

__all__ = ["fail", "format_version", "parse_version", "report", "warn"]

#: Matches the first dotted numeric triple in a version banner. Tools pad their
#: ``--version`` output with names, build hashes, and release channels; the
#: triple is the only part any of these checks compares.
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(banner: str) -> tuple[int, int, int] | None:
    """Extract the first dotted numeric triple from a version banner.

    Args:
        banner: The raw ``--version`` output.

    Returns:
        The parsed ``(major, minor, patch)`` triple, or ``None`` when the
        banner carries no recognisable version.
    """
    match = _SEMVER.search(banner)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def format_version(version: tuple[int, int, int]) -> str:
    """Render a parsed version triple back into dotted form."""
    return ".".join(str(part) for part in version)


def fail(message: str) -> int:
    """Report a blocking diagnosis and return the gating exit code.

    Args:
        message: What is wrong and how to fix it.

    Returns:
        Always 1, so the caller can ``return fail(...)`` in one line.
    """
    print(message, file=sys.stderr, flush=True)
    return 1


def warn(message: str) -> int:
    """Report a non-blocking diagnosis and return the passing exit code.

    Used by the optional probes, whose whole contract is that a missing tool
    is information rather than a failure.

    Args:
        message: What is missing and when it would matter.

    Returns:
        Always 0.
    """
    print(message, file=sys.stderr, flush=True)
    return 0


def report(message: str) -> None:
    """Print a satisfied-requirement line to stdout."""
    print(message, flush=True)
