"""Real-subprocess proof that the worker wires bridged authoring tools.

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
    authoring_allowed_tool_names,
)
from vaultspec_a2a.providers._acp_authoring import (
    BEARER_HEADER as _BEARER_HEADER,
)

from ...nodes.worker import _attach_authoring_tools, create_worker_node

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

    # The headless run auto-permits EXACTLY the bridged tool names so
    # the CLI can invoke them, and nothing else.
    allowed = params["_meta"]["claudeCode"]["options"]["allowedTools"]
    assert allowed == [
        "mcp__vaultspec-authoring__read_context",
        "mcp__vaultspec-authoring__propose_changeset",
    ]
    # A non-bridged mutating tool (e.g. the built-in Write) is NOT permitted.
    assert "Write" not in allowed
    assert not any(name == "mcp__vaultspec-authoring__*" for name in allowed)


def _stdio_binding(
    engine_base_url: str = "http://127.0.0.1:8767",
    run_id: str = "run:xyz",
) -> AuthoringToolBinding:
    return AuthoringToolBinding(
        snapshot=_binding().snapshot,
        bearer_token="machine-bearer-xyz",
        actor_token="actor-token-abc",
        engine_base_url=engine_base_url,
        run_id=run_id,
    )


@pytest.mark.asyncio
async def test_stdio_binding_wires_stdio_server_to_real_subprocess(
    tmp_path: Path,
) -> None:
    """A stdio binding makes session/new advertise the spawn-a-bridge entry.

    When the binding carries the engine transport (engine_base_url + run_id) the
    worker prefers the stdio bridge (a spawned subprocess). Neither session-injected
    transport surfaces to the model per the S20 registration-scope matrix, so this
    is a transport-mechanics choice, not a surfacing one. The session/new the real
    CLI receives must carry a stdio server entry (command + args, no url/type) whose
    env carries the run's engine facts — proving the wiring reaches a subprocess.
    """
    from vaultspec_a2a.providers._acp_authoring import AUTHORING_MCP_SERVER_NAME
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
        authoring_binding=_stdio_binding(),
    )

    await node(_make_state())

    params = json.loads(record_file.read_text(encoding="utf-8"))
    servers = params["mcpServers"]
    assert len(servers) == 1
    entry = servers[0]
    assert entry["name"] == AUTHORING_MCP_SERVER_NAME
    # A stdio entry spawns a command; it carries no HTTP url/type.
    assert "url" not in entry
    assert "type" not in entry
    assert entry["args"][0] == "-m"
    assert entry["args"][1].endswith("authoring_stdio")
    env = {item["name"]: item["value"] for item in entry["env"]}
    assert env["VAULTSPEC_AUTHORING_BASE_URL"] == "http://127.0.0.1:8767"
    assert env["VAULTSPEC_AUTHORING_RUN_ID"] == "run:xyz"
    assert env["VAULTSPEC_AUTHORING_BEARER"] == "machine-bearer-xyz"

    # The exact allowlist is still threaded so the CLI can invoke the bridged
    # tools headless.
    allowed = params["_meta"]["claudeCode"]["options"]["allowedTools"]
    assert allowed == authoring_allowed_tool_names(_stdio_binding())


class TestAuthoringAllowlist:
    """The auto-permit allowlist is exact, catalog-derived, and autonomous-only."""

    def test_allowed_names_are_exact_and_catalog_scoped(self) -> None:
        binding = _binding()
        names = authoring_allowed_tool_names(binding)
        assert names == [
            "mcp__vaultspec-authoring__read_context",
            "mcp__vaultspec-authoring__propose_changeset",
        ]
        assert "*" not in "".join(names)

    def test_autonomous_attaches_allowlist(self) -> None:
        from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

        model = AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")
        wired = _attach_authoring_tools(model, _binding(), autonomous=True)
        assert isinstance(wired, AcpChatModel)
        assert wired.allowed_tools == authoring_allowed_tool_names(_binding())

    def test_human_in_loop_gets_no_allowlist(self) -> None:
        from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

        model = AcpChatModel(command=["echo"], env_vars={}, workspace_root="/tmp/ws")
        wired = _attach_authoring_tools(model, _binding(), autonomous=False)
        assert isinstance(wired, AcpChatModel)
        # No allowlist → the human-in-loop permission prompt still gates every tool.
        assert wired.allowed_tools == []


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
