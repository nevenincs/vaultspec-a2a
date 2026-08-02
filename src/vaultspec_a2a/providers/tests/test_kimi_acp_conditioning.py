"""Deterministic proof of the per-backend ACP _meta conditioning (P02.S08).

No mocks: a real ``AcpChatModel`` drives the real ACP protocol simulator as a
subprocess, which records the exact ``initialize`` and ``session/new`` params it
receives. Asserts the claude family serializes the Claude-only allowedTools
_meta while the kimi family omits it, and that the shared terminal-auth handshake
stays unconditional for BOTH families.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage
from pydantic import TypeAdapter

from ...authoring import AgentTool, CatalogSnapshot
from ...thread.errors import ConfigError
from .._acp_authoring import AuthoringToolBinding, build_authoring_stdio_mcp_servers
from .._json_contract import JsonObject
from ..acp_chat_model import AcpChatModel

_SIMULATOR = (
    Path(__file__).parent.parent.parent / "graph" / "tests" / "acp_simulator.py"
)

_ALLOWED = ["mcp__vaultspec-rag__search_vault"]


async def _drive_and_record(
    tmp_path: Path,
    acp_family: str,
    *,
    allowed_tools: list[str] | None = None,
    mcp_servers: list[JsonObject] | None = None,
    tag: str = "",
) -> tuple[JsonObject, JsonObject]:
    """Run one turn on the simulator and return (initialize, session_new) params."""
    init_file = tmp_path / f"init_{acp_family}{tag}.json"
    new_file = tmp_path / f"new_{acp_family}{tag}.json"
    model = AcpChatModel(
        command=[
            sys.executable,
            str(_SIMULATOR),
            "--response",
            "done",
            "--record-initialize",
            str(init_file),
            "--record-session-new",
            str(new_file),
        ],
        env_vars={},
        allowed_tools=_ALLOWED if allowed_tools is None else allowed_tools,
        mcp_servers=mcp_servers or [],
        acp_family=acp_family,
        workspace_root=str(tmp_path),
    )
    async for _ in model.astream([HumanMessage(content="hi")]):
        pass
    json_object = TypeAdapter[JsonObject](JsonObject)
    init_data = json_object.validate_json(init_file.read_text(encoding="utf-8"))
    new_data = json_object.validate_json(new_file.read_text(encoding="utf-8"))
    return init_data, new_data


def _allowed_tools_meta(session_new: JsonObject) -> list[str] | None:
    meta = session_new.get("_meta")
    if not isinstance(meta, dict):
        return None
    claude_code = meta.get("claudeCode")
    if not isinstance(claude_code, dict):
        return None
    options = claude_code.get("options")
    if not isinstance(options, dict):
        return None
    allowed_tools = options.get("allowedTools")
    if not isinstance(allowed_tools, list):
        return None
    result: list[str] = []
    for tool in allowed_tools:
        if not isinstance(tool, str):
            return None
        result.append(tool)
    return result


@pytest.mark.asyncio
async def test_claude_family_serializes_allowed_tools_meta(tmp_path: Path) -> None:
    """The claude family (Claude/Z.ai) emits the Claude-only allowedTools _meta."""
    _, session_new = await _drive_and_record(tmp_path, "claude")
    assert _allowed_tools_meta(session_new) == _ALLOWED


@pytest.mark.asyncio
async def test_kimi_family_omits_allowed_tools_meta(tmp_path: Path) -> None:
    """The kimi family omits the claudeCode namespace though allowed_tools is set.

    Read-only enforcement moves to the permission-RPC handler (P03.S10); the
    session/new the CLI receives carries NO claudeCode allowedTools _meta.
    """
    _, session_new = await _drive_and_record(tmp_path, "kimi")
    assert _allowed_tools_meta(session_new) is None
    # The mcpServers surface is still advertised (harness delivery is unaffected).
    assert "mcpServers" in session_new


@pytest.mark.asyncio
async def test_terminal_auth_handshake_is_unconditional_across_families(
    tmp_path: Path,
) -> None:
    """The clientCapabilities._meta.terminal-auth handshake is family-independent."""
    for family in ("claude", "kimi"):
        initialize, _ = await _drive_and_record(tmp_path, family)
        client_capabilities = initialize.get("clientCapabilities")
        assert isinstance(client_capabilities, dict)
        term_meta = client_capabilities.get("_meta")
        assert isinstance(term_meta, dict)
        assert term_meta.get("terminal-auth") is True, family


def _claude_code_options(session_new: JsonObject) -> JsonObject | None:
    meta = session_new.get("_meta")
    if not isinstance(meta, dict):
        return None
    claude_code = meta.get("claudeCode")
    if not isinstance(claude_code, dict):
        return None
    options = claude_code.get("options")
    return options if isinstance(options, dict) else None


@pytest.mark.asyncio
async def test_claude_family_pins_strict_mcp_on_every_session(
    tmp_path: Path,
) -> None:
    """strictMcpConfig rides every claude-family session, armed or not.

    On a plain (unarmed) run the flag is what keeps the operator's ambient MCP
    configuration - user-global servers, project ``.mcp.json``, plugins, and
    account connectors - from mounting into the agent: without it the CLI
    surfaces everything the operator's own interactive session would.
    """
    _, armed = await _drive_and_record(tmp_path, "claude", tag="_armed")
    options = _claude_code_options(armed)
    assert options is not None
    assert options.get("strictMcpConfig") is True

    _, plain = await _drive_and_record(
        tmp_path, "claude", allowed_tools=[], tag="_plain"
    )
    plain_options = _claude_code_options(plain)
    assert plain_options is not None
    assert plain_options.get("strictMcpConfig") is True
    # A plain run auto-permits nothing; the flag stands alone. And with no
    # declared servers there is nothing to wait for, so no readiness note.
    assert "allowedTools" not in plain_options
    plain_meta = plain.get("_meta")
    assert isinstance(plain_meta, dict)
    assert "systemPrompt" not in plain_meta


@pytest.mark.asyncio
async def test_kimi_family_never_receives_the_claude_option_block(
    tmp_path: Path,
) -> None:
    """The kimi agent has no claudeCode namespace, so no _meta rides at all."""
    _, session_new = await _drive_and_record(tmp_path, "kimi", tag="_strict")
    assert session_new.get("_meta") is None


@pytest.mark.asyncio
async def test_kimi_session_specs_are_normalized_to_carry_an_env_list(
    tmp_path: Path,
) -> None:
    """Every advertised stdio spec carries an explicit ``env`` list.

    The ACP schema models ``env`` as part of the stdio server shape and the
    migrated adapter's validator silently DROPS a spec without it - the failure
    that was long misread as session injection never surfacing. An env-less
    spec is exactly the class that used to vanish; the kimi family (no
    declared-surface guard) can advertise one directly, and the normalization
    is family-shared code.
    """
    _, session_new = await _drive_and_record(
        tmp_path,
        "kimi",
        mcp_servers=[{"name": "envless", "command": "srv", "args": ["run"]}],
        tag="_env",
    )
    servers = session_new.get("mcpServers")
    assert isinstance(servers, list) and servers
    for server in servers:
        assert isinstance(server, dict)
        assert server.get("env") == []


def _bridge_specs() -> list[JsonObject]:
    binding = AuthoringToolBinding(
        snapshot=CatalogSnapshot(
            schema_version="authoring.semantic_tools.v1",
            tools=(
                AgentTool(
                    name="read_context",
                    description="read tool",
                    input_schema={"type": "object"},
                    risk_tier="read_only",
                    permission_requirement="auto_permitted",
                    idempotency_required=False,
                    commands=("read_context",),
                ),
            ),
        ),
        engine_base_url="http://127.0.0.1:18300",
        run_id="run-strict-surface",
        bearer_token="machine-bearer-secret",
        actor_token="actor-token-secret",
    )
    return build_authoring_stdio_mcp_servers(binding)


@pytest.mark.asyncio
async def test_claude_session_env_values_are_placeholder_references(
    tmp_path: Path,
) -> None:
    """Bridge env values ride the claude session as ``${NAME}`` references.

    The adapter serializes the session set onto the spawned CLI's argv, which
    any local process enumerator can read, so the real bearer/actor/run values
    must never appear there: the CLI expands the references from its spawn
    environment at MCP config parse time instead.
    """
    _, session_new = await _drive_and_record(
        tmp_path, "claude", mcp_servers=_bridge_specs(), tag="_bridge"
    )
    # An armed session also carries the MCP-readiness system-prompt note: the
    # CLI mounts MCP asynchronously and does not hold the first turn, so the
    # model is told to wait for the declared tools instead of silently working
    # ungrounded.
    meta = session_new.get("_meta")
    assert isinstance(meta, dict)
    system_prompt = meta.get("systemPrompt")
    assert isinstance(system_prompt, dict)
    append = system_prompt.get("append")
    assert isinstance(append, str) and "WaitForMcpServers" in append
    servers = session_new.get("mcpServers")
    assert isinstance(servers, list) and len(servers) == 1
    server = servers[0]
    assert isinstance(server, dict)
    env = server.get("env")
    assert isinstance(env, list) and env
    rendered = str(session_new)
    assert "machine-bearer-secret" not in rendered
    assert "actor-token-secret" not in rendered
    for item in env:
        assert isinstance(item, dict)
        name = item.get("name")
        assert isinstance(name, str)
        assert item.get("value") == f"${{{name}}}"


@pytest.mark.asyncio
async def test_claude_family_refuses_an_undeclared_session_server(
    tmp_path: Path,
) -> None:
    """An entry outside the declared surface refuses the run before any mount.

    On the strict lane the session advertisement is mounted verbatim, so this
    guard is what stands between a reviewed harness and an arbitrary server
    riding in through a composed model.
    """
    model = AcpChatModel(
        command=[sys.executable, str(_SIMULATOR), "--response", "done"],
        env_vars={},
        mcp_servers=[{"name": "operator-extra", "command": "npx"}],
        acp_family="claude",
        workspace_root=str(tmp_path),
    )
    with pytest.raises(ConfigError, match="operator-extra"):
        async for _ in model.astream([HumanMessage(content="hi")]):
            pass


@pytest.mark.asyncio
async def test_claude_armed_session_leaves_the_workspace_untouched(
    tmp_path: Path,
) -> None:
    """MCP surfacing writes nothing into the run workspace.

    The declared surface rides the session itself; a crash or tree-kill can no
    longer leave surfacing residue (a projected ``.mcp.json`` or a
    ``.claude/settings.local.json`` confinement) governing the workspace's own
    interactive sessions.
    """
    before = sorted(p.name for p in tmp_path.iterdir())
    _, _session_new = await _drive_and_record(
        tmp_path, "claude", mcp_servers=_bridge_specs(), tag="_clean"
    )
    after = sorted(
        name
        for name in (p.name for p in tmp_path.iterdir())
        if not (name.startswith(("init_", "new_")) and name.endswith(".json"))
    )
    assert after == before
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / ".claude").exists()
