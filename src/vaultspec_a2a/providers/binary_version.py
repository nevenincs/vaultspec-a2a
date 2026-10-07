"""Version identity reported by a resolved provider launcher."""

from __future__ import annotations

import os
import re
import subprocess
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from ..control.provider_execution import NativeExecutionRefusedError
from ..utils.process import ProcessContainmentError
from ..workspace.environment import scrub_agent_environment
from ._provider_execution import provider_execution_launch

if TYPE_CHECKING:
    from ..desktop.native_isolation import NativeLaunchAuthority

__all__ = [
    "BinaryVersionProbeError",
    "next_minor_version",
    "parse_binary_version",
    "probe_binary_version",
]

_VERSION = re.compile(r"(?<![\w.])(\d+)\.(\d+)\.(\d+)(?![\w.+-])")
_PROBE_TIMEOUT_SECONDS = 5
_AUTHORITY_UNAVAILABLE = "provider execution authority is unavailable"


class BinaryVersionProbeError(RuntimeError):
    """A launcher's version cannot be established for admission."""


def parse_binary_version(value: str) -> tuple[int, int, int] | None:
    """Read one three-part CLI version from its bounded version report."""
    matches = _VERSION.findall(value)
    if len(matches) != 1:
        return None
    major, minor, patch = matches[0]
    return int(major), int(minor), int(patch)


def next_minor_version(version: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return the first version outside a host PATH proof's minor line."""
    return (version[0], version[1] + 1, 0)


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    if not path.is_file():
        raise BinaryVersionProbeError("provider binary is not a file")
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _launch_identity(path: Path) -> tuple[int, ...]:
    """Include a Scoop shim's current target, which can change behind its EXE."""
    identity = _file_identity(path)
    sidecar = path.with_suffix(".shim")
    if path.suffix.lower() != ".exe" or not sidecar.is_file():
        return identity
    lines = sidecar.read_text(encoding="utf-8-sig").splitlines()
    targets = [
        match.group(1)
        for line in lines
        if (match := re.fullmatch(r'path\s*=\s*"([^"]+)"', line.strip()))
    ]
    if len(targets) != 1 or not Path(targets[0]).is_absolute():
        raise BinaryVersionProbeError("provider launcher target is unavailable")
    return identity + _file_identity(sidecar) + _file_identity(Path(targets[0]))


@cache
def _reported_version(
    executable: str,
    identity: tuple[int, ...],
    native_authority: NativeLaunchAuthority | None,
) -> str | None:
    """Run one launch identity once, including failed reports."""
    del identity
    try:
        launch = provider_execution_launch(
            [executable, "--version"],
            environment=scrub_agent_environment(os.environ),
            cwd=None,
            native_authority=native_authority,
        )
        completed = subprocess.run(
            launch.command,
            env=launch.environment,
            cwd=launch.cwd,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, ValueError, ProcessContainmentError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    reported = f"{completed.stdout}\n{completed.stderr}"
    version = parse_binary_version(reported)
    return ".".join(map(str, version)) if version is not None else None


def probe_binary_version(
    executable: Path | str, *, native_authority: NativeLaunchAuthority | None = None
) -> str:
    """Return a resolved launcher's version or refuse an unverifiable identity.

    The path and file stat are the launch identity. A Scoop shim also includes
    its sidecar and current target, since the EXE itself stays unchanged across
    package updates. A changed identity is probed again.

    The launch boundary is consulted on every call, so a cached version never
    outlives a later refusal; its profile refusal keeps its own safe reason.
    """
    path = Path(executable)
    if not path.is_absolute():
        raise BinaryVersionProbeError("provider binary path is not absolute")
    try:
        identity = _launch_identity(path)
    except (OSError, UnicodeError) as exc:
        raise BinaryVersionProbeError("provider binary is unavailable") from exc
    try:
        provider_execution_launch(
            [str(path), "--version"],
            environment=scrub_agent_environment(os.environ),
            cwd=None,
            native_authority=native_authority,
        )
    except NativeExecutionRefusedError as exc:
        # Other containment refusals can name configured launcher paths, so only
        # the profile refusal's own sentence is carried through.
        raise BinaryVersionProbeError(str(exc)) from exc
    except (OSError, ValueError, ProcessContainmentError) as exc:
        raise BinaryVersionProbeError(_AUTHORITY_UNAVAILABLE) from exc
    result = _reported_version(str(path), identity, native_authority)
    if result is None:
        raise BinaryVersionProbeError("provider binary version is unavailable")
    return result
