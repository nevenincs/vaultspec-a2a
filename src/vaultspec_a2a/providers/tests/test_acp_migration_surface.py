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
- the ``_meta.claudeCode.options`` block our ``setup_session`` emits on every
  claude-family session (``strictMcpConfig`` plus the headless ``allowedTools``
  auto-permit) is accepted without error.

Service-marked and reaped before any ``session/prompt``: the subject here is the
handshake surface, so a turn would add runtime and flakiness without adding
evidence. The lane implements NO authentication of its own: the env is exactly
the production workspace assembly (``resolve_env_vars``), which scrubs provider
API keys — including ``ANTHROPIC_API_KEY``, so a stray key can never silently
downgrade the operator's flat-rate login to metered billing — and injects no
credential of its own; the subprocess resolves whatever login the operator
ambiently carries. Completed-turn coverage for this provider lives in
``test_claude_live_turn.py``; the strict-MCP surfacing loop is proven in
``test_acp_strict_mcp_surface.py``.

Skips with a pointer when the Claude CLI entry point is unavailable (an infra gate).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ...control.config import settings
from ...graph.enums import MODEL_MAP, Model, Provider
from ...workspace.environment import resolve_env_vars
from .._json_contract import JsonObject, JsonValue
from .._subprocess import kill_process_tree, spawn_acp_process
from ..factory import _CLAUDE_ACP_JS, _classify_acp_command
from ._acp_frames import read_acp_frame


@pytest.mark.service
@pytest.mark.asyncio
async def test_migrated_adapter_preserves_handshake_surface() -> None:
    if settings.acp_backend != "binary" and not _CLAUDE_ACP_JS.exists():
        pytest.fail(
            "migrated ACP node entry not installed; run 'npm install' "
            "(@agentclientprotocol/claude-agent-acp) per the ACP runbook"
        )

    command, meta = _classify_acp_command(settings.acp_backend)
    workspace = str(Path.cwd())
    # Exactly the production env assembly: ambient environment passthrough, no
    # credential injected or scrubbed (the no-auth contract).
    env = resolve_env_vars(Path(workspace))
    sys_claude = shutil.which("claude")
    if sys_claude:
        env["CLAUDE_CODE_EXECUTABLE"] = sys_claude
    env.pop("CLAUDECODE", None)

    proc = await spawn_acp_process(
        command, env, workspace, use_exec=False, metadata=meta
    )
    assert proc.stdin is not None and proc.stdout is not None
    try:
        init: JsonObject = {
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
        assert isinstance(init_res, dict)

        # protocolVersion our request pins and our fs/terminal RPC names are keyed to.
        assert init_res.get("protocolVersion") == 1, init_res.get("protocolVersion")
        # The two fields InitializeResult parses.
        agent_caps = init_res.get("agentCapabilities")
        assert isinstance(agent_caps, dict) and agent_caps
        assert agent_caps.get("loadSession") is True
        assert isinstance(init_res.get("authMethods"), list)

        # session/new with the claudeCode options block our layer emits on every
        # claude-family session: strictMcpConfig plus the headless allowedTools
        # auto-permit (production emission is pinned by the ACP-simulator
        # conditioning tests; this proves the real adapter accepts the shape).
        new: JsonObject = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/new",
            "params": {
                "cwd": workspace,
                "mcpServers": list[JsonValue](),
                "_meta": {
                    "claudeCode": {
                        "options": {
                            "strictMcpConfig": True,
                            "allowedTools": ["mcp__vaultspec-rag__search"],
                        }
                    }
                },
            },
        }
        proc.stdin.write(json.dumps(new).encode("utf-8") + b"\n")
        await proc.stdin.drain()
        new_frame = await read_acp_frame(proc.stdout, 1, 40.0)
        assert "result" in new_frame, new_frame.get("error")
        new_res = new_frame["result"]
        assert isinstance(new_res, dict)

        # The shape SessionSetupResult parses.
        assert isinstance(new_res.get("sessionId"), str) and new_res["sessionId"]
        modes = new_res.get("modes")
        assert isinstance(modes, dict), new_res
        assert modes.get("currentModeId")
        available = modes.get("availableModes")
        assert isinstance(available, list) and available
        assert all(isinstance(mode, dict) and "id" in mode for mode in available)

        config_options = new_res.get("configOptions")
        assert isinstance(config_options, list) and config_options
        model_options = [
            option
            for option in config_options
            if isinstance(option, dict) and option.get("category") == "model"
        ]
        assert len(model_options) == 1
        model_option = model_options[0]
        config_id = model_option.get("id")
        assert isinstance(config_id, str) and config_id

        desired_model = MODEL_MAP[Provider.CLAUDE][Model.LOW]
        select_model: JsonObject = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/set_config_option",
            "params": {
                "sessionId": new_res["sessionId"],
                "configId": config_id,
                "value": desired_model,
            },
        }
        proc.stdin.write(json.dumps(select_model).encode("utf-8") + b"\n")
        await proc.stdin.drain()
        selected_frame = await read_acp_frame(proc.stdout, 2, 40.0)
        assert "result" in selected_frame, selected_frame.get("error")
        selected_result = selected_frame["result"]
        assert isinstance(selected_result, dict)
        selected_options = selected_result.get("configOptions")
        assert isinstance(selected_options, list)
        selected_model_options = [
            option
            for option in selected_options
            if isinstance(option, dict) and option.get("id") == config_id
        ]
        assert len(selected_model_options) == 1
        assert selected_model_options[0].get("currentValue") == desired_model
    finally:
        await kill_process_tree(proc, metadata=meta)
