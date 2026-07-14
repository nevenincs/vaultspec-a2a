"""ACP session lifecycle RPCs: initialize, setup, and prompt.

Extracted from the original monolithic ``_acp_session.py`` (D-04).
Data carriers live in ``_acp_types``, auth logic in ``_acp_auth``.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from ..control.config import settings
from ..utils.enums import AcpRequestId
from ..workspace.environment import resolve_env_vars
from ._acp_auth import (
    auth_hint,
    authenticate_rpc,
    is_auth_required_error,
    runtime_log_extra,
)
from ._acp_types import (
    InitializeResult,
    SessionSetupResult,
    _AcpModelConfig,
    _AcpSessionContext,
)
from .acp_exceptions import AcpErrorCode, AcpSessionError

__all__: list[str] = []

logger = logging.getLogger(__name__)


async def initialize_session(
    ctx: _AcpSessionContext,
    config: _AcpModelConfig,
) -> InitializeResult:
    """Send ACP initialize request and return capabilities + auth methods."""
    rpc_id = AcpRequestId.INITIALIZE
    ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
    req = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "clientCapabilities": {
                "fs": {
                    "readTextFile": (
                        config.agent_config.capabilities.filesystem_read
                        if config.agent_config is not None
                        else False
                    ),
                    "writeTextFile": (
                        config.agent_config.capabilities.filesystem_write
                        if config.agent_config is not None
                        else False
                    ),
                },
                "terminal": (
                    config.agent_config.capabilities.terminal
                    if config.agent_config is not None
                    else False
                ),
                # ACP-AUTH-002: signal support for terminal-based auth and
                # terminal output to claude-agent-acp >=0.20.2.  Without
                # these flags the agent refuses to authenticate via the
                # subprocess stdin/stdout channel (gateway auth check added
                # in v0.20.2 via zed-industries/claude-agent-acp#380).
                "_meta": {
                    "terminal-auth": True,
                    "terminal_output": True,
                },
            },
            "clientInfo": {"name": "vaultspec", "version": "1.0.0"},
        },
    }
    async with ctx.stdin_lock:
        ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.stdin.drain()
    try:
        resp = await asyncio.wait_for(
            ctx.response_futures[rpc_id],
            timeout=settings.acp_startup_timeout_seconds,
        )
    except TimeoutError:
        logger.error(
            "ACP initialize timed out",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step="initialize",
                timeout_seconds=settings.acp_startup_timeout_seconds,
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
        raise
    if "error" in resp:
        # M22: use domain exception with explicit cause information
        logger.error(
            "ACP initialize returned an error",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step="initialize",
                timeout_seconds=settings.acp_startup_timeout_seconds,
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
        raise AcpSessionError(
            f"ACP initialize failed: {resp['error']}",
            code=resp["error"].get("code", AcpErrorCode.INTERNAL_ERROR)
            if isinstance(resp.get("error"), dict)
            else AcpErrorCode.INTERNAL_ERROR,
        )
    res = resp.get("result", {})
    return InitializeResult(
        agent_capabilities=res.get("agentCapabilities", {}),
        auth_methods=res.get("authMethods", []),
    )


async def setup_session(
    ctx: _AcpSessionContext,
    config: _AcpModelConfig,
    agent_capabilities: dict[str, Any],
    auth_methods: list[dict[str, Any]],
) -> SessionSetupResult:
    """Create or load an ACP session.

    Returns a ``SessionSetupResult`` with the session id and agent modes.
    Writes session-scoped mutables (``tool_calls``, ``agent_modes``) to
    ``ctx`` internally.
    """
    working_dir = config.workspace_root or config.cwd or str(Path.cwd())
    method = "session/new"
    params: dict[str, object] = {"cwd": working_dir, "mcpServers": config.mcp_servers}
    if config.allowed_tools:
        # ADR R4 (headless): auto-permit exactly the bridged authoring tools so
        # the CLI can invoke them without a local prompt. This is a recorded
        # approval policy, not a bypass — the real human gate is the engine
        # review lane, and the .vault deny policy still blocks fs writes.
        params["_meta"] = {
            "claudeCode": {"options": {"allowedTools": list(config.allowed_tools)}}
        }
        logger.info(
            "ACP auto-permitting bridged authoring tools (headless): %s",
            config.allowed_tools,
            extra=runtime_log_extra(config, process=ctx.process),
        )
    if config.session_id and agent_capabilities.get("loadSession"):
        method = "session/load"
        params["sessionId"] = config.session_id

    env = resolve_env_vars(Path(working_dir))
    env.update(config.env_vars)
    attempted_auth = False
    while True:
        rpc_id = AcpRequestId.SESSION_SETUP
        ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        async with ctx.stdin_lock:
            ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await ctx.stdin.drain()
        try:
            resp = await asyncio.wait_for(
                ctx.response_futures[rpc_id],
                timeout=settings.acp_startup_timeout_seconds,
            )
        except TimeoutError:
            logger.error(
                "ACP session setup timed out",
                extra=runtime_log_extra(
                    config,
                    process=ctx.process,
                    handshake_step=method,
                    timeout_seconds=settings.acp_startup_timeout_seconds,
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )
            raise
        if "error" not in resp:
            break
        err = resp["error"]
        err_code = (
            err.get("code", AcpErrorCode.INTERNAL_ERROR)
            if isinstance(err, dict)
            else AcpErrorCode.INTERNAL_ERROR
        )
        err_msg = str(err.get("message", err)) if isinstance(err, dict) else str(err)
        if not attempted_auth and auth_methods and is_auth_required_error(err):
            attempted_auth = True
            await authenticate_rpc(
                ctx=ctx,
                config=config,
                env=env,
                auth_methods=auth_methods,
                stdin=ctx.stdin,
                stdin_lock=ctx.stdin_lock,
                response_futures=ctx.response_futures,
                process=ctx.process,
                stderr_event_count=ctx.stderr_event_count,
                auth_url=ctx.auth_url,
            )
            continue
        if is_auth_required_error(err):
            logger.error(
                "ACP session setup requires authentication",
                extra=runtime_log_extra(
                    config,
                    process=ctx.process,
                    handshake_step=method,
                    timeout_seconds=settings.acp_startup_timeout_seconds,
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )
            hint = auth_hint(config)
            raise AcpSessionError(
                f"ACP {method} failed — authentication required. {hint}",
                code=err_code,
            )
        logger.error(
            "ACP session setup returned an error",
            extra=runtime_log_extra(
                config,
                process=ctx.process,
                handshake_step=method,
                timeout_seconds=settings.acp_startup_timeout_seconds,
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
        raise AcpSessionError(
            f"ACP {method} failed: {err_msg}",
            code=err_code,
        )
    res = resp["result"]
    session_id = res["sessionId"]
    agent_modes: dict[str, Any] = {}
    if modes := res.get("modes"):
        agent_modes = {
            "currentModeId": modes.get("currentModeId"),
            "availableModes": modes.get("availableModes", []),
        }
    ctx.tool_calls = {}
    ctx.agent_modes = agent_modes
    return SessionSetupResult(
        session_id=session_id,
        agent_modes=agent_modes,
    )


async def setup_prompt(
    ctx: _AcpSessionContext,
    _config: _AcpModelConfig,
    blocks: list[dict],
    active_session_id: str,
) -> asyncio.Future:
    """Send the initial prompt."""
    rpc_id = AcpRequestId.SESSION_PROMPT
    ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
    req = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "session/prompt",
        "params": {"sessionId": active_session_id, "prompt": blocks},
    }
    async with ctx.stdin_lock:
        ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.stdin.drain()
    ctx.prompt_id_ref.append(rpc_id)
    return ctx.response_futures[rpc_id]
