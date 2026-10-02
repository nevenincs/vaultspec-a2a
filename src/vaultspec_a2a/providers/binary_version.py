"""Version identity reported by a resolved provider launcher."""

from __future__ import annotations

import re
import subprocess
from functools import cache
from pathlib import Path

__all__ = [
    "BinaryVersionProbeError",
    "next_minor_version",
    "parse_binary_version",
    "probe_binary_version",
]

_VERSION = re.compile(r"(?<![\w.])(\d+)\.(\d+)\.(\d+)(?![\w.+-])")
_PROBE_TIMEOUT_SECONDS = 5


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
def _reported_version(executable: str, identity: tuple[int, ...]) -> str | None:
    """Run one launch identity once, including failed reports."""
    del identity
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    reported = f"{completed.stdout}\n{completed.stderr}"
    version = parse_binary_version(reported)
    return ".".join(map(str, version)) if version is not None else None


def probe_binary_version(executable: Path | str) -> str:
    """Return a resolved launcher's version or refuse an unverifiable identity.

    The path and file stat are the launch identity. A Scoop shim also includes
    its sidecar and current target, since the EXE itself stays unchanged across
    package updates. A changed identity is probed again.
    """
    path = Path(executable)
    if not path.is_absolute():
        raise BinaryVersionProbeError("provider binary path is not absolute")
    try:
        identity = _launch_identity(path)
    except (OSError, UnicodeError) as exc:
        raise BinaryVersionProbeError("provider binary is unavailable") from exc
    result = _reported_version(str(path), identity)
    if result is None:
        raise BinaryVersionProbeError("provider binary version is unavailable")
    return result
