"""Run the real ``vaultspec-a2a`` operator CLI in a child process.

The one runner for suites that drive a CLI verb end to end. A child process
rather than an in-process call because every verb reads the process-wide
settings singleton: configuring a child through its environment exercises the
real configuration path, where reaching into the singleton would only prove that
the singleton can be overwritten. The argv comes from the runtime's own
self-execution authority, so the child is the CLI an installed runtime runs.

The environments a child is given are built here too, because they are the same
question every caller answers: what the inherited environment looks like once a
test has named the variables it cares about.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

from ..utils.runtime_exec import CLI_MODULE, self_command
from .children import run_child

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Mapping

__all__ = [
    "clean_subprocess_environment",
    "combined_output",
    "inherited_environment",
    "run_cli",
]

# Interpreter and package-manager state that would leak the running virtual
# environment into a child asked to exercise a freshly installed one.
_LEAKING_ENVIRONMENT_NAMES = (
    "PYTHONHOME",
    "PYTHONPATH",
    "UV_PROJECT_ENVIRONMENT",
    "VIRTUAL_ENV",
)


def _overlaid(
    environment: dict[str, str], overlay: Mapping[str, str | None] | None
) -> dict[str, str]:
    for name, value in (overlay or {}).items():
        if value is None:
            environment.pop(name, None)
        else:
            environment[name] = value
    return environment


def inherited_environment(
    overlay: Mapping[str, str | None] | None = None,
) -> dict[str, str]:
    """The current environment with *overlay* applied.

    A ``None`` value removes the name rather than blanking it, so a child can be
    started without a setting the test session itself declares.
    """
    return _overlaid(dict(os.environ), overlay)


def clean_subprocess_environment() -> dict[str, str]:
    """The current environment with this virtual environment's leakage removed.

    A child asked to exercise a freshly installed capsule must not inherit the
    running interpreter's ``PYTHONHOME``/``PYTHONPATH`` or the project's uv
    environment pointers, or it resolves the development tree instead of what
    was installed. Colour and progress output are also suppressed so captured
    output is comparable.
    """
    return inherited_environment(
        {
            **dict.fromkeys(_LEAKING_ENVIRONMENT_NAMES),
            "NO_COLOR": "1",
            "UV_NO_PROGRESS": "1",
        }
    )


class _CapturedOutput(Protocol):
    """A finished child's captured text streams, however its runner records them."""

    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...


def combined_output(result: _CapturedOutput) -> str:
    """*result*'s standard output followed by its standard error."""
    return result.stdout + result.stderr


def run_cli(
    *argv: str,
    env: Mapping[str, str | None] | None = None,
    interpreter: os.PathLike[str] | str | None = None,
    cwd: os.PathLike[str] | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``vaultspec-a2a *argv`` to completion, capturing its text output.

    *env* overlays the inherited environment, so a caller can point the
    configured ports, stores or timeouts somewhere specific without having to
    restate everything else the child needs to start; a ``None`` value removes
    the name instead. The wait is progress-based: a child that stops making
    progress fails the call, a merely slow one does not.

    *interpreter* runs the CLI of another installed runtime instead of this one.
    Such a child is given :func:`clean_subprocess_environment` as the
    environment *env* overlays, so it resolves what was installed and not the
    development tree. *cwd* is the directory the child starts in.
    """
    if interpreter is None:
        command = self_command(*argv)
        child_env = inherited_environment(env)
    else:
        command = [os.fspath(interpreter), "-m", CLI_MODULE, *argv]
        child_env = _overlaid(clean_subprocess_environment(), env)
    return run_child(
        command,
        what=f"vaultspec-a2a {' '.join(argv)}",
        env=child_env,
        cwd=cwd,
    )
