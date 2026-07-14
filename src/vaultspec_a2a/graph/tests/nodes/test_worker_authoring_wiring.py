"""Real-subprocess proof that the worker wires bridged authoring tools (R4).

No mocks: the worker node drives a real ACP subprocess (the protocol simulator)
through ``AcpChatModel``. When a run's :class:`AuthoringToolBinding` is attached,
the ``session/new`` the CLI receives must advertise the loopback authoring MCP
server carrying both auth layers — proving the wiring reaches a real subprocess.
Without a binding, ``session/new`` carries no MCP server, so the agent gains no
new surface by default.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from vaultspec_a2a.authoring import AgentTool, CatalogSnapshot
from vaultspec_a2a.providers._acp_authoring import (
    ACTOR_TOKEN_HEADER,
    AUTHORING_MCP_SERVER_NAME,
    AuthoringToolBinding,
)
from vaultspec_a2a.providers._acp_authoring import (
    BEARER_HEADER as _BEARER_HEADER,
)

from ...nodes.worker import create_worker_node

if TYPE_CHECKING:
    from vaultspec_a2a.thread.state import TeamState

SIMULATOR_PATH = Path(__file__).parent.parent / "acp_simulator.py"
PYTHON_EXE = sys.executable


def _make_state() -> TeamState:
    return {
        "active_agent": "coder",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Author a doc")],
        "next": "",
        "thread_id": "test-thread-authoring",
        "token_usage": {},
    }


def _binding(server_url: str = "http://127.0.0.1:8200/mcp") -> AuthoringToolBinding:
    snapshot = CatalogSnapshot(
        schema_version="authoring.semantic_tools.v1",
        tools=(
            AgentTool(
                name="read_context",
                description="read",
                input_schema={"type": "object"},
                risk_tier="read_only",
                permission_requirement="auto_permitted",
                idempotency_required=False,
                commands=("read_context",),
            ),
            AgentTool(
                name="propose_changeset",
                description="propose",
                input_schema={"type": "object"},
                risk_tier="mutating",
                permission_requirement="human_approval_required",
                idempotency_required=True,
                commands=("create_proposal",),
            ),
        ),
    )
    return AuthoringToolBinding(
        snapshot=snapshot,
        server_url=server_url,
        bearer_token="machine-bearer-xyz",
        actor_token="actor-token-abc",
    )


@pytest.mark.asyncio
async def test_binding_surfaces_authoring_server_to_real_subprocess(
    tmp_path: Path,
) -> None:
    """A bound worker turn makes the real CLI receive the authoring MCP server."""
    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

    record_file = tmp_path / "session_new.json"
    model = AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "authored",
            "--record-session-new",
            str(record_file),
        ],
        env_vars={},
        workspace_root=str(tmp_path),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
        autonomous=True,
        authoring_binding=_binding(),
    )

    result = await node(_make_state())
    assert result["messages"][0].content == "authored"

    params = json.loads(record_file.read_text(encoding="utf-8"))
    servers = params["mcpServers"]
    assert len(servers) == 1
    entry = servers[0]
    assert entry["name"] == AUTHORING_MCP_SERVER_NAME
    assert entry["type"] == "http"
    assert entry["url"] == "http://127.0.0.1:8200/mcp"
    headers = {h["name"]: h["value"] for h in entry["headers"]}
    assert headers[_BEARER_HEADER] == "Bearer machine-bearer-xyz"
    assert headers[ACTOR_TOKEN_HEADER] == "actor-token-abc"


@pytest.mark.asyncio
async def test_no_binding_leaves_session_without_mcp_servers(
    tmp_path: Path,
) -> None:
    """Without a binding the real CLI receives no MCP server (no new surface)."""
    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

    record_file = tmp_path / "session_new.json"
    model = AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "plain",
            "--record-session-new",
            str(record_file),
        ],
        env_vars={},
        workspace_root=str(tmp_path),
    )
    node = create_worker_node(
        model=model,
        system_prompt="You are a coder.",
        name="coder",
        autonomous=True,
    )

    result = await node(_make_state())
    assert result["messages"][0].content == "plain"

    params = json.loads(record_file.read_text(encoding="utf-8"))
    assert params["mcpServers"] == []
