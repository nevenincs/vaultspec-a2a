"""Capturing subprocess execution for instruments that parse their tool's output.

:mod:`dev.runner` runs a tool for its EXIT CODE and lets its output stream
straight to the terminal. The instruments in :mod:`dev.quality` and
:mod:`dev.audit` do the opposite: they own their tool's whole measurement -
invoke it, capture it, parse it, and classify the outcome - so they need the
streams back rather than on screen.

Three failure modes are separated here rather than in each caller, because
collapsing them is how a scan that never ran comes to read as a scan that
found nothing:

* the executable is absent,
* it was launched and did not finish inside its timeout,
* it ran, and its exit status is then the caller's to interpret.

Only the third is a measurement. The first two raise
:class:`ToolUnavailableError`, which every caller turns into an explicit
"unavailable" outcome.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING, Final

from dev.paths import REPO_ROOT, UTF_8
from dev.runner import TOOLING_PROFILE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

#: The default ceiling on a captured tool's runtime.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 300.0


class ToolUnavailableError(RuntimeError):
    """A tool could not be run, so its silence is not evidence of anything."""


def run_captured(
    argv: Sequence[str],
    *,
    cwd: Path = REPO_ROOT,
    env: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run a command to completion and return both of its streams.

    Args:
        argv: The argument vector. Never a shell string - passing a list is
            what keeps quoting identical on every platform.
        cwd: The directory to run in.
        env: Variables overlaid on the inherited environment.
        timeout: Seconds to wait before giving up on the tool.

    Returns:
        The completed process. A non-zero status is NOT an error here: it is
        how most scanners report findings, and interpreting it is the caller's
        job.

    Raises:
        ToolUnavailableError: When the executable is not on ``PATH``, could not
            be launched, or did not finish inside ``timeout``.
    """
    # Resolve through `shutil.which` rather than handing the bare name to
    # `subprocess`. On Windows the interesting tools ship as `.cmd` shims -
    # `npx` is a POSIX shell script CreateProcess cannot execute, while
    # `npx.cmd` beside it is the real entry point - and only PATHEXT
    # resolution finds the right one.
    resolved = shutil.which(argv[0])
    if resolved is None:
        msg = f"{argv[0]} is not on PATH"
        raise ToolUnavailableError(msg)

    merged = None if env is None else {**os.environ, **env}
    try:
        # `resolved` is an absolute path from `shutil.which` and the rest of the
        # vector is constructed by the caller; nothing here is shell-parsed.
        return subprocess.run(
            [resolved, *argv[1:]],
            capture_output=True,
            text=True,
            encoding=UTF_8,
            errors="replace",
            check=False,
            cwd=cwd,
            env=merged,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"{argv[0]} exceeded its {timeout:g}s timeout"
        raise ToolUnavailableError(msg) from exc
    except OSError as exc:
        msg = f"{argv[0]} could not be launched ({exc})"
        raise ToolUnavailableError(msg) from exc


def run_tool(
    argv: Sequence[str],
    *,
    cwd: Path = REPO_ROOT,
    env: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run a locked-profile tool through ``uv run``, capturing both streams.

    Args:
        argv: The tool and its arguments, without the ``uv run`` prefix.
        cwd: The directory to run in.
        env: Variables overlaid on the inherited environment.
        timeout: Seconds to wait before giving up on the tool.

    Returns:
        The completed process.

    Raises:
        ToolUnavailableError: As :func:`run_captured`.
    """
    return run_captured(
        ["uv", "run", "--no-sync", *TOOLING_PROFILE, *argv],
        cwd=cwd,
        env=env,
        timeout=timeout,
    )
