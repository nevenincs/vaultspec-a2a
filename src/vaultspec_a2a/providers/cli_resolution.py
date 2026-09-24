"""Canonical platform-aware resolution for provider-owned system CLIs."""

from __future__ import annotations

import os
import shutil
import sys

from ..graph.enums import Provider

__all__ = ["resolve_provider_cli_executable", "resolve_trusted_executable"]

_SYSTEM_CLI_NAMES: dict[Provider, str] = {
    Provider.CLAUDE: "claude",
    Provider.CODEX: "codex",
    Provider.KIMI: "kimi",
}


def _trusted_search_directories(search_path: str | None) -> tuple[str, ...]:
    """Return the absolute directories of one search path, in order.

    A relative entry - including the empty entry POSIX reads as "the working
    directory" - resolves against wherever the process happens to sit, which for
    a provider launch is the agent's own workspace. Dropping those entries is
    what makes the remaining list a statement about the machine rather than
    about the directory a run was given.
    """
    raw = search_path if search_path is not None else os.defpath
    return tuple(
        entry for entry in raw.split(os.pathsep) if entry and os.path.isabs(entry)
    )


def resolve_trusted_executable(
    name: str, *, search_path: str | None = None
) -> str | None:
    """Resolve a launcher name to an absolute path using the SERVICE's own PATH.

    The environment a provider child receives is not a trustworthy place to
    resolve that child's own launcher from: it leads with the agent workspace's
    virtualenv, so a checkout carrying ``.venv/bin/node`` would supply the
    interpreter of the very process meant to supervise it. Resolution therefore
    reads this service's environment, and the result is absolute so no later
    search - POSIX ``execvp``, the Compose identity launcher, or Windows
    ``cmd.exe``, which consults the working directory first - gets a second
    chance to pick a different file.

    The directory is joined onto the name rather than handed to ``shutil.which``
    as a search path: that keeps Windows ``PATHEXT`` expansion while taking the
    implicit current-directory entry which ``which`` prepends on Windows out of
    the decision entirely.

    ``search_path`` names the search path explicitly instead of reading this
    process's own, so a caller (and a test) can state which machine locations are
    trusted rather than arranging an ambient environment to imply it.
    """
    if os.path.dirname(name):
        raise ValueError(f"trusted executable resolution takes a bare name: {name!r}")
    if search_path is None:
        search_path = os.environ.get("PATH")
    for directory in _trusted_search_directories(search_path):
        if resolved := shutil.which(os.path.join(directory, name)):
            return os.path.abspath(resolved)
    return None


def _cli_candidates(name: str, *, windows: bool) -> tuple[str, ...]:
    """Return the filenames one CLI may legitimately be installed under."""
    return (name, f"{name}.cmd", f"{name}.exe") if windows else (name,)


def resolve_provider_cli_executable(
    provider: Provider, *, search_path: str | None = None
) -> str | None:
    """Resolve a provider's system CLI exactly as production will launch it.

    Windows command shims are explicit fallbacks rather than an assumption about
    the caller's ``PATHEXT``. Unix hosts accept only the unsuffixed executable,
    so an unrelated ``.cmd`` file cannot make a lane appear runnable there. The
    search runs over this service's own locations (see
    :func:`resolve_trusted_executable`), never the environment a provider child
    is handed.
    """

    try:
        name = _SYSTEM_CLI_NAMES[provider]
    except KeyError as exc:
        raise ValueError(f"provider {provider.value} has no system CLI") from exc
    for candidate in _cli_candidates(name, windows=sys.platform == "win32"):
        if executable := resolve_trusted_executable(candidate, search_path=search_path):
            return executable
    return None
