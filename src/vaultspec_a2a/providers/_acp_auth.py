"""ACP authentication helpers and RPCs.

Extracted from ``_acp_session.py`` (D-04) to isolate auth logic from
session lifecycle RPCs and data carriers.
"""

import asyncio
import json
import logging
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from ..control.config import settings
from ..utils.enums import AcpRequestId
from ._acp_types import _AcpModelConfig, _AcpSessionContext
from .acp_exceptions import AcpAuthError, AcpErrorCode

__all__: list[str] = []

logger = logging.getLogger(__name__)


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
# Auth RPCs
# ---------------------------------------------------------------------------


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
