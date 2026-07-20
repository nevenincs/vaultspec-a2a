"""The armed-run spawn-time isolation fail-loud, exercised through _astream.

Executes the ACTUAL raise path (not just the pure predicate): a harness-armed
claude-family model with no env auth token resolves ``should_isolate`` False, so
no isolated config home is created, and ``_astream`` must raise
``IsolationRequiredError`` BEFORE spawning any subprocess. No mocks, no
monkeypatch - the model is real and the raise fires ahead of ``_spawn_acp_process``
so nothing is launched. The model supplies explicit empty token values, masking
any operator ambient token without mutating process state. The one-sided guard
(a NON-armed run does not trip) is covered by the pure-predicate tests in
``test_acp_config_home.py``.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from ...thread.errors import IsolationRequiredError, ProjectionRefusedError
from ..acp_chat_model import AcpChatModel

# A claude-family ACP command (node adapter). The raise fires before any spawn,
# so this process is never actually launched.
_CLAUDE_CMD = [
    "node",
    "/x/node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js",
]


@pytest.mark.asyncio
async def test_armed_run_without_token_raises_isolation_required(
    tmp_path: Path,
) -> None:
    model = AcpChatModel(
        command=_CLAUDE_CMD,
        env_vars={
            "CLAUDE_CODE_OAUTH_TOKEN": "",
            "ANTHROPIC_AUTH_TOKEN": "",
        },  # explicit empty lane overrides any operator ambient token
        mcp_servers=[
            {
                "name": "vaultspec-rag",
                "type": "stdio",
                "command": "uvx",
                "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
            }
        ],
        workspace_root=str(tmp_path),
    )
    with pytest.raises(IsolationRequiredError):
        async for _ in model._astream([HumanMessage(content="hi")]):
            pass


@pytest.mark.asyncio
async def test_armed_run_refuses_on_workspace_mcp_name_collision(
    tmp_path: Path,
) -> None:
    # Isolation engages (token present), so the projection channel runs. A foreign
    # workspace .mcp.json whose server NAME collides with a declared surfacing entry
    # must make _astream raise ProjectionRefusedError BEFORE spawning, rather than
    # silently shadow either side. (A non-colliding foreign file is now merged, not
    # refused - covered in test_acp_project_mcp.py.)
    foreign = {"mcpServers": {"vaultspec-rag": {"type": "stdio", "command": "x"}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(foreign), encoding="utf-8")
    model = AcpChatModel(
        command=_CLAUDE_CMD,
        env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},  # isolation engages
        mcp_servers=[
            {
                "name": "vaultspec-rag",
                "type": "stdio",
                "command": "uvx",
                "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
            }
        ],
        workspace_root=str(tmp_path),
    )
    with pytest.raises(ProjectionRefusedError, match="collide"):
        async for _ in model._astream([HumanMessage(content="hi")]):
            pass
    # The foreign file is left intact (never clobbered).
    assert json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8")) == foreign


@pytest.mark.asyncio
async def test_spawn_failure_cleans_home_and_projection(tmp_path: Path) -> None:
    # A spawn-time raise (nonexistent binary through the real spawn path) must not
    # orphan the isolated config home OR the projected run-ws .mcp.json: the
    # finally is the single cleanup path for both.
    home_prefix = "vaultspec-acp-home-"
    tmp_root = Path(tempfile.gettempdir())
    homes_before = set(tmp_root.glob(home_prefix + "*"))
    model = AcpChatModel(
        command=["vaultspec-nonexistent-acp-binary-zzz"],
        env_vars={"ANTHROPIC_AUTH_TOKEN": "env-auth-token"},  # isolation engages
        use_exec=True,  # exec path -> a missing binary raises at spawn, not at shell
        mcp_servers=[
            {
                "name": "vaultspec-rag",
                "type": "stdio",
                "command": "uvx",
                "args": ["--from", "vaultspec-rag", "vaultspec-search-mcp"],
            }
        ],
        workspace_root=str(tmp_path),
    )
    with pytest.raises(FileNotFoundError):
        async for _ in model._astream([HumanMessage(content="hi")]):
            pass
    # Both artifacts are cleaned despite the spawn-time raise.
    assert not (tmp_path / ".mcp.json").exists()
    assert set(tmp_root.glob(home_prefix + "*")) == homes_before
