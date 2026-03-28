"""ACP session lifecycle: config, context, auth helpers, and session RPCs.

Extracted from ``acp_chat_model.py`` (ADR D-04) to keep the LangChain
interface module under the 1,000-line mandate.  All functions are
free-standing — they receive ``_AcpModelConfig`` and/or
``_AcpSessionContext`` instead of ``self``.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from langchain_core.outputs import ChatGenerationChunk

from ..control.config import settings
from ..team.team_config import AgentConfig
from ..utils.enums import AcpRequestId
from ..workspace.environment import resolve_env_vars
from .acp_exceptions import (
    AcpAuthError,
    AcpErrorCode,
    AcpSessionError,
)

__all__: list[str] = []

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data carriers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AcpModelConfig:
    """Frozen snapshot of read-only ACP model configuration.

    Built once in ``AcpChatModel.model_post_init`` and threaded through
    every extracted free function so they never need a reference to the
    Pydantic model instance.
    """

    agent_config: AgentConfig | None
    permission_callback: Callable[..., Any] | None
    workspace_root: str | None
    cwd: str | None
    command: list[str]
    env_vars: dict[str, str]
    session_id: str | None
    mcp_servers: list[dict[str, Any]]
    use_exec: bool
    provider: str | None
    runtime_authority: str | None
    acp_backend: str | None
    command_origin: str | None
    command_kind: str | None
    command_executable: str | None
    command_target: str | None
    auth_mode: str | None


@dataclass
class _AcpSessionContext:
    """Consolidated state for an active ACP session."""

    process: asyncio.subprocess.Process
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader
    response_futures: dict[int, asyncio.Future]
    chunk_queue: asyncio.Queue[ChatGenerationChunk | None]
    prompt_done: asyncio.Event
    prompt_id_ref: list[int]
    interrupt_exc: list[BaseException]
    background_tasks: set[asyncio.Task] = field(default_factory=set)
    terminals: dict[str, asyncio.subprocess.Process] = field(default_factory=dict)
    stderr_event_count: int = 0
    auth_prompt_active: bool = False
    auth_url: str | None = None
    # Serialises all ctx.stdin.write() + drain() calls so concurrent background
    # RPC tasks cannot interleave writes and produce malformed JSON-RPC frames.
    stdin_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Session-scoped mutables (moved from AcpChatModel PrivateAttrs)
    tool_calls: dict[str, Any] = field(default_factory=dict)
    agent_modes: dict[str, Any] = field(default_factory=dict)
    last_auth_url: str | None = None


@dataclass(frozen=True)
class InitializeResult:
    """Return value of ``initialize_session``."""

    agent_capabilities: dict[str, Any]
    auth_methods: list[dict[str, Any]]


@dataclass(frozen=True)
class SessionSetupResult:
    """Return value of ``setup_session``."""

    session_id: str
    agent_modes: dict[str, Any]


# ---------------------------------------------------------------------------
# Sentinel / helpers
# ---------------------------------------------------------------------------


class _AuthResponseCancelledError(RuntimeError):
    """Raised when the authenticate response future is cancelled in-band."""


def _log_task_exception(task: asyncio.Task) -> None:
    """Log unhandled exceptions from fire-and-forget background RPC tasks."""
    if not task.cancelled() and (exc := task.exception()):
        logger.error("Background RPC task failed: %s", exc, exc_info=exc)


def runtime_log_extra(
    config: _AcpModelConfig,
    *,
    process: asyncio.subprocess.Process | None = None,
    handshake_step: str | None = None,
    timeout_seconds: float | None = None,
    session_id: str | None = None,
    stderr_event_count: int | None = None,
    exit_code: int | None = None,
    kill_strategy: str | None = None,
) -> dict[str, object]:
    """Build bounded ACP runtime metadata for structured logs."""
    extra: dict[str, object] = {
        "provider": config.provider,
        "runtime_authority": config.runtime_authority,
        "acp_backend": config.acp_backend,
        "command_origin": config.command_origin,
        "command_kind": config.command_kind,
        "command_executable": config.command_executable,
        "command_target": config.command_target,
        "auth_mode": config.auth_mode,
        "use_exec": config.use_exec,
        "workspace_root_present": bool(config.workspace_root),
        "cwd": config.workspace_root or config.cwd or str(Path.cwd()),
    }
    if process is not None:
        extra["process_pid"] = process.pid
        extra["returncode"] = process.returncode
    if handshake_step is not None:
        extra["handshake_step"] = handshake_step
    if timeout_seconds is not None:
        extra["timeout_seconds"] = timeout_seconds
    if session_id is not None:
        extra["session_id"] = session_id
    if stderr_event_count is not None:
        extra["stderr_event_count"] = stderr_event_count
    if exit_code is not None:
        extra["exit_code"] = exit_code
    if kill_strategy is not None:
        extra["kill_strategy"] = kill_strategy
    return {key: value for key, value in extra.items() if value is not None}


# ---------------------------------------------------------------------------
# Auth helpers (free functions)
# ---------------------------------------------------------------------------


def auth_hint(config: _AcpModelConfig) -> str:
    """Return a provider-specific authentication hint for error messages."""
    exe = config.command[0] if config.command else ""
    if "gemini" in exe:
        return (
            "To authenticate: set GEMINI_API_KEY or GOOGLE_API_KEY, provide "
            "GOOGLE_APPLICATION_CREDENTIALS for Vertex AI, or run `gemini` "
            "interactively and complete the OAuth flow."
        )
    # Default: Claude / node-based ACP
    return (
        "To authenticate: run `claude login` in your terminal, or set "
        "CLAUDE_CODE_OAUTH_TOKEN in your environment."
    )


def auth_url_hint(auth_url: str | None, last_auth_url: str | None) -> str:
    """Return a short browser-auth hint when an auth URL is available."""
    url = auth_url or last_auth_url
    if not url:
        return ""
    return f" Browser auth URL: {url}"


def select_auth_method_id(
    auth_methods: list[dict[str, Any]],
    env: Mapping[str, str],
    auth_mode: str | None,
) -> str:
    """Select the best advertised ACP auth method for the current env."""
    method_ids: list[str] = [
        mid
        for method in auth_methods
        if isinstance(method, dict)
        for mid in (method.get("id"),)
        if isinstance(mid, str)
    ]
    if not method_ids:
        return "oauth"
    if env.get("GEMINI_API_KEY") and "gemini-api-key" in method_ids:
        return "gemini-api-key"
    if (
        env.get("GOOGLE_GENAI_USE_VERTEXAI") == "true"
        or env.get("GOOGLE_APPLICATION_CREDENTIALS")
        or env.get("GOOGLE_API_KEY")
    ) and "vertex-ai" in method_ids:
        return "vertex-ai"
    if (
        env.get("GOOGLE_GENAI_USE_GCA") == "true"
        or env.get("GEMINI_CLI_HOME")
        or auth_mode in {"local_oauth_mount", "local_oauth_refresh"}
    ) and "oauth-personal" in method_ids:
        return "oauth-personal"
    return method_ids[0]


def is_auth_required_error(error: object) -> bool:
    """Return True when an ACP error indicates authentication is required."""
    if not isinstance(error, dict):
        return False
    err = cast("dict[str, Any]", error)
    message = str(err.get("message", "")).lower()
    return bool(
        err.get("code") == AcpErrorCode.UNAUTHENTICATED
        or "authrequired" in message
        or "authentication required" in message
        or "unauthenticated" in message
        or "not authenticated" in message
    )


def is_auth_cancelled_error(error: object) -> bool:
    """Return True when an auth error indicates operator cancellation."""
    if not isinstance(error, dict):
        return False
    err = cast("dict[str, Any]", error)
    message = str(err.get("message", "")).lower()
    return bool(
        "cancelled" in message
        or "canceled" in message
        or "aborted" in message
        or "closed by user" in message
    )


def is_auth_rejected_error(error: object) -> bool:
    """Return True when an auth error indicates explicit auth rejection."""
    if not isinstance(error, dict):
        return False
    err = cast("dict[str, Any]", error)
    message = str(err.get("message", "")).lower()
    return bool(
        "access_denied" in message
        or "access denied" in message
        or "denied" in message
        or "rejected" in message
        or "declined" in message
    )


def raise_auth_outcome_error(
    *,
    message: str,
    code: int,
    auth_outcome: str,
    auth_url: str | None = None,
    last_auth_url: str | None = None,
) -> None:
    """Raise AcpAuthError with a bounded machine-readable auth outcome."""
    raise AcpAuthError(
        f"{message}{auth_url_hint(auth_url, last_auth_url)}",
        code=code,
        data={"auth_outcome": auth_outcome},
    )


# ---------------------------------------------------------------------------
# Session lifecycle functions
# ---------------------------------------------------------------------------


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


async def authenticate_rpc(
    *,
    ctx: _AcpSessionContext | None,
    config: _AcpModelConfig,
    env: Mapping[str, str],
    auth_methods: list[dict[str, Any]],
    stdin: asyncio.StreamWriter,
    stdin_lock: asyncio.Lock,
    response_futures: dict[int, asyncio.Future],
    process: asyncio.subprocess.Process | None = None,
    stderr_event_count: int | None = None,
    auth_url: str | None = None,
) -> dict[str, object]:
    """Send the ACP authenticate RPC using the advertised method."""
    last_auth_url = ctx.last_auth_url if ctx is not None else None
    if ctx is not None:
        ctx.last_auth_url = auth_url
    method_id = select_auth_method_id(auth_methods, env, config.auth_mode)
    rpc_id = AcpRequestId.AUTHENTICATE
    response_futures[rpc_id] = asyncio.get_running_loop().create_future()
    req: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "authenticate",
        "params": {"methodId": method_id},
    }
    api_key = env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY")
    if api_key and method_id in {"gemini-api-key", "vertex-ai"}:
        req["_meta"] = {"api-key": api_key}
    logger.info(
        "Attempting ACP authenticate handshake",
        extra=runtime_log_extra(config, handshake_step="authenticate"),
    )
    async with stdin_lock:
        stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await stdin.drain()
    try:
        resp = await wait_for_authenticate_response(
            response_future=response_futures[rpc_id],
            process=process,
            timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
        )
    except TimeoutError:
        logger.error(
            "ACP authenticate timed out",
            extra=runtime_log_extra(
                config,
                process=process,
                handshake_step="authenticate",
                timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
                stderr_event_count=stderr_event_count,
            ),
        )
        raise_auth_outcome_error(
            message=(
                "Authentication did not complete before the interactive auth "
                f"watchdog expired after "
                f"{settings.acp_interactive_auth_timeout_seconds:.0f}s. "
                f"{auth_hint(config)}"
            ),
            code=AcpErrorCode.INTERNAL_ERROR,
            auth_outcome="watchdog_expired",
            auth_url=auth_url,
            last_auth_url=last_auth_url,
        )
    except _AuthResponseCancelledError:
        logger.warning(
            "ACP authenticate was cancelled",
            extra=runtime_log_extra(
                config,
                process=process,
                handshake_step="authenticate",
                timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
                stderr_event_count=stderr_event_count,
            ),
        )
        raise_auth_outcome_error(
            message="Authentication was cancelled before completion.",
            code=AcpErrorCode.INTERNAL_ERROR,
            auth_outcome="operator_cancelled",
            auth_url=auth_url,
            last_auth_url=last_auth_url,
        )
    except RuntimeError as exc:
        logger.error(
            "ACP authenticate ended before completion",
            extra=runtime_log_extra(
                config,
                process=process,
                handshake_step="authenticate",
                timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
                stderr_event_count=stderr_event_count,
            ),
        )
        raise_auth_outcome_error(
            message=(
                f"Authentication ended before completion: {exc}. {auth_hint(config)}"
            ),
            code=AcpErrorCode.INTERNAL_ERROR,
            auth_outcome="subprocess_exited_before_auth",
            auth_url=auth_url,
            last_auth_url=last_auth_url,
        )
    if "error" in resp:
        raw_err = resp["error"]
        err = cast("dict[str, Any]", raw_err) if isinstance(raw_err, dict) else {}
        err_msg = str(err.get("message", "")) if err else str(raw_err)
        err_code: int = (
            err.get("code", AcpErrorCode.INTERNAL_ERROR)
            if err
            else AcpErrorCode.INTERNAL_ERROR
        )
        if is_auth_cancelled_error(err):
            raise_auth_outcome_error(
                message=(f"Authentication was cancelled before completion: {err_msg}"),
                code=err_code,
                auth_outcome="operator_cancelled",
                auth_url=auth_url,
                last_auth_url=last_auth_url,
            )
        if is_auth_rejected_error(err):
            raise_auth_outcome_error(
                message=f"Authentication was explicitly rejected: {err_msg}",
                code=err_code,
                auth_outcome="auth_rejected",
                auth_url=auth_url,
                last_auth_url=last_auth_url,
            )
        raise_auth_outcome_error(
            message=f"Authentication failed: {err_msg}",
            code=err_code,
            auth_outcome="auth_failed",
            auth_url=auth_url,
            last_auth_url=last_auth_url,
        )
    result = resp.get("result")
    return cast("dict[str, object]", result) if isinstance(result, dict) else {}


async def wait_for_authenticate_response(
    *,
    response_future: asyncio.Future,
    process: asyncio.subprocess.Process | None,
    timeout_seconds: float,
) -> dict[str, object]:
    """Wait for auth completion, subprocess exit, or watchdog expiry."""
    if process is None:
        return await asyncio.wait_for(response_future, timeout=timeout_seconds)

    process_wait_task = asyncio.create_task(process.wait())
    try:
        done, _ = await asyncio.wait(
            {response_future, process_wait_task},
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if response_future in done:
            if response_future.cancelled():
                raise _AuthResponseCancelledError
            return await response_future
        if process_wait_task in done:
            exit_code = process_wait_task.result()
            if not response_future.done():
                response_future.cancel()
            raise RuntimeError(f"ACP subprocess exited with code {exit_code}")
        if not response_future.done():
            response_future.cancel()
        raise TimeoutError
    finally:
        if not process_wait_task.done():
            process_wait_task.cancel()
            with suppress(asyncio.CancelledError):
                await process_wait_task


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


async def send_notification(
    ctx: _AcpSessionContext,
    method: str,
    params: dict,
) -> None:
    """Send an ACP notification."""
    req = {"jsonrpc": "2.0", "method": method, "params": params}
    async with ctx.stdin_lock:
        ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.stdin.drain()
