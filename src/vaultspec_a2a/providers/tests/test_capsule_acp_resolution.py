"""Real-seam tests for capsule-owned Node and ACP adapter resolution.

Exercises the production ``_classify_acp_command`` seam with real capsule layouts
on disk. No mocks, monkeypatches, settings mutation, or duplicated layout policy:
tests construct assets through the production-owned path authorities.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import pytest

from ...thread.errors import ConfigError
from ..factory import (
    _CLAUDE_ACP_JS,
    _capsule_acp_entry,
    _capsule_node_executable,
    _classify_acp_command,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_capsule_root_resolves_node_and_acp_only_from_capsule(tmp_path: Path) -> None:
    """An explicit capsule root binds the capsule Node executable and ACP entry."""
    root = tmp_path / "capsule"
    node = _write(_capsule_node_executable(root), "node runtime\n")
    acp = _write(_capsule_acp_entry(root), "// acp entry\n")

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
    _write(_capsule_acp_entry(root), "// acp entry\n")

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=root)

    message = str(excinfo.value)
    assert "Node executable" in message
    assert str(_capsule_node_executable(root.resolve())) in message


def test_capsule_missing_acp_entry_fails_loud_naming_the_asset(tmp_path: Path) -> None:
    """A capsule without its ACP adapter raises, naming the missing path."""
    root = tmp_path / "capsule"
    _write(_capsule_node_executable(root), "node runtime\n")

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=root)

    message = str(excinfo.value)
    assert "ACP entry point" in message
    assert str(_capsule_acp_entry(root.resolve())) in message


def test_capsule_resolution_takes_no_path_or_checkout_fallback(tmp_path: Path) -> None:
    """With a capsule root in force, an empty capsule never falls back."""
    root = tmp_path / "empty-capsule"
    root.mkdir()

    with pytest.raises(ConfigError):
        _classify_acp_command("node", capsule_assets_root=root)


def test_unresolvable_user_root_has_stable_config_error() -> None:
    """User expansion and strict resolution failures share the public error type."""
    unknown_user_root = Path("~vaultspec-user-that-must-not-exist/capsule")

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=unknown_user_root)

    assert "Desktop capsule assets root cannot be resolved" in str(excinfo.value)
    assert str(unknown_user_root) in str(excinfo.value)


def test_relative_capsule_root_returns_absolute_canonical_assets() -> None:
    """A relative capsule root becomes one absolute canonical authority."""
    with TemporaryDirectory(prefix="capsule-s09-", dir=Path.cwd()) as temp_dir:
        root = Path(temp_dir)
        relative_root = root.relative_to(Path.cwd())
        node = _write(_capsule_node_executable(root), "node runtime\n")
        acp = _write(_capsule_acp_entry(root), "// acp entry\n")

        command, meta = _classify_acp_command("node", capsule_assets_root=relative_root)

        assert command == [str(node.resolve()), str(acp.resolve())]
        assert all(Path(part).is_absolute() for part in command)
        assert meta["command_target"] == str(acp.resolve())


@pytest.mark.parametrize(
    ("asset_path", "asset_name"),
    [
        pytest.param(_capsule_node_executable, "Node executable", id="node"),
        pytest.param(_capsule_acp_entry, "Claude ACP entry point", id="acp"),
    ],
)
def test_capsule_rejects_asset_symlink_that_escapes_root(
    tmp_path: Path,
    asset_path: Callable[[Path], Path],
    asset_name: str,
) -> None:
    """A required asset cannot transfer authority through an escaping link."""
    root = tmp_path / "capsule"
    _write(_capsule_node_executable(root), "node runtime\n")
    _write(_capsule_acp_entry(root), "// acp entry\n")
    escaped_asset = asset_path(root)
    escaped_asset.unlink()
    outside_asset = _write(
        tmp_path / "outside" / escaped_asset.name,
        "outside capsule authority\n",
    )
    escaped_asset.symlink_to(outside_asset)

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=root)

    message = str(excinfo.value)
    assert asset_name in message
    assert "escapes its assets root" in message
    assert str(escaped_asset) in message
    assert str(outside_asset.resolve()) in message


def test_explicit_none_forces_project_resolution_despite_configured_root(
    tmp_path: Path,
) -> None:
    """Explicit None bypasses configured capsule resolution in a clean process."""
    configured_root = tmp_path / "configured-capsule"
    configured_root.mkdir()
    repository_root = Path(__file__).resolve().parents[4]
    source_root = repository_root / "src"
    script = f"""
import json
import sys
sys.path.insert(0, {str(source_root)!r})
from vaultspec_a2a.providers.factory import _classify_acp_command, settings
from vaultspec_a2a.thread.errors import ConfigError

try:
    _classify_acp_command("node")
except ConfigError as error:
    omitted = {{"status": "error", "message": str(error)}}
else:
    omitted = {{"status": "resolved"}}

command, metadata = _classify_acp_command("node", capsule_assets_root=None)
print(json.dumps({{
    "configured_root": str(settings.capsule_assets_root),
    "omitted": omitted,
    "explicit_none": {{"command": command, "metadata": metadata}},
}}))
"""
    env = os.environ.copy()
    env["VAULTSPEC_CAPSULE_ASSETS"] = str(configured_root)
    env["VAULTSPEC_PROJECT_ROOT"] = str(repository_root)

    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=repository_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["configured_root"] == str(configured_root)
    assert report["omitted"]["status"] == "error"
    assert str(configured_root) in report["omitted"]["message"]
    assert report["explicit_none"]["command"] == ["node", str(_CLAUDE_ACP_JS)]
    assert report["explicit_none"]["metadata"]["runtime_authority"] == "project_local"
    assert report["explicit_none"]["metadata"]["command_origin"] == (
        "project_node_modules_entry"
    )


def test_explicit_none_keeps_project_backend_behavior() -> None:
    """Explicit None selects the existing Compose/project-local classifier."""
    command, meta = _classify_acp_command("node", capsule_assets_root=None)
    assert command == ["node", str(_CLAUDE_ACP_JS)]
    assert meta["runtime_authority"] == "project_local"
    assert meta["command_origin"] == "project_node_modules_entry"
