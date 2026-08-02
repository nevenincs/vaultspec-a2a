"""ACP session lifecycle RPCs: initialize, setup, and prompt.

Extracted from the original monolithic ``_acp_session.py``.
Data carriers live in ``_acp_types``, auth logic in ``_acp_auth``.
"""

import asyncio
import json
import logging
from pathlib import Path

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
    AcpModelConfig,
    AcpResponseFuture,
    AcpSessionContext,
    InitializeResult,
    SessionSetupResult,
)
from ._json_contract import JsonObject, JsonValue
from .acp_exceptions import AcpErrorCode, AcpSessionError

__all__: list[str] = []

logger = logging.getLogger(__name__)


def _json_object(value: JsonValue | None) -> JsonObject:
    """Return one protocol object or an empty object for malformed data."""
    return value if isinstance(value, dict) else {}


def _error_code(value: JsonValue | None) -> int:
    """Read one numeric JSON-RPC error code with the standard fallback."""
    code = _json_object(value).get("code")
    return (
        code
        if isinstance(code, int) and not isinstance(code, bool)
        else AcpErrorCode.INTERNAL_ERROR
    )


async def initialize_session(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> InitializeResult:
    """Send ACP initialize request and return capabilities + auth methods."""
    rpc_id = AcpRequestId.INITIALIZE
    ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
    req: JsonObject = {
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
                # Signal support for terminal-based auth and
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
            code=_error_code(resp.get("error")),
        )
    res = resp.get("result")
    result = _json_object(res)
    capabilities = result.get("agentCapabilities")
    auth_methods = result.get("authMethods")
    return InitializeResult(
        agent_capabilities=capabilities if isinstance(capabilities, dict) else {},
        auth_methods=[method for method in auth_methods if isinstance(method, dict)]
        if isinstance(auth_methods, list)
        else [],
    )


async def setup_session(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    agent_capabilities: JsonObject,
    auth_methods: list[JsonObject],
) -> SessionSetupResult:
    """Create or load an ACP session.

    Returns a ``SessionSetupResult`` with the session id and agent modes.
    Writes session-scoped mutables (``tool_calls``, ``agent_modes``) to
    ``ctx`` internally.
    """
    working_dir = config.workspace_root or config.cwd or str(Path.cwd())
    method = "session/new"
    mcp_servers = list[JsonValue](config.mcp_servers)
    params: JsonObject = {"cwd": working_dir, "mcpServers": mcp_servers}
    if config.allowed_tools and config.acp_family == "claude":
        # Claude family only (Claude/Z.ai): serialize the headless auto-permit
        # allowlist into the Claude-CLI-specific claudeCode namespace so the CLI
        # can invoke the composed tools without a local prompt. This is a recorded
        # approval policy, not a bypass — the real human gate is the engine review
        # lane, and the .vault deny policy still blocks fs writes.
        #
        # The kimi family OMITS this _meta: Kimi has no claudeCode/allowedTools
        # analogue, so the SAME composed names (still carried in
        # config.allowed_tools) are enforced at our session/request_permission
        # handler as an exact-name auto-approve set (P03.S10) instead.
        allowed_tools = list[JsonValue](config.allowed_tools)
        params["_meta"] = {"claudeCode": {"options": {"allowedTools": allowed_tools}}}
        logger.info(
            "ACP auto-permitting bridged authoring tools (headless): %s",
            config.allowed_tools,
            extra=runtime_log_extra(config, process=ctx.process),
        )
    if config.session_id and agent_capabilities.get("loadSession") is True:
        method = "session/load"
        params["sessionId"] = config.session_id

    env = resolve_env_vars(Path(working_dir))
    env.update(config.env_vars)
    attempted_auth = False
    while True:
        rpc_id = AcpRequestId.SESSION_SETUP
        ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req: JsonObject = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
            "params": params,
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
        err_code = _error_code(err)
        error = _json_object(err)
        err_msg = str(error.get("message", err)) if error else str(err)
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
    result = resp.get("result")
    if not isinstance(result, dict):
        raise AcpSessionError(
            f"ACP {method} succeeded without an object result",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    session_id = result.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise AcpSessionError(
            f"ACP {method} succeeded without a sessionId",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    agent_modes: JsonObject = {}
    if modes := result.get("modes"):
        if not isinstance(modes, dict):
            modes = {}
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
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
    blocks: list[JsonObject],
    active_session_id: str,
) -> AcpResponseFuture:
    """Send the initial prompt."""
    rpc_id = AcpRequestId.SESSION_PROMPT
    ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
    prompt = list[JsonValue](blocks)
    req: JsonObject = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "session/prompt",
        "params": {"sessionId": active_session_id, "prompt": prompt},
    }
    async with ctx.stdin_lock:
        ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.stdin.drain()
    ctx.prompt_id_ref.append(rpc_id)
    return ctx.response_futures[rpc_id]
