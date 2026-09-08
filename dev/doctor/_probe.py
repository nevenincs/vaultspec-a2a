"""Shared primitives for probing an external tool and reporting the verdict.

The probes in this package all have the same shape: resolve an executable,
run it to learn its version, and either report success or explain how to
install the thing that is missing. Expressing that shape once is what keeps
the individual checks declarative.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Matches the first dotted numeric triple in a version banner. Tools pad their
#: ``--version`` output with names, build hashes, and release channels; the
#: triple is the only part any of these checks compares.
_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def which(tool: str) -> str | None:
    """Return the resolved path to ``tool``, or ``None`` when it is absent.

    Resolution goes through :func:`shutil.which` rather than handing the bare
    name to :mod:`subprocess`, because on Windows the interesting tools ship as
    ``.cmd`` shims that only PATHEXT resolution finds.

    Args:
        tool: The executable name to look for on ``PATH``.

    Returns:
        The resolved absolute path, or ``None``.
    """
    return shutil.which(tool)


def capture(argv: Sequence[str]) -> tuple[int, str]:
    """Run a command and capture its combined output.

    Args:
        argv: The argument vector to execute. Never a shell string.

    Returns:
        A ``(returncode, output)`` pair. A missing or unrunnable executable
        yields a non-zero code and the reason as the output.
    """
    resolved = which(argv[0])
    if resolved is None:
        return 127, f"{argv[0]} not found on PATH"
    try:
        completed = subprocess.run(
            [resolved, *argv[1:]],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 127, f"{argv[0]} could not be executed: {exc}"
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


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
