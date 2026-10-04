"""The declared Claude auth channel controls the actual child environment."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from typing import TYPE_CHECKING

import pytest
from pydantic import SecretStr

from ...conftest import _claude_credentialed
from ...graph.enums import Provider
from ...testing import armed_environment, settings_override
from .._factory_commands import (
    capsule_acp_entry,
    capsule_claude_executable,
    capsule_node_executable,
)
from ..acp_chat_model import AcpChatModel
from ..acp_exceptions import AcpError
from ..cli_resolution import ProviderRuntimeUnavailableError, resolve_service_executable
from ..factory import (
    _discover_claude_catalog,
    claude_auth_env,
)
from ..provider_catalog import CatalogStatus, ProviderCatalogKey

if TYPE_CHECKING:
    from pathlib import Path


def _child_token(env: dict[str, str]) -> str:
    """Read the credential off a real child, not the Python overlay alone."""
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('CLAUDE_CODE_OAUTH_TOKEN', ''))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    return child.stdout.strip()


def _cli_file(root: Path) -> Path:
    cli = root / ("claude.exe" if os.name == "nt" else "claude")
    cli.write_text("owned CLI\n", encoding="utf-8")
    return cli


def _auth_model(root: Path) -> AcpChatModel:
    """Build the real ACP model from production credential selection."""
    env_vars, auth_mode = claude_auth_env()
    return AcpChatModel(
        command=["node", "index.js"],
        env_vars=env_vars,
        workspace_root=str(root),
        provider=Provider.CLAUDE.value,
        auth_mode=auth_mode,
    )


@pytest.mark.parametrize(
    ("channel", "configured", "ambient", "expected"),
    (
        ("subscription_login", SecretStr("configured-test-token"), None, False),
        ("subscription_login", None, "ambient-test-token", True),
        ("oauth_token", SecretStr("configured-test-token"), None, True),
        ("oauth_token", None, "ambient-test-token", False),
    ),
)
def test_credential_prerequisite_uses_production_channel(
    tmp_path: Path,
    channel: str,
    configured: SecretStr | None,
    ambient: str | None,
    expected: bool,
) -> None:
    with (
        settings_override(
            claude_auth_channel=channel,
            claude_code_oauth_token=configured,
        ),
        armed_environment(
            PATH=str(tmp_path),
            CLAUDE_CONFIG_DIR=str(tmp_path),
            CLAUDE_CODE_OAUTH_TOKEN=ambient,
        ),
    ):
        assert _claude_credentialed() is expected


def test_subscription_channel_does_not_inject_the_configured_token(
    tmp_path: Path,
) -> None:
    cli = _cli_file(tmp_path)
    with (
        settings_override(
            claude_auth_channel="subscription_login",
            claude_code_oauth_token=SecretStr("configured-test-token"),
            claude_cli_executable=cli,
        ),
        armed_environment(CLAUDE_CODE_OAUTH_TOKEN=None),
    ):
        model = _auth_model(tmp_path)
        env = asyncio.run(model._acp_environment())

    assert model.auth_mode == "subscription_login"
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in model.env_vars
    assert _child_token(env) == ""


def test_subscription_channel_preserves_the_operators_ambient_export(
    tmp_path: Path,
) -> None:
    cli = _cli_file(tmp_path)
    with (
        settings_override(
            claude_auth_channel="subscription_login",
            claude_code_oauth_token=SecretStr("configured-test-token"),
            claude_cli_executable=cli,
        ),
        armed_environment(CLAUDE_CODE_OAUTH_TOKEN="ambient-test-token"),
    ):
        model = _auth_model(tmp_path)
        env = asyncio.run(model._acp_environment())

    assert model.auth_mode == "subscription_login"
    assert _child_token(env) == "ambient-test-token"


def test_oauth_channel_overrides_ambient_token_in_the_child(tmp_path: Path) -> None:
    cli = _cli_file(tmp_path)
    with (
        settings_override(
            claude_auth_channel="oauth_token",
            claude_code_oauth_token=SecretStr("configured-test-token"),
            claude_cli_executable=cli,
        ),
        armed_environment(CLAUDE_CODE_OAUTH_TOKEN="different-ambient-token"),
    ):
        model = _auth_model(tmp_path)
        env = asyncio.run(model._acp_environment())

    assert model.auth_mode == "oauth_token"
    assert _child_token(env) == "configured-test-token"
    assert "configured-test-token" not in repr(model)
    assert "configured-test-token" not in str(model.model_dump())


@pytest.mark.parametrize("token", (None, SecretStr("   ")))
def test_oauth_channel_without_a_token_refuses_selection(
    token: SecretStr | None, tmp_path: Path
) -> None:
    cli = _cli_file(tmp_path)
    with (
        settings_override(
            claude_auth_channel="oauth_token",
            claude_code_oauth_token=token,
            claude_cli_executable=cli,
        ),
        pytest.raises(ProviderRuntimeUnavailableError, match="configured OAuth token"),
    ):
        claude_auth_env()


@pytest.mark.asyncio
async def test_oauth_channel_without_a_token_refuses_catalog_probe(
    tmp_path: Path,
) -> None:
    cli = _cli_file(tmp_path)
    key = ProviderCatalogKey(Provider.CLAUDE.value, "claude-agent-acp:node")
    with settings_override(
        claude_auth_channel="oauth_token",
        claude_code_oauth_token=None,
        claude_cli_executable=cli,
    ):
        discovery = await _discover_claude_catalog(key, tmp_path)

    assert discovery.catalog.state.status is CatalogStatus.UNAVAILABLE
    assert discovery.catalog.state.reason == "claude_oauth_token_unavailable"


@pytest.mark.asyncio
async def test_oauth_catalog_probe_passes_token_to_its_real_child(
    tmp_path: Path,
) -> None:
    report = tmp_path / "probe-token.txt"
    capsule = tmp_path / "capsule"
    node = capsule_node_executable(capsule)
    node.parent.mkdir(parents=True, exist_ok=True)
    installed_node = resolve_service_executable("node")
    assert installed_node is not None
    shutil.copy2(installed_node, node)
    entry = capsule_acp_entry(capsule)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        "require('node:fs').writeFileSync("
        f"{json.dumps(str(report))}, process.env.CLAUDE_CODE_OAUTH_TOKEN || '')\n",
        encoding="utf-8",
    )
    cli = capsule_claude_executable(capsule)
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text("capsule CLI\n", encoding="utf-8")
    key = ProviderCatalogKey(Provider.CLAUDE.value, "claude-agent-acp:node")

    with (
        settings_override(
            claude_auth_channel="oauth_token",
            claude_code_oauth_token=SecretStr("configured-test-token"),
            claude_cli_executable=None,
            capsule_assets_root=capsule,
        ),
        armed_environment(CLAUDE_CODE_OAUTH_TOKEN="different-ambient-token"),
        suppress(AcpError),
    ):
        await _discover_claude_catalog(key, tmp_path)

    assert report.read_text(encoding="utf-8") == "configured-test-token"
