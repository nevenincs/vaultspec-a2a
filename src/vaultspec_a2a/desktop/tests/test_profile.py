"""Real-directory tests for the desktop profile roots and derived state paths.

No mocks, monkeypatches, or duplicated layout policy: capsule assets are built
through the provider factory's own path authorities, and the profile is exercised
against real temporary directories on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ...providers.factory import _capsule_acp_entry, _capsule_node_executable
from ..profile import (
    DesktopProfile,
    DesktopProfileError,
    DesktopStatePaths,
    derive_state_paths,
)


def _build_capsule(root: Path) -> Path:
    """Materialise a minimal but real capsule tree at ``root``.

    Writes the two runtime assets the provider factory resolves — the bundled
    Node executable and the ACP adapter entry — at their production-owned paths.
    """
    node = _capsule_node_executable(root)
    acp = _capsule_acp_entry(root)
    for asset, content in ((node, "node runtime\n"), (acp, "// acp entry\n")):
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text(content, encoding="utf-8")
    return root


def test_derive_state_paths_are_absolute_and_seated_under_app_home(
    tmp_path: Path,
) -> None:
    """Every derived mutable path is absolute and nested under the app home."""
    app_home = tmp_path / "app"
    state = derive_state_paths(app_home)

    assert isinstance(state, DesktopStatePaths)
    assert state.app_home == app_home
    for path in (
        state.database_path,
        state.checkpoint_path,
        state.logs_dir,
        state.discovery_path,
        state.workspaces_root,
        state.credentials_dir,
        state.receipts_dir,
        state.temp_homes_dir,
        state.snapshots_dir,
    ):
        assert path.is_absolute()
        assert path.is_relative_to(app_home)

    # Database and checkpoint are distinct files under the same state directory.
    assert state.database_path != state.checkpoint_path
    assert state.database_path.parent == state.checkpoint_path.parent

    # Seated paths mirror the operative a2a_home conventions: runtime logs and the
    # discovery service.json at the application-home root.
    assert state.logs_dir == app_home / "runtime"
    assert state.discovery_path == app_home / "service.json"


def test_derive_state_paths_rejects_relative_app_home() -> None:
    """A launch-directory-relative app home is refused fail-closed."""
    with pytest.raises(DesktopProfileError, match="absolute"):
        derive_state_paths(Path("relative/app-home"))


def test_resolve_binds_valid_roots_and_exposes_capsule_assets_root(
    tmp_path: Path,
) -> None:
    """A valid app home and capsule resolve, and capsule assets bind to the root."""
    app_home = tmp_path / "app"
    capsule = _build_capsule(tmp_path / "capsule")

    profile = DesktopProfile.resolve(app_home, capsule)

    assert profile.app_home == app_home
    assert profile.capsule_root == capsule
    assert profile.capsule_assets_root == capsule
    assert profile.state.database_path == derive_state_paths(app_home).database_path


def test_resolve_rejects_relative_capsule_root(tmp_path: Path) -> None:
    """A relative capsule root is refused before any asset probe."""
    with pytest.raises(DesktopProfileError, match="absolute"):
        DesktopProfile.resolve(tmp_path / "app", Path("relative/capsule"))


def test_resolve_rejects_missing_capsule_directory(tmp_path: Path) -> None:
    """A capsule root that does not exist is refused with an actionable message."""
    with pytest.raises(DesktopProfileError, match="not a directory"):
        DesktopProfile.resolve(tmp_path / "app", tmp_path / "absent-capsule")


def test_resolve_rejects_capsule_missing_runtime_assets(tmp_path: Path) -> None:
    """A capsule directory without its bundled Node/ACP assets is refused."""
    empty_capsule = tmp_path / "capsule"
    empty_capsule.mkdir()
    with pytest.raises(DesktopProfileError, match=r"Node\.js runtime executable"):
        DesktopProfile.resolve(tmp_path / "app", empty_capsule)


def test_resolve_rejects_capsule_missing_acp_entry(tmp_path: Path) -> None:
    """A capsule with Node but no ACP adapter entry is refused, naming the gap."""
    capsule = tmp_path / "capsule"
    node = _capsule_node_executable(capsule)
    node.parent.mkdir(parents=True, exist_ok=True)
    node.write_text("node runtime\n", encoding="utf-8")
    with pytest.raises(DesktopProfileError, match="ACP adapter entry point"):
        DesktopProfile.resolve(tmp_path / "app", capsule)


def test_resolve_rejects_nested_roots(tmp_path: Path) -> None:
    """Mutable state nested inside the immutable capsule is refused."""
    capsule = _build_capsule(tmp_path / "capsule")
    nested_home = capsule / "state"
    with pytest.raises(DesktopProfileError, match="distinct and non-nested"):
        DesktopProfile.resolve(nested_home, capsule)


def test_resolve_rejects_uncreatable_app_home(tmp_path: Path) -> None:
    """An app home whose ancestor is a file (not a directory) is refused."""
    capsule = _build_capsule(tmp_path / "capsule")
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file\n", encoding="utf-8")
    blocked_home = blocker / "app"
    with pytest.raises(DesktopProfileError, match="non-directory"):
        DesktopProfile.resolve(blocked_home, capsule)


def test_resolve_accepts_creatable_but_absent_app_home(tmp_path: Path) -> None:
    """An absent app home under a writable ancestor validates as creatable."""
    capsule = _build_capsule(tmp_path / "capsule")
    absent_home = tmp_path / "does-not-exist-yet" / "app"

    profile = DesktopProfile.resolve(absent_home, capsule)

    assert not absent_home.exists()
    assert profile.app_home == absent_home


def test_ensure_materialises_only_provisioned_directories(tmp_path: Path) -> None:
    """``ensure`` creates the consumed directories and leaves reserved ones alone."""
    capsule = _build_capsule(tmp_path / "capsule")
    profile = DesktopProfile.resolve(tmp_path / "app", capsule)
    state = profile.state

    profile.ensure()
    profile.ensure()  # idempotent second pass must not raise.

    for directory in state.provisioned_directories:
        assert directory.is_dir()

    # Reserved directories have no consumer yet and must not be seeded empty.
    for reserved in (
        state.credentials_dir,
        state.receipts_dir,
        state.temp_homes_dir,
        state.snapshots_dir,
    ):
        assert not reserved.exists()

    # Discovery is a file written by the discovery authority, never pre-created.
    assert not state.discovery_path.exists()
