"""Service proof that a real Claude CLI accepts the projected MCP file."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from .._acp_mcp import resolve_harness_mcp_servers
from .._acp_project_mcp import cleanup_projected_mcp, project_declared_mcp

pytestmark = pytest.mark.service

if TYPE_CHECKING:
    from pathlib import Path


def _claude_cli() -> str:
    executable = shutil.which("claude")
    if executable is None:
        pytest.fail("Claude ACP CLI is required for the explicit service probe")
    return executable


def test_claude_mcp_list_accepts_the_projected_config(tmp_path: Path) -> None:
    """The production projection is accepted by the installed ACP CLI."""
    workspace = tmp_path / "run-ws"
    workspace.mkdir()
    projected = project_declared_mcp(
        workspace,
        resolve_harness_mcp_servers(["vaultspec-rag"]),
    )
    assert projected is not None
    config_home = tmp_path / "config-home"
    config_home.mkdir()
    environment = dict(os.environ)
    environment["CLAUDE_CONFIG_DIR"] = str(config_home)
    try:
        proc = subprocess.run(
            [_claude_cli(), "mcp", "list"],
            cwd=str(workspace),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "vaultspec-rag" in proc.stdout
        assert "uvx" in proc.stdout
        assert "vaultspec-search-mcp" in proc.stdout
    finally:
        cleanup_projected_mcp(projected)
