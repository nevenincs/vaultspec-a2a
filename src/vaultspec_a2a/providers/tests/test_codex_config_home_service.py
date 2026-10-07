"""Service proofs for generated CODEX_HOME MCP configuration."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from ...graph.enums import Provider
from ...testing import combined_output, inherited_environment
from ...utils.enums import CodexWebSearchMode
from .._acp_mcp import codex_mcp_server_specs
from .._codex_config_home import (
    build_codex_config_home,
    cleanup_codex_config_home,
    render_codex_config_toml,
)
from ..cli_resolution import resolve_provider_cli_executable

pytestmark = pytest.mark.service

if TYPE_CHECKING:
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule


@pytest.fixture
def codex_cli(external_prerequisite: ExternalPrerequisiteRule) -> str:
    executable = resolve_provider_cli_executable(Provider.CODEX)
    if executable is None:
        external_prerequisite.absent(
            "codex-cli", "the service probe runs the installed CLI"
        )
    return executable


def _run_mcp_list(codex: str, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [codex, "mcp", "list"],
        env=inherited_environment({"CODEX_HOME": str(home)}),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_codex_mcp_list_accepts_the_built_config_home(
    tmp_path: Path, codex_cli: str
) -> None:
    """The installed CLI accepts and exposes production-generated MCP config."""
    home = build_codex_config_home(
        codex_mcp_server_specs(["vaultspec-rag"]),
        tmp_path / "base",
        web_search=CodexWebSearchMode.DISABLED,
    )
    try:
        proc = _run_mcp_list(codex_cli, home)
        assert proc.returncode == 0, proc.stderr
        assert "vaultspec-rag" in proc.stdout
        assert "uvx" in proc.stdout
        assert "vaultspec-search-mcp" in proc.stdout
    finally:
        cleanup_codex_config_home(home)


def test_codex_accepts_the_served_live_web_posture(
    tmp_path: Path, codex_cli: str
) -> None:
    """The installed CLI accepts the generated live web-search posture."""
    home = build_codex_config_home(
        codex_mcp_server_specs(["vaultspec-rag"]),
        tmp_path / "base",
        web_search=CodexWebSearchMode.LIVE,
    )
    try:
        written = (home / "config.toml").read_text(encoding="utf-8")
        assert 'web_search = "live"' in written
        proc = _run_mcp_list(codex_cli, home)
        assert proc.returncode == 0, proc.stderr
    finally:
        cleanup_codex_config_home(home)


def test_codex_refuses_an_unrecognised_web_mode(tmp_path: Path, codex_cli: str) -> None:
    """A bad live-posture token is rejected by the installed CLI."""
    home = tmp_path / "tampered-home"
    home.mkdir()
    rendered = render_codex_config_toml(
        codex_mcp_server_specs(["vaultspec-rag"]),
        web_search=CodexWebSearchMode.LIVE,
    )
    (home / "config.toml").write_text(
        rendered.replace('web_search = "live"', 'web_search = "no-such-mode"', 1),
        encoding="utf-8",
    )
    proc = _run_mcp_list(codex_cli, home)
    assert proc.returncode != 0
    combined = combined_output(proc)
    assert "web_search" in combined
    for mode in CodexWebSearchMode:
        assert f"`{mode.value}`" in combined
