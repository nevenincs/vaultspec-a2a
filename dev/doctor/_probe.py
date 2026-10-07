"""Shared primitives for reporting a probe's verdict.

The probes in this package all have the same shape: ask a tool whether it is
there and working - through :func:`dev.init.probe.check`, the one host-tool
probe in ``dev/``, or :func:`dev.process.run_captured` for the checks that are
not a version - and either report success or explain how to install the thing
that is missing. Expressing the reporting once is what keeps the individual
checks declarative.
"""

from __future__ import annotations

import sys

from dev.exit_codes import FAILED, OK

__all__ = ["fail", "report", "warn"]


def fail(message: str) -> int:
    """Report a blocking diagnosis and return the gating exit code.

    Args:
        message: What is wrong and how to fix it.

    Returns:
        Always :data:`FAILED`, so the caller can ``return fail(...)`` in one
        line.
    """
    print(message, file=sys.stderr, flush=True)
    return FAILED


def warn(message: str) -> int:
    """Report a non-blocking diagnosis and return the passing exit code.

    Used by the optional probes, whose whole contract is that a missing tool
    is information rather than a failure.

    Args:
        message: What is missing and when it would matter.

    Returns:
        Always :data:`OK`.
    """
    print(message, file=sys.stderr, flush=True)
    return OK


def report(message: str) -> None:
    """Print a satisfied-requirement line to stdout."""
    print(message, flush=True)
