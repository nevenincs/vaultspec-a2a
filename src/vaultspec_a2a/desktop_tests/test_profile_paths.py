"""Certify desktop state stays app-home-seated across launch and capsule moves.

Real-artifact gate: it builds a real application home and a real capsule tree on
disk, constructs the production ``Settings`` through its established environment
seam, and changes the real working directory and the capsule location to prove
that mutable-state derivation is anchored to the explicit application home rather
than the launch directory. No mock, monkeypatch, stub, skip, or expected failure
is used; the working directory is always restored in a ``finally``.

Capsule realism: the desktop profile validates the capsule's installed-runtime
assets — the bundled Node executable and the ACP adapter entry the provider
factory resolves. Those exact files are written on disk here through the factory's
own path authorities. A full base closure with real CPython, Node.js, and ACP
archives requires network downloads and belongs to the target-capsule build and
verifier gates; this gate certifies path seating, not artifact bytes.
"""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ..control.config import Settings
from ..desktop.profile import (
    DesktopProfile,
    DesktopProfileError,
    derive_state_paths,
)
from ..providers.factory import (
    capsule_acp_entry,
    capsule_node_executable,
)
from ..testing import armed_environment

if TYPE_CHECKING:
    from collections.abc import Iterator

_APP_HOME_ENV = "VAULTSPEC_DESKTOP_APP_HOME"
_CAPSULE_ENV = "VAULTSPEC_CAPSULE_ASSETS"


def _build_capsule(root: Path) -> Path:
    """Write the factory-resolved runtime assets into a real capsule tree."""
    for asset, content in (
        (capsule_node_executable(root), "node runtime\n"),
        (capsule_acp_entry(root), "// acp entry\n"),
    ):
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(content, encoding="utf-8")
    return root


@contextmanager
def _armed_env(app_home: str, capsule_root: str) -> Iterator[None]:
    """Arm the desktop environment variables, restoring the prior values after."""
    with armed_environment(**{_APP_HOME_ENV: app_home, _CAPSULE_ENV: capsule_root}):
        yield


@contextmanager
def _working_directory(target: Path) -> Iterator[None]:
    """Change the process working directory, always restoring the origin."""
    origin = Path.cwd()
    os.chdir(target)
    try:
        yield
    finally:
        os.chdir(origin)


def test_armed_state_is_invariant_under_launch_directory_changes(
    tmp_path: Path,
) -> None:
    """Armed mutable paths stay app-home-seated regardless of the launch dir."""
    app_home = tmp_path / "app"
    capsule = _build_capsule(tmp_path / "capsule")
    state = derive_state_paths(app_home)
    launch_a = tmp_path / "launch-a"
    launch_b = tmp_path / "launch-b"
    launch_a.mkdir()
    launch_b.mkdir()

    with _armed_env(str(app_home), str(capsule)):
        with _working_directory(launch_a):
            from_a = Settings()
        with _working_directory(launch_b):
            from_b = Settings()

    assert from_a.database_path == state.database_path
    assert from_b.database_path == state.database_path
    assert from_a.checkpoint_path == from_b.checkpoint_path == state.checkpoint_path
    assert from_a.workspace_root == from_b.workspace_root == state.workspaces_root
    assert from_a.a2a_home == from_b.a2a_home == app_home
    assert from_a.database_path.is_relative_to(app_home)
    assert not from_a.database_path.is_relative_to(launch_a)


def test_state_is_invariant_under_capsule_relocation(tmp_path: Path) -> None:
    """Relocating the immutable capsule leaves the mutable-state layout unchanged."""
    app_home = tmp_path / "app"
    origin_capsule = _build_capsule(tmp_path / "capsule-origin")

    before = DesktopProfile.resolve(app_home, origin_capsule)

    relocated_capsule = tmp_path / "capsule-moved"
    shutil.move(str(origin_capsule), str(relocated_capsule))

    after = DesktopProfile.resolve(app_home, relocated_capsule)

    assert after.state == before.state
    assert after.capsule_assets_root == relocated_capsule
    assert after.capsule_assets_root != before.capsule_assets_root


def test_relative_app_home_is_refused_when_armed(tmp_path: Path) -> None:
    """A launch-directory-relative application home is refused when arming."""
    capsule = _build_capsule(tmp_path / "capsule")

    with pytest.raises(DesktopProfileError, match="absolute"):
        DesktopProfile.resolve(Path("relative/app"), capsule)

    with (
        _armed_env("relative/app", str(capsule)),
        pytest.raises(ValidationError, match="absolute"),
    ):
        Settings()


def test_a_launch_relative_database_url_is_refused(tmp_path: Path) -> None:
    """A relative database URL is rejected rather than resolved per launch dir.

    This asserted the opposite: that an unarmed profile KEPT its launch-relative
    form, and that the same URL read from two directories yielded two different
    files. That behaviour is exactly the hazard the settings validator now
    refuses - the gateway and the CLI resolve against their own working
    directories, so one relative URL silently becomes two databases and each
    process is certain it holds the only one.

    The refusal is the contract now, so the drift the old test pinned as
    expected is what this one proves impossible. Both launch directories are
    still exercised, because the defect only ever showed itself as a difference
    between two of them.
    """
    launch_a = tmp_path / "launch-a"
    launch_b = tmp_path / "launch-b"
    launch_a.mkdir()
    launch_b.mkdir()

    for launch in (launch_a, launch_b):
        with _working_directory(launch), pytest.raises(ValidationError) as raised:
            Settings(database_url="sqlite+aiosqlite:///vaultspec.db")
        assert "must be absolute" in str(raised.value)


def test_discovery_path_matches_the_discovery_authority(tmp_path: Path) -> None:
    """The profile's discovery path mirrors the lifecycle discovery authority.

    ``derive_state_paths`` uses a leaf filename constant to stay importable during
    settings construction; this guard keeps that constant in sync with the
    canonical ``service_json_path`` placement so the two never drift.
    """
    from ..lifecycle.discovery import service_json_path

    home = (tmp_path / "app-home").resolve()
    assert derive_state_paths(home).discovery_path == service_json_path(home)
