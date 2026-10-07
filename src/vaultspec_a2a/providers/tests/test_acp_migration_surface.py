"""Live regression: the pinned ACP adapter preserves the surface our layer targets.

No mocks. Spawns the real ``@agentclientprotocol/claude-agent-acp`` subprocess via
the production spawn path and drives ``initialize`` + ``session/new`` to assert the
protocol surface ``_acp_session.py`` / ``_acp_protocol.py`` depend on survives each
adapter bump, including the one that split the single bundle into per-surface
modules and withdrew a permission mode from the session catalog:

- ``initialize`` negotiates ``protocolVersion == 1`` (the exact version our request
  hardcodes and our fs/terminal RPC method names are keyed to),
- the result carries ``agentCapabilities`` (with ``loadSession``) and ``authMethods``,
  the two fields ``InitializeResult`` parses,
- ``session/new`` returns a ``sessionId`` and a ``modes`` block with ``currentModeId``
  and ``availableModes`` — the shape ``SessionSetupResult`` parses,
- the mode an unattended run pins is in the catalog THIS session reports, and the
  bypass mode the lane declines is not,
- the ``_meta.claudeCode.options`` block is the one production composes
  (:func:`claude_session_options`), not a copy of it, so an option the adapter
  starts rejecting — or one it starts requiring — fails here rather than at the
  first served turn.

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

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...control.config import settings
from ...graph.enums import Provider
from ...testing import (
    ACP_PROTOCOL_VERSION,
    acp_request,
    exchange_acp_request,
    initialize_request,
)
from ...workspace.environment import resolve_env_vars
from .._acp_session import claude_session_options
from .._acp_types import AcpModelConfig
from .._claude_tool_policy import AUTONOMOUS_PERMISSION_MODE, MODE_CONFIG_OPTION_ID
from .._factory_commands import _classify_acp_command, claude_acp_entry
from .._json_contract import JsonObject, JsonValue
from .._subprocess import kill_process_tree, spawn_acp_process
from ..cli_resolution import resolve_provider_cli_executable

if TYPE_CHECKING:
    from asyncio.subprocess import Process


async def _assert_initialize_surface(proc: Process) -> None:
    init_frame = await exchange_acp_request(
        proc,
        initialize_request(
            0,
            "p02-s08-surface",
            {"fs": {"readTextFile": True, "writeTextFile": False}},
        ),
        30.0,
    )
    assert "result" in init_frame, init_frame.get("error")
    init_res = init_frame["result"]
    assert isinstance(init_res, dict)

    # protocolVersion our request pins and our fs/terminal RPC names are keyed to.
    assert init_res.get("protocolVersion") == ACP_PROTOCOL_VERSION, init_res.get(
        "protocolVersion"
    )
    # The two fields InitializeResult parses.
    agent_caps = init_res.get("agentCapabilities")
    assert isinstance(agent_caps, dict) and agent_caps
    assert agent_caps.get("loadSession") is True
    assert isinstance(init_res.get("authMethods"), list)


def _served_config(workspace: str) -> AcpModelConfig:
    """Build the frozen config an unattended claude-family turn is served with.

    No permission callback, which is what makes the session unattended, and the
    bridged tool name a headless run auto-permits. Everything the adapter is
    asked for is then derived from this by production code.
    """
    return AcpModelConfig(
        agent_config=None,
        permission_callback=None,
        workspace_root=workspace,
        command=[],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider=Provider.CLAUDE.value,
        runtime_authority=None,
        acp_backend=settings.acp_backend,
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
        allowed_tools=["mcp__vaultspec-rag__search"],
        acp_family="claude",
    )


async def _set_config_option(
    proc: Process, rpc_id: int, session_id: str, config_id: str, value: str
) -> JsonObject:
    """Send ``session/set_config_option`` and return the option as the adapter holds it.

    The adapter answers with its whole option list, so the one named *config_id*
    is picked out of the reply rather than assumed to be the only entry.
    """
    frame = await exchange_acp_request(
        proc,
        acp_request(
            rpc_id,
            "session/set_config_option",
            {"sessionId": session_id, "configId": config_id, "value": value},
        ),
        40.0,
    )
    assert "result" in frame, frame.get("error")
    result = frame["result"]
    assert isinstance(result, dict)
    options = result.get("configOptions")
    assert isinstance(options, list)
    matching = [
        option
        for option in options
        if isinstance(option, dict) and option.get("id") == config_id
    ]
    assert len(matching) == 1, options
    return matching[0]


async def _start_acp_session(proc: Process, workspace: str) -> tuple[str, str, str]:
    # session/new with the claudeCode options block PRODUCTION composes, read
    # from the production composer rather than copied: a copy proves the
    # adapter accepts some shape, which is not the question. The question is
    # whether it accepts the shape a served turn sends.
    new_frame = await exchange_acp_request(
        proc,
        acp_request(
            1,
            "session/new",
            {
                "cwd": workspace,
                "mcpServers": list[JsonValue](),
                "_meta": {
                    "claudeCode": {
                        "options": claude_session_options(_served_config(workspace))
                    }
                },
            },
        ),
        40.0,
    )
    assert "result" in new_frame, new_frame.get("error")
    new_res = new_frame["result"]
    assert isinstance(new_res, dict)

    # The shape SessionSetupResult parses.
    session_id = new_res.get("sessionId")
    assert isinstance(session_id, str) and session_id
    modes = new_res.get("modes")
    assert isinstance(modes, dict), new_res
    assert modes.get("currentModeId")
    available = modes.get("availableModes")
    assert isinstance(available, list) and available
    assert all(isinstance(mode, dict) and "id" in mode for mode in available)

    # The mode an unattended run pins has to be in the catalog THIS session
    # reports, because that is the list the adapter validates the pin against.
    offered = [
        mode["id"] for mode in available if isinstance(mode, dict) and "id" in mode
    ]
    assert AUTONOMOUS_PERMISSION_MODE in offered, offered
    # And the capability the options block declines is genuinely withdrawn: a
    # bypass mode in the catalog would mean the spawned CLI also carries the
    # skip-permissions flag the same decision arms.
    assert "bypassPermissions" not in offered, offered
    # Withdrawn upstream while the adapter's parser still accepts the spelling.
    # Asserted against a real session because the parser is what a reading of
    # the source finds first, and it is the catalog that decides: asking for a
    # mode that is only parseable fails the session rather than pinning it.
    assert "dontAsk" not in offered, offered

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

    # Take the model from what THIS session advertises, never from a table
    # in source. External lanes carry no hardcoded model values precisely
    # because provider catalogs move; a literal here would pass until the
    # next CLI release retired the name and then fail for a reason that
    # looks nothing like "the constant went stale".
    advertised = model_option.get("options")
    assert isinstance(advertised, list) and advertised, model_option
    desired_model = next(
        value
        for choice in advertised
        if isinstance(choice, dict)
        for field in ("value", "modelId", "id")
        if isinstance(value := choice.get(field), str) and value
    )
    return session_id, config_id, desired_model


@pytest.mark.service
@pytest.mark.asyncio
async def test_migrated_adapter_preserves_handshake_surface() -> None:
    if settings.acp_backend != "binary" and not claude_acp_entry().exists():
        pytest.fail(
            "migrated ACP node entry not installed; run 'npm install' "
            "(@agentclientprotocol/claude-agent-acp) per the ACP runbook"
        )

    command = _classify_acp_command(settings.acp_backend)
    workspace = str(Path.cwd())
    # Exactly the production env assembly: ambient environment passthrough, no
    # credential injected or scrubbed (the no-auth contract).
    env = resolve_env_vars(Path(workspace))
    sys_claude = resolve_provider_cli_executable(Provider.CLAUDE)
    if sys_claude:
        env["CLAUDE_CODE_EXECUTABLE"] = sys_claude
    env.pop("CLAUDECODE", None)

    proc = await spawn_acp_process(
        list(command.argv),
        env,
        workspace,
        use_exec=False,
        metadata=command.metadata(),
    )
    try:
        await _assert_initialize_surface(proc)
        session_id, config_id, desired_model = await _start_acp_session(proc, workspace)
        selected = await _set_config_option(
            proc, 2, session_id, config_id, desired_model
        )
        assert selected.get("currentValue") == desired_model

        # The seam an unattended run pins its permission mode through. It is
        # this exchange rather than session/set_mode precisely because it
        # answers with the option list the adapter now holds, so the mode is
        # set and verified in one call - which is the property asserted here.
        pinned = await _set_config_option(
            proc, 3, session_id, MODE_CONFIG_OPTION_ID, AUTONOMOUS_PERMISSION_MODE
        )
        assert pinned.get("currentValue") == AUTONOMOUS_PERMISSION_MODE
    finally:
        await kill_process_tree(proc, metadata=command.metadata())
