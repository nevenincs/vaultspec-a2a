"""Live regression: the migrated ACP adapter preserves the surface our layer targets.

No mocks. Spawns the real ``@agentclientprotocol/claude-agent-acp`` subprocess via
the production spawn path and drives ``initialize`` + ``session/new`` to assert the
protocol surface ``_acp_session.py`` / ``_acp_protocol.py`` depend on survives the
0.23.1 -> 0.59.0 migration (a 36-release jump whose vendored SDK crossed 0.2.x to
0.3.x):

- ``initialize`` negotiates ``protocolVersion == 1`` (the exact version our request
  hardcodes and our fs/terminal RPC method names are keyed to),
- the result carries ``agentCapabilities`` (with ``loadSession``) and ``authMethods``,
  the two fields ``InitializeResult`` parses,
- ``session/new`` returns a ``sessionId`` and a ``modes`` block with ``currentModeId``
  and ``availableModes`` — the shape ``SessionSetupResult`` parses,
- the ``_meta.claudeCode.options.allowedTools`` auto-permit shape our headless
  ``setup_session`` emits is accepted without error.

Service-marked and reaped before any ``session/prompt`` — no agent work, no spend.
Skips with a pointer when the Claude CLI entry point is unavailable (an infra gate).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ...control.config import settings
from ...workspace.environment import resolve_env_vars
from .._subprocess import kill_process_tree, spawn_acp_process
from ..factory import _CLAUDE_ACP_JS, _classify_acp_command
from ._acp_frames import read_acp_frame


@pytest.mark.service
@pytest.mark.asyncio
async def test_migrated_adapter_preserves_handshake_surface() -> None:
    if settings.acp_backend != "binary" and not _CLAUDE_ACP_JS.exists():
        pytest.skip(
            "migrated ACP node entry not installed; run 'npm install' "
            "(@agentclientprotocol/claude-agent-acp) per the ACP runbook"
        )

    command, meta = _classify_acp_command(settings.acp_backend)
    workspace = str(Path.cwd())
    env = resolve_env_vars(Path(workspace))
    token = settings.claude_code_oauth_token
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        env.pop("ANTHROPIC_API_KEY", None)
    sys_claude = shutil.which("claude")
    if sys_claude:
        env["CLAUDE_CODE_EXECUTABLE"] = sys_claude
    env.pop("CLAUDECODE", None)

    proc = await spawn_acp_process(
        command, env, workspace, use_exec=False, metadata=meta
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        init = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": False},
                },
                "clientInfo": {"name": "p02-s08-surface", "version": "1.0.0"},
            },
        }
        proc.stdin.write(json.dumps(init).encode("utf-8") + b"\n")
        await proc.stdin.drain()
        init_frame = await read_acp_frame(proc.stdout, 0, 30.0)
        assert "result" in init_frame, init_frame.get("error")
        init_res = init_frame["result"]

        # protocolVersion our request pins and our fs/terminal RPC names are keyed to.
        assert init_res.get("protocolVersion") == 1, init_res.get("protocolVersion")
        # The two fields InitializeResult parses.
        agent_caps = init_res.get("agentCapabilities")
        assert isinstance(agent_caps, dict) and agent_caps
        assert agent_caps.get("loadSession") is True
        assert isinstance(init_res.get("authMethods"), list)

        # session/new with the headless allowedTools auto-permit meta our layer emits.
        new = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/new",
            "params": {
                "cwd": workspace,
                "mcpServers": [],
                "_meta": {
                    "claudeCode": {
                        "options": {"allowedTools": ["mcp__vaultspec-rag__search"]}
                    }
                },
            },
        }
        proc.stdin.write(json.dumps(new).encode("utf-8") + b"\n")
        await proc.stdin.drain()
        new_frame = await read_acp_frame(proc.stdout, 1, 40.0)
        assert "result" in new_frame, new_frame.get("error")
        new_res = new_frame["result"]

        # The shape SessionSetupResult parses.
        assert isinstance(new_res.get("sessionId"), str) and new_res["sessionId"]
        modes = new_res.get("modes")
        assert isinstance(modes, dict), new_res
        assert modes.get("currentModeId")
        available = modes.get("availableModes")
        assert isinstance(available, list) and available
        assert all("id" in m for m in available)
    finally:
        await kill_process_tree(proc, metadata=meta)
