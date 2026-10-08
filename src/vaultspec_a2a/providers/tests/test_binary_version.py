"""Real launcher processes establish and refresh provider version identity."""

from __future__ import annotations

import os
import shlex
from typing import TYPE_CHECKING

import pytest

from ..binary_version import (
    BinaryVersionProbeError,
    _launch_identity,
    binary_version_text,
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
    initial_version = "1.2.3"
    updated_version = "1.2.4"
    _launcher(launcher, count, initial_version)

    assert probe_binary_version(launcher) == initial_version
    assert probe_binary_version(launcher) == initial_version
    assert count.read_text(encoding="utf-8").splitlines() == ["probe"]

    previous = launcher.stat()
    _launcher(launcher, count, updated_version)
    os.utime(
        launcher,
        ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000),
    )
    assert probe_binary_version(launcher) == updated_version
    assert count.read_text(encoding="utf-8").splitlines() == ["probe", "probe"]


def test_missing_or_malformed_launcher_version_is_refused(tmp_path: Path) -> None:
    launcher = tmp_path / ("version.cmd" if os.name == "nt" else "version")
    with pytest.raises(BinaryVersionProbeError, match="unavailable"):
        probe_binary_version(launcher)
    _launcher(launcher, tmp_path / "probes.txt", "not-a-version")
    with pytest.raises(BinaryVersionProbeError, match="version is unavailable"):
        probe_binary_version(launcher)
    assert parse_binary_version("probe-cli 1.2.3 and 2.3.4") is None
    assert binary_version_text("probe-cli 1.2.3 and 2.3.4") is None


def test_version_report_is_read_in_dotted_form() -> None:
    assert binary_version_text("codex-cli 1.2.3\n") == "1.2.3"
    assert binary_version_text("no version here") is None


def test_a_bare_version_string_with_nothing_else_is_parsed() -> None:
    """A launcher that reports only the bare number, with or without a newline."""
    assert binary_version_text("1.2.3") == "1.2.3"
    assert binary_version_text("1.2.3\n") == "1.2.3"


def test_a_click_style_version_banner_is_parsed() -> None:
    """``click``'s own ``--version`` banner shape: ``"{prog}, version {ver}"``.

    ``vaultspec-core`` is itself a click CLI, so its ``--version`` report takes
    this exact shape - the one :func:`cli.provision._resolved_version` reads
    through this same shared parser.
    """
    assert binary_version_text("vaultspec-core, version 1.2.3\n") == "1.2.3"


def test_a_report_with_no_version_number_at_all_is_refused() -> None:
    """A launcher that does not understand ``--version`` prints help, not a version."""
    banner = (
        "Usage: probe-cli [OPTIONS] COMMAND [ARGS]...\n\n"
        "  Manage the probe toolchain.\n\n"
        "Options:\n  --help  Show this message and exit.\n"
    )
    assert parse_binary_version(banner) is None
    assert binary_version_text(banner) is None


def test_shim_identity_tracks_current_target(tmp_path: Path) -> None:
    launcher = tmp_path / "codex.exe"
    launcher.write_bytes(b"shim")
    target = tmp_path / "codex-target.exe"
    target.write_bytes(b"old target")
    launcher.with_suffix(".shim").write_text(f'path = "{target}"\n', encoding="utf-8")
    before = _launch_identity(launcher)
    target.write_bytes(b"new target content")
    assert _launch_identity(launcher) != before
