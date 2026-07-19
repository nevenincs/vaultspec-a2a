"""Real-seam tests for capsule-owned Node and ACP adapter resolution.

Exercises the production ``_classify_acp_command`` seam with a real temporary
capsule layout on disk. No mocks, monkeypatches, or settings mutation: the
capsule assets root is passed explicitly, which is the same seam the desktop
profile will bind through ``settings.capsule_assets_root``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ...thread.errors import ConfigError
from ..factory import _CLAUDE_ACP_JS, _classify_acp_command, settings

if TYPE_CHECKING:
    from pathlib import Path


def _capsule_node_path(root: Path) -> Path:
    """The capsule Node executable path for this platform (documented layout)."""
    if os.name == "nt":
        return root / "node" / "node.exe"
    return root / "node" / "bin" / "node"


def _capsule_acp_path(root: Path) -> Path:
    """The capsule Claude ACP entry point path (documented layout)."""
    return (
        root
        / "node_modules"
        / "@agentclientprotocol"
        / "claude-agent-acp"
        / "dist"
        / "index.js"
    )


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_capsule_root_resolves_node_and_acp_only_from_capsule(tmp_path: Path) -> None:
    """An explicit capsule root binds the capsule Node executable and ACP entry."""
    root = tmp_path / "capsule"
    node = _write(_capsule_node_path(root), "#!/bin/sh\n")
    acp = _write(_capsule_acp_path(root), "// acp entry\n")

    command, meta = _classify_acp_command("node", capsule_assets_root=root)

    assert command == [str(node), str(acp)]
    # The executable is the explicit capsule binary, never a bare PATH ``node``.
    assert command[0] == str(node)
    assert meta["runtime_authority"] == "capsule"
    assert meta["command_origin"] == "capsule"
    assert meta["command_kind"] == "node_entry"
    assert meta["command_target"] == str(acp)
    assert meta["command_executable"] == node.name
    assert meta["acp_backend"] == "node"


def test_capsule_missing_node_fails_loud_naming_the_asset(tmp_path: Path) -> None:
    """A capsule without its Node executable raises, naming the missing path."""
    root = tmp_path / "capsule"
    _write(_capsule_acp_path(root), "// acp entry\n")

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=root)

    message = str(excinfo.value)
    assert "Node executable" in message
    assert str(_capsule_node_path(root)) in message


def test_capsule_missing_acp_entry_fails_loud_naming_the_asset(tmp_path: Path) -> None:
    """A capsule without its ACP adapter raises, naming the missing path."""
    root = tmp_path / "capsule"
    _write(_capsule_node_path(root), "#!/bin/sh\n")

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=root)

    message = str(excinfo.value)
    assert "ACP entry point" in message
    assert str(_capsule_acp_path(root)) in message


def test_capsule_resolution_takes_no_path_or_checkout_fallback(tmp_path: Path) -> None:
    """With a capsule root in force, an empty capsule never falls back."""
    root = tmp_path / "empty-capsule"
    root.mkdir()

    with pytest.raises(ConfigError):
        _classify_acp_command("node", capsule_assets_root=root)


def test_node_backend_without_capsule_is_unchanged() -> None:
    """Without a capsule root the Node backend keeps checkout-relative behavior."""
    assert settings.capsule_assets_root is None

    if not _CLAUDE_ACP_JS.exists():
        with pytest.raises(ConfigError):
            _classify_acp_command("node")
        return

    command, meta = _classify_acp_command("node")
    assert command == ["node", str(_CLAUDE_ACP_JS)]
    assert meta["runtime_authority"] == "project_local"
    assert meta["command_origin"] == "project_node_modules_entry"
