"""Process-execution primitives shared by every development verb.

Each step type below is a small, declarative description of one action. They
are data rather than code so :mod:`dev.toolchain` can state the toolchain as a
table, and so the platform-specific parts - executable resolution, Docker
fallback, environment overlay - are implemented once here instead of being
re-expressed in each recipe.

This module imports the standard library only. That is what lets the harness
behave identically on Windows, macOS, and Linux without a second shell dialect.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Exit code for "the required tool is not installed and has no fallback".
#: 127 is the conventional shell status for command-not-found, which keeps the
#: meaning legible to CI logs and to anyone reading the exit code directly.
TOOL_MISSING = 127

#: The locked tooling profile every read-only recipe resolves against.
#:
#: ``--no-sync`` keeps ``uv run`` from re-resolving and rebuilding the project
#: into ``.venv``. That rebuild fails on Windows whenever a resident process -
#: an MCP server, an editor, another agent's session - holds one of the
#: console-script executables open. ``--frozen`` refuses to silently update the
#: lock. The recipes whose purpose IS to change the environment call ``uv``
#: directly and deliberately omit all of this.
TOOLING_PROFILE = ("--frozen", "--no-default-groups", "--group", "tooling")


@dataclass(frozen=True)
class Cmd:
    """A single subprocess invocation.

    Args:
        argv: The full argument vector, already split. Never a shell string -
            passing a list is what keeps quoting identical on every platform.
        env: Environment variables overlaid on the inherited environment.
    """

    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True)
class ToolOrDocker:
    """An external tool, falling back to its Docker image when absent.

    ``taplo`` and ``actionlint`` are native binaries rather than Python
    packages, so they cannot always be pinned in the lockfile and may simply be
    missing. Rather than fail, the harness runs the pinned image with the
    working tree mounted at ``/repo``.

    Args:
        tool: Executable name to look for on ``PATH``.
        argv: Arguments passed to the native executable.
        image: Docker image reference used when the executable is absent.
        docker_argv: Arguments passed to the container. Defaults to ``argv``,
            and differs only where the container needs repo-absolute paths.
    """

    tool: str
    argv: tuple[str, ...]
    image: str
    docker_argv: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Echo:
    """A section header printed between the steps of an aggregate target."""

    text: str


@dataclass(frozen=True)
class Ref:
    """A reference to another target within the same verb.

    Aggregates such as ``lint all`` are expressed as references rather than by
    repeating their steps, so a target and its use in an aggregate cannot drift
    apart.
    """

    target: str


Step = Cmd | ToolOrDocker | Echo | Ref


def run(argv: Sequence[str], env: Mapping[str, str] | None = None) -> int:
    """Run one subprocess and return its exit code.

    Args:
        argv: The argument vector to execute.
        env: Variables overlaid on the inherited environment.

    Returns:
        The child process exit code, or :data:`TOOL_MISSING` when the
        executable does not exist.
    """
    merged = {**os.environ, **(env or {})}
    print(f"$ {' '.join(argv)}", flush=True)

    # Resolve through `shutil.which` rather than handing the bare name to
    # `subprocess`. On Windows the interesting tools ship as `.cmd` shims -
    # `npx` is a POSIX shell script that CreateProcess cannot execute, while
    # `npx.cmd` beside it is the real entry point - and only PATHEXT resolution
    # finds the right one. Without this, `npx` reads as "not installed" on a
    # machine where Node is installed and on PATH.
    resolved = shutil.which(argv[0])
    if resolved is None:
        print(f"{argv[0]} not found on PATH", file=sys.stderr, flush=True)
        return TOOL_MISSING

    try:
        return subprocess.run([resolved, *argv[1:]], env=merged, check=False).returncode
    except OSError as exc:
        print(f"{argv[0]} could not be executed: {exc}", file=sys.stderr, flush=True)
        return TOOL_MISSING


def run_tool_or_docker(step: ToolOrDocker) -> int:
    """Run a native tool, or its Docker image when the tool is unavailable.

    Args:
        step: The tool description to execute.

    Returns:
        The exit code of whichever form ran, or :data:`TOOL_MISSING` when
        neither the tool nor Docker is present.
    """
    if shutil.which(step.tool):
        return run([step.tool, *step.argv])
    if shutil.which("docker"):
        container_argv = step.docker_argv if step.docker_argv is not None else step.argv
        return run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{Path.cwd()}:/repo",
                "-w",
                "/repo",
                step.image,
                *container_argv,
            ]
        )
    print(
        f"{step.tool} not found and docker is unavailable",
        file=sys.stderr,
        flush=True,
    )
    return TOOL_MISSING


def uv_run(*argv: str) -> Cmd:
    """Build a command that runs a tool from the locked tooling profile.

    Args:
        *argv: The command and arguments to run inside the environment.

    Returns:
        The corresponding :class:`Cmd`, carrying :data:`TOOLING_PROFILE`.
    """
    return Cmd(("uv", "run", "--no-sync", *TOOLING_PROFILE, *argv))


def uv_run_env(env: Mapping[str, str], *argv: str) -> Cmd:
    """Build a tooling-profile command with environment overrides.

    Args:
        env: Variables overlaid on the inherited environment.
        *argv: The command and arguments to run inside the environment.

    Returns:
        The corresponding :class:`Cmd`.
    """
    return Cmd(uv_run(*argv).argv, env)


def dev_module(module: str, *argv: str) -> Cmd:
    """Build a command that runs one of this harness's own instruments.

    Args:
        module: The dotted module path beneath ``dev``.
        *argv: Arguments passed to the instrument.

    Returns:
        The corresponding :class:`Cmd`.
    """
    return uv_run("python", "-m", f"dev.{module}", *argv)
