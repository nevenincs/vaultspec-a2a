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

from .._json_contract import JsonObject
from ..acp_chat_model import AcpChatModel

_SIMULATOR = (
    Path(__file__).parent.parent.parent / "graph" / "tests" / "acp_simulator.py"
)

_ALLOWED = ["mcp__vaultspec-rag__search_vault"]


async def _drive_and_record(
    tmp_path: Path, acp_family: str
) -> tuple[JsonObject, JsonObject]:
    """Run one turn on the simulator and return (initialize, session_new) params."""
    init_file = tmp_path / f"init_{acp_family}.json"
    new_file = tmp_path / f"new_{acp_family}.json"
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
        allowed_tools=_ALLOWED,
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
