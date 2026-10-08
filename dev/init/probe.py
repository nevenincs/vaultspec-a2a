"""Host-tool discovery: what the workstation must already provide.

``init`` provisions the worktree, not the workstation. The distinction is the
whole of what this module enforces. Dependencies pinned by a lockfile inside
the repository are `init`'s job and it installs them; `uv`, `just`, `node`,
`rustup` and `mise` are the operator's, and `init` reports them precisely and
refuses to guess at a package manager.

That refusal is deliberate. A bootstrap that silently installs system packages
is one a person cannot run on a machine they do not administer, cannot run in a
sandbox, and cannot reason about afterwards. Reporting
:data:`dev.exit_codes.INIT_HOST_TOOL_MISSING` with the tool's own installation
URL is a better outcome than a half-provisioned host.

This is the one host-tool probe in ``dev/``: :mod:`dev.doctor` asks it the same
questions about the tools a developer runs recipes with, so "present",
"working" and "new enough" mean one thing whichever command asked.

Stdlib-only, by the constraint stated in :mod:`dev.init`; a tool is asked its
version through :func:`dev.process.run_captured`, which is stdlib-only as well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dev.process import (
    ToolMissingError,
    ToolUnavailableError,
    combined_output,
    run_captured,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["VERSION_TIMEOUT_SECONDS", "Finding", "Requirement", "check", "check_all"]

#: Matches the first dotted version in a `--version` banner. Every tool this
#: fleet requires prints one, in among a varying amount of other text.
_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")

#: Ceiling on one version probe. A tool that cannot say its version inside a
#: minute has hung, and a hung tool is not one the workstation provides.
VERSION_TIMEOUT_SECONDS: Final[float] = 60.0


@dataclass(frozen=True)
class Requirement:
    """A tool the workstation must provide.

    Attributes:
        command: The executable name, as it must appear on ``PATH``.
        purpose: What this repository needs it for, in one line.
        install_url: Where a person gets it.
        minimum: The lowest acceptable version, as a dotted string, or ``None``
            when any version will do.
        version_argv: How to ask it its version, when that differs from
            ``(command, "--version")``.
        advisory: When true, absence is reported and does not fail `init`.
            Used for tools only some workflows need - Docker, a container
            runtime, a browser channel.
    """

    command: str
    purpose: str
    install_url: str
    minimum: str | None = None
    version_argv: tuple[str, ...] | None = None
    advisory: bool = False


@dataclass(frozen=True)
class Finding:
    """The outcome of probing one requirement.

    Attributes:
        command: The executable that was probed.
        ok: Whether the requirement is satisfied.
        found: The version that was found, or ``None`` when the tool is absent,
            could not report one, or printed nothing recognizable.
        message: One line stating the outcome and, when it is not satisfied,
            the remedy.
        advisory: Carried through from the requirement.
    """

    command: str
    ok: bool
    found: str | None
    message: str
    advisory: bool


def _version_of(requirement: Requirement) -> str | None:
    """Return the dotted version a tool reports, or ``None``.

    Args:
        requirement: The tool to interrogate.

    Returns:
        The first dotted version in its banner, or ``None`` when it answered
        and printed nothing recognizable.

    Raises:
        ToolMissingError: When the executable is not on ``PATH``.
        ToolUnavailableError: When it could not be launched, did not answer
            inside :data:`VERSION_TIMEOUT_SECONDS`, or its version command
            exited non-zero. A tool that cannot answer ``--version`` is not one
            the workstation provides, whatever its banner happened to say.
    """
    declared = requirement.version_argv or (requirement.command, "--version")
    argv = [requirement.command, *declared[1:]]
    completed = run_captured(argv, timeout=VERSION_TIMEOUT_SECONDS)
    banner = combined_output(completed)
    if completed.returncode != 0:
        detail = banner.splitlines()[-1] if banner else "no output"
        msg = f"`{' '.join(argv)}` exited {completed.returncode}: {detail}"
        raise ToolUnavailableError(msg)
    match = _VERSION.search(banner)
    return match.group(0) if match else None


def _tuple(version: str) -> tuple[int, ...]:
    """Return a comparable tuple for a dotted version string.

    Args:
        version: A dotted version, possibly with fewer than three components.

    Returns:
        A three-element tuple of integers, zero-padded.
    """
    parts = [int(part) for part in version.split(".")[:3] if part.isdigit()]
    return tuple(parts + [0] * (3 - len(parts)))


def _absent(requirement: Requirement) -> str:
    """Return the message for a tool that is not on ``PATH``.

    Args:
        requirement: The tool that is missing.

    Returns:
        The one line a person needs: what it was for, and where to get it.
    """
    where = f"Install it from {requirement.install_url}"
    return f"{requirement.command} is not on PATH. {requirement.purpose} {where}"


def _finding(
    requirement: Requirement, *, ok: bool, found: str | None, message: str
) -> Finding:
    """Return one requirement's finding, carrying its advisory flag through."""
    return Finding(
        command=requirement.command,
        ok=ok,
        found=found,
        message=message,
        advisory=requirement.advisory,
    )


def check(requirement: Requirement) -> Finding:
    """Probe one requirement.

    Args:
        requirement: The tool to check for.

    Returns:
        The finding, whose ``message`` is the whole of what a person needs.
    """
    try:
        found = _version_of(requirement)
    except ToolMissingError:
        return _finding(requirement, ok=False, found=None, message=_absent(requirement))
    except ToolUnavailableError as exc:
        return _finding(
            requirement,
            ok=False,
            found=None,
            message=(
                f"{requirement.command} is installed but could not report its "
                f"version ({exc}). See {requirement.install_url}"
            ),
        )
    if requirement.minimum is None:
        return _finding(
            requirement,
            ok=True,
            found=found,
            message=f"{requirement.command} {found or '(version unknown)'}",
        )
    if found is None:
        return _finding(
            requirement,
            ok=False,
            found=None,
            message=(
                f"{requirement.command} is installed but did not report a version; "
                f"this repository requires >= {requirement.minimum}. "
                f"See {requirement.install_url}"
            ),
        )
    if _tuple(found) < _tuple(requirement.minimum):
        return _finding(
            requirement,
            ok=False,
            found=found,
            message=(
                f"{requirement.command} {found} is too old; this repository "
                f"requires >= {requirement.minimum}. See {requirement.install_url}"
            ),
        )
    return _finding(
        requirement,
        ok=True,
        found=found,
        message=f"{requirement.command} {found} (requires >= {requirement.minimum})",
    )


def check_all(requirements: Iterable[Requirement]) -> list[Finding]:
    """Probe every requirement.

    Args:
        requirements: The tools to check for.

    Returns:
        One finding per requirement, in declaration order. Every requirement is
        probed even after one fails, because a person fixing their workstation
        wants the whole list, not the first item of it.
    """
    return [check(requirement) for requirement in requirements]
