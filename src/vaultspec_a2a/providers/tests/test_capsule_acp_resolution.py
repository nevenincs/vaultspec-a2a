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

from ...testing import inherited_environment, session_scratch_dir
from ...thread.errors import ConfigError
from .._factory_commands import (
    _classify_acp_command,
    capsule_acp_entry,
    capsule_claude_executable,
    capsule_node_executable,
    claude_acp_entry,
)
from ..cli_resolution import resolve_service_executable
from ..execution_modes import NODE_BACKEND

if TYPE_CHECKING:
    from collections.abc import Callable


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_capsule_cli_authority_names_the_vendored_binary(
    installed_acp_adapter: Path,
) -> None:
    """The capsule path authority points at a runnable CLI in the npm closure."""
    assert installed_acp_adapter.is_dir()
    install_root = Path(__file__).resolve().parents[4]
    binary = capsule_claude_executable(install_root)

    assert binary.is_file()
    assert binary.is_relative_to(install_root / "node_modules" / "@anthropic-ai")
    result = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_capsule_root_resolves_node_and_acp_only_from_capsule(tmp_path: Path) -> None:
    """An explicit capsule root binds the capsule Node executable and ACP entry."""
    root = tmp_path / "capsule"
    node = _write(capsule_node_executable(root), "node runtime\n")
    acp = _write(capsule_acp_entry(root), "// acp entry\n")

    command = _classify_acp_command("node", capsule_assets_root=root)

    assert command.argv == (str(node), str(acp))
    # The executable is the explicit capsule binary, never a bare PATH ``node``.
    assert command.argv[0] == str(node)
    assert command.runtime_authority == "capsule"
    assert command.command_origin == "capsule"
    assert command.command_kind == "node_entry"
    assert command.command_target == str(acp)
    assert command.command_executable == node.name
    assert command.acp_backend == NODE_BACKEND


def test_capsule_missing_node_fails_loud_naming_the_asset(tmp_path: Path) -> None:
    """A capsule without its Node executable raises, naming the missing path."""
    root = tmp_path / "capsule"
    _write(capsule_acp_entry(root), "// acp entry\n")

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=root)

    message = str(excinfo.value)
    assert "Node executable" in message
    assert str(capsule_node_executable(root.resolve())) in message


def test_capsule_missing_acp_entry_fails_loud_naming_the_asset(tmp_path: Path) -> None:
    """A capsule without its ACP adapter raises, naming the missing path."""
    root = tmp_path / "capsule"
    _write(capsule_node_executable(root), "node runtime\n")

    with pytest.raises(ConfigError) as excinfo:
        _classify_acp_command("node", capsule_assets_root=root)

    message = str(excinfo.value)
    assert "ACP entry point" in message
    assert str(capsule_acp_entry(root.resolve())) in message


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
    with TemporaryDirectory(
        prefix="capsule-root-", dir=session_scratch_dir("capsule-")
    ) as temp_dir:
        root = Path(temp_dir)
        relative_root = Path(os.path.relpath(root, Path.cwd()))
        node = _write(capsule_node_executable(root), "node runtime\n")
        acp = _write(capsule_acp_entry(root), "// acp entry\n")

        command = _classify_acp_command("node", capsule_assets_root=relative_root)

        assert command.argv == (str(node.resolve()), str(acp.resolve()))
        assert all(Path(part).is_absolute() for part in command.argv)
        assert command.command_target == str(acp.resolve())


@pytest.mark.parametrize(
    ("asset_path", "asset_name"),
    [
        pytest.param(capsule_node_executable, "Node executable", id="node"),
        pytest.param(capsule_acp_entry, "Claude ACP entry point", id="acp"),
    ],
)
def test_capsule_rejects_asset_symlink_that_escapes_root(
    tmp_path: Path,
    asset_path: Callable[[Path], Path],
    asset_name: str,
) -> None:
    """A required asset cannot transfer authority through an escaping link."""
    root = tmp_path / "capsule"
    _write(capsule_node_executable(root), "node runtime\n")
    _write(capsule_acp_entry(root), "// acp entry\n")
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
    installed_acp_adapter: Path,
) -> None:
    """Explicit None bypasses configured capsule resolution in a clean process."""
    del installed_acp_adapter
    configured_root = tmp_path / "configured-capsule"
    configured_root.mkdir()
    repository_root = Path(__file__).resolve().parents[4]
    source_root = repository_root / "src"
    script = f"""
import json
import sys
sys.path.insert(0, {str(source_root)!r})
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.providers._factory_commands import _classify_acp_command
from vaultspec_a2a.thread.errors import ConfigError

try:
    _classify_acp_command("node")
except ConfigError as error:
    omitted = {{"status": "error", "message": str(error)}}
else:
    omitted = {{"status": "resolved"}}

command = _classify_acp_command("node", capsule_assets_root=None)
print(json.dumps({{
    "configured_root": str(settings.capsule_assets_root),
    "omitted": omitted,
    "explicit_none": {{
        "command": list(command.argv),
        "metadata": command.metadata(),
    }},
}}))
"""
    env = inherited_environment(
        {
            "VAULTSPEC_A2A_CAPSULE_ASSETS": str(configured_root),
            "VAULTSPEC_A2A_INSTALL_ROOT": str(repository_root),
        }
    )

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
    assert report["explicit_none"]["command"] == [
        resolve_service_executable("node"),
        str(claude_acp_entry()),
    ]
    assert report["explicit_none"]["metadata"]["runtime_authority"] == "project_local"
    assert report["explicit_none"]["metadata"]["command_origin"] == (
        "project_node_modules_entry"
    )


def test_explicit_none_keeps_project_backend_behavior(
    installed_acp_adapter: Path,
) -> None:
    """Explicit None selects the project-local classifier."""
    del installed_acp_adapter
    command = _classify_acp_command("node", capsule_assets_root=None)
    assert command.argv == (
        resolve_service_executable("node"),
        str(claude_acp_entry()),
    )
    assert command.runtime_authority == "project_local"
    assert command.command_origin == "project_node_modules_entry"
