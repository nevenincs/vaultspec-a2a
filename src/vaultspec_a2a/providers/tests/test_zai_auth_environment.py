"""Z.ai credentials belong only to the explicitly selected provider root."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ...testing import armed_environment
from ...workspace.environment import scrub_agent_environment
from .._acp_rpc_terminal_handlers import _terminal_environment
from .._factory_commands import _build_zai_env
from .._mcp_contract import _probe_environment
from ..acp_chat_model import AcpChatModel
from ..binary_version import probe_binary_version
from ..codex_chat_model import CodexChatModel

if TYPE_CHECKING:
    from pathlib import Path

_AMBIENT = {
    "ANTHROPIC_AUTH_TOKEN": "synthetic-ambient-token",
    "ANTHROPIC_BASE_URL": "https://ambient.invalid/anthropic",
    "ZAI_AUTH_TOKEN": "synthetic-zai-token",
    "ZAI_API_KEY": "synthetic-legacy-token",
    "ZAI_BASE_URL": "https://zai.invalid/anthropic",
    "ZAI_ANTHROPIC_BASE_URL": "https://legacy.invalid/anthropic",
}


def _child_credentials(environment: dict[str, str]) -> dict[str, str]:
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, os, sys; "
            "print(json.dumps({k: v for k, v in os.environ.items() "
            "if k.upper() in json.loads(sys.argv[1])}))",
            json.dumps(list(_AMBIENT)),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    return json.loads(child.stdout)


@pytest.mark.parametrize("recipient", ["claude", "codex", "kimi", "mcp", "terminal"])
def test_ambient_zai_credentials_do_not_reach_unrelated_children(
    tmp_path: Path, recipient: str
) -> None:
    with armed_environment(**_AMBIENT):
        if recipient == "codex":
            environment = CodexChatModel()._build_env(tmp_path)
        elif recipient == "mcp":
            environment = _probe_environment(dict(os.environ))
        elif recipient == "terminal":
            environment = _terminal_environment({}, tmp_path)
        else:
            model = AcpChatModel(
                command=[],
                workspace_root=str(tmp_path),
                provider=recipient,
                acp_family="kimi" if recipient == "kimi" else "claude",
            )
            environment = asyncio.run(model._acp_environment())
    assert _child_credentials(environment) == {}


@pytest.mark.parametrize("name", list(_AMBIENT))
def test_zai_alias_scrubbing_is_case_insensitive(name: str) -> None:
    assert scrub_agent_environment(
        {name.lower(): "synthetic-value", "PATH": "runtime"}
    ) == {"PATH": "runtime"}


@pytest.mark.parametrize("token", ["synthetic-selected-token", None, "  "])
def test_only_selected_zai_auth_reaches_the_zai_child(
    tmp_path: Path, token: str | None
) -> None:
    selected = _build_zai_env("https://selected.invalid/anthropic", token)
    with armed_environment(**_AMBIENT):
        model = AcpChatModel(
            command=[],
            workspace_root=str(tmp_path),
            provider="zai",
            env_vars=selected,
        )
        environment = asyncio.run(model._acp_environment())
    expected = (
        {
            "ANTHROPIC_AUTH_TOKEN": "synthetic-selected-token",
            "ANTHROPIC_BASE_URL": "https://selected.invalid/anthropic",
        }
        if token == "synthetic-selected-token"
        else {}
    )
    assert _child_credentials(environment) == expected
    assert _child_credentials(_probe_environment(environment)) == {}


def test_version_probe_has_no_ambient_provider_credentials(tmp_path: Path) -> None:
    names = [*_AMBIENT, "CLAUDE_CODE_OAUTH_TOKEN"]
    launcher = tmp_path / ("version.cmd" if os.name == "nt" else "version")
    if os.name == "nt":
        script = "@echo off\n" + "\n".join(
            f"if defined {name} exit /b 1" for name in names
        )
        script += '\nif not "%PROBE_SAFE_OPTION%"=="preserved" exit /b 2\n'
    else:
        script = "#!/bin/sh\n" + "\n".join(
            f'if [ "${{{name}+x}}" = x ]; then exit 1; fi' for name in names
        )
        script += '\n[ "$PROBE_SAFE_OPTION" = preserved ] || exit 2\n'
    launcher.write_text(script + "echo probe-cli 1.2.3\n", encoding="utf-8")
    if os.name != "nt":
        launcher.chmod(0o755)
    with armed_environment(
        **_AMBIENT,
        CLAUDE_CODE_OAUTH_TOKEN="synthetic-claude-token",
        PROBE_SAFE_OPTION="preserved",
    ):
        assert probe_binary_version(launcher) == "1.2.3"
