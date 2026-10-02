"""Canonical platform-aware resolution for provider-owned system CLIs."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from ..control.config import settings
from ..graph.enums import Provider
from ..thread.errors import ConfigError

__all__ = [
    "CLAUDE_EXECUTABLE_ENV",
    "ClaudeCliResolution",
    "ProviderRuntimeUnavailableError",
    "ProviderRuntimeUnavailableReason",
    "pin_claude_executable",
    "resolve_provider_cli_executable",
    "resolve_service_executable",
]

# The Claude ACP adapter's own setting for which CLI it drives. Named here
# because this module is where the answer is resolved, and both the lanes that
# need one - a served turn and a catalog probe - take it from here.
CLAUDE_EXECUTABLE_ENV = "CLAUDE_CODE_EXECUTABLE"

ClaudeCliAuthority = Literal[
    "explicit_setting", "capsule", "child_environment", "service_path", "lock_vendored"
]


@dataclass(frozen=True)
class ClaudeCliResolution:
    path: Path
    authority: ClaudeCliAuthority


class ProviderRuntimeUnavailableReason(StrEnum):
    CLAUDE_CLI_UNAVAILABLE = "claude_cli_unavailable"
    BINARY_VERSION_UNAVAILABLE = "binary_version_unavailable"
    BINARY_OUT_OF_PROOF_RANGE = "binary_out_of_proof_range"


class ProviderRuntimeUnavailableError(ConfigError):
    """A structurally valid provider lane has no usable runtime asset."""

    def __init__(
        self,
        message: str,
        *,
        reason: ProviderRuntimeUnavailableReason | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason


_SYSTEM_CLI_NAMES: dict[Provider, str] = {
    Provider.CLAUDE: "claude",
    Provider.CODEX: "codex",
    Provider.KIMI: "kimi",
}


def _absolute_search_directories(search_path: str | None) -> tuple[str, ...]:
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


def resolve_service_executable(
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
        # The service's OWN search path, read as the machine fact it is rather
        # than as configuration: a settings field would declare a second, quieter
        # answer to "where is this host's software installed", and the value that
        # must not be consulted here - a provider child's environment - is
        # excluded by reading this process's rather than by naming a setting.
        search_path = os.environ.get("PATH")  # storage-anchor-ok
    for directory in _absolute_search_directories(search_path):
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
    :func:`resolve_service_executable`), never the environment a provider child
    is handed.
    """

    try:
        name = _SYSTEM_CLI_NAMES[provider]
    except KeyError as exc:
        raise ValueError(f"provider {provider.value} has no system CLI") from exc
    for candidate in _cli_candidates(name, windows=sys.platform == "win32"):
        if executable := resolve_service_executable(candidate, search_path=search_path):
            return executable
    return None


def _resolved_cli_file(path: Path, *, authority: ClaudeCliAuthority) -> Path:
    """Validate an authority's exact file before giving it to the adapter."""
    if not path.is_absolute():
        raise ConfigError(f"Claude CLI {authority} path must be absolute: {path}")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ConfigError(
            f"Claude CLI {authority} path is unavailable: {path}"
        ) from exc
    if not resolved.is_file():
        raise ConfigError(f"Claude CLI {authority} path is not a file: {resolved}")
    return resolved


def pin_claude_executable(env: dict[str, str]) -> ClaudeCliResolution:
    """Pin one absolute Claude CLI path by the profile's authority order."""
    from ._factory_commands import capsule_claude_executable

    explicit = settings.claude_cli_executable
    capsule_root = settings.capsule_assets_root
    try:
        if explicit is not None:
            authority: ClaudeCliAuthority = "explicit_setting"
            candidate = explicit
        elif capsule_root is not None:
            authority = "capsule"
            candidate = capsule_claude_executable(capsule_root)
        elif inherited := env.get(CLAUDE_EXECUTABLE_ENV):
            authority = "child_environment"
            candidate = Path(inherited)
        elif installed := resolve_provider_cli_executable(Provider.CLAUDE):
            authority = "service_path"
            candidate = Path(installed)
        else:
            authority = "lock_vendored"
            candidate = capsule_claude_executable(settings.install_root)

        path = _resolved_cli_file(candidate, authority=authority)
        if capsule_root is not None and authority == "capsule":
            try:
                root = capsule_root.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ConfigError(
                    f"Claude CLI capsule assets root is unavailable: {capsule_root}"
                ) from exc
            if not path.is_relative_to(root):
                raise ConfigError(
                    f"Claude CLI capsule asset escapes its root: {candidate}"
                )
    except ConfigError as exc:
        raise ProviderRuntimeUnavailableError(
            str(exc), reason=ProviderRuntimeUnavailableReason.CLAUDE_CLI_UNAVAILABLE
        ) from exc
    env[CLAUDE_EXECUTABLE_ENV] = str(path)
    return ClaudeCliResolution(path=path, authority=authority)
