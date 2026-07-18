"""The armed-run spawn-time isolation fail-loud, exercised through _astream.

Executes the ACTUAL raise path (not just the pure predicate): a harness-armed
claude-family model with no env auth token resolves ``should_isolate`` False, so
no isolated config home is created, and ``_astream`` must raise
``IsolationRequiredError`` BEFORE spawning any subprocess. No mocks, no
monkeypatch - the model is real and the raise fires ahead of ``_spawn_acp_process``
so nothing is launched. Relies on the canonical no-ambient-token test environment
(the same assumption the harness wiring tests make). The one-sided guard (a
NON-armed run does not trip) is covered by the pure-predicate tests in
``test_acp_config_home.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ...thread.errors import IsolationRequiredError
from ..acp_chat_model import AcpChatModel

if TYPE_CHECKING:
    from pathlib import Path

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
        env_vars={},  # no lane token -> should_isolate False -> no config home
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
