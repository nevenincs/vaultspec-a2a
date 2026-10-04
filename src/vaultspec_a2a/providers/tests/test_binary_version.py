"""Real launcher processes establish and refresh provider version identity."""

from __future__ import annotations

import os
import shlex
from typing import TYPE_CHECKING

import pytest

from ..binary_version import (
    BinaryVersionProbeError,
    _launch_identity,
    parse_binary_version,
    probe_binary_version,
)

if TYPE_CHECKING:
    from pathlib import Path


def _launcher(path: Path, count: Path, version: str) -> None:
    if os.name == "nt":
        path.write_text(
            f'@echo off\r\necho probe>>"{count}"\r\necho codex-cli {version}\r\n',
            encoding="utf-8",
        )
    else:
        path.write_text(
            f"#!/bin/sh\necho probe >> {shlex.quote(str(count))}\n"
            f"echo codex-cli {version}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)


def test_real_launcher_version_is_cached_until_file_changes(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / ("version.cmd" if os.name == "nt" else "version")
    count = tmp_path / "probes.txt"
    _launcher(launcher, count, "0.159.2")

    assert probe_binary_version(launcher) == "0.159.2"
    assert probe_binary_version(launcher) == "0.159.2"
    assert count.read_text(encoding="utf-8").splitlines() == ["probe"]

    previous = launcher.stat()
    _launcher(launcher, count, "0.159.3")
    os.utime(
        launcher,
        ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000),
    )
    assert probe_binary_version(launcher) == "0.159.3"
    assert count.read_text(encoding="utf-8").splitlines() == ["probe", "probe"]


def test_missing_or_malformed_launcher_version_is_refused(tmp_path: Path) -> None:
    launcher = tmp_path / ("version.cmd" if os.name == "nt" else "version")
    with pytest.raises(BinaryVersionProbeError, match="unavailable"):
        probe_binary_version(launcher)
    _launcher(launcher, tmp_path / "probes.txt", "not-a-version")
    with pytest.raises(BinaryVersionProbeError, match="version is unavailable"):
        probe_binary_version(launcher)
    assert parse_binary_version("codex-cli 0.159.2 and 0.160.0") is None


def test_shim_identity_tracks_current_target(tmp_path: Path) -> None:
    launcher = tmp_path / "codex.exe"
    launcher.write_bytes(b"shim")
    target = tmp_path / "codex-target.exe"
    target.write_bytes(b"old target")
    launcher.with_suffix(".shim").write_text(f'path = "{target}"\n', encoding="utf-8")
    before = _launch_identity(launcher)
    target.write_bytes(b"new target content")
    assert _launch_identity(launcher) != before
