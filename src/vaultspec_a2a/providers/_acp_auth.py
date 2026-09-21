"""ACP authentication helpers and RPCs.

Extracted from ``_acp_session.py`` to isolate auth logic from
session lifecycle RPCs and data carriers.
"""

import asyncio
import json
import logging
from contextlib import suppress
from typing import Never, TypedDict, Unpack

from ..control.config import settings
from ..utils.enums import AcpRequestId
from ._acp_types import (
    AcpModelConfig,
    AcpResponseFuture,
    AcpResponseFutures,
    AcpSessionContext,
)
from ._json_contract import JsonObject, JsonValue, lenient_json_object
from .acp_exceptions import AcpAuthError, AcpErrorCode
from .conditions import ProviderCondition

__all__: list[str] = []

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinel / helpers
# ---------------------------------------------------------------------------


class _AuthResponseCancelledError(RuntimeError):
    """Raised when the authenticate response future is cancelled in-band."""


class _RuntimeLogOptions(TypedDict, total=False):
    process: asyncio.subprocess.Process | None
    handshake_step: str | None
    timeout_seconds: float | None
    session_id: str | None
    stderr_event_count: int | None
    exit_code: int | None
    kill_strategy: str | None


def runtime_log_extra(
    config: AcpModelConfig,
    **options: Unpack[_RuntimeLogOptions],
) -> dict[str, object]:
    """Build bounded ACP runtime metadata for structured logs."""
    process = options.get("process")
    handshake_step = options.get("handshake_step")
    timeout_seconds = options.get("timeout_seconds")
    session_id = options.get("session_id")
    stderr_event_count = options.get("stderr_event_count")
    exit_code = options.get("exit_code")
    kill_strategy = options.get("kill_strategy")
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
        # Telemetry never fabricates a directory: an unsited lane is reported
        # as absent rather than as whatever the serving process was started in.
        "cwd": config.workspace_root or "<no-active-project>",
    }
    if process is not None:
        extra["process_pid"] = process.pid
        extra["returncode"] = process.returncode
    extra.update(
        handshake_step=handshake_step,
        timeout_seconds=timeout_seconds,
        session_id=session_id,
        stderr_event_count=stderr_event_count,
        exit_code=exit_code,
        kill_strategy=kill_strategy,
    )
    return {key: value for key, value in extra.items() if value is not None}


# ---------------------------------------------------------------------------
# Auth helpers (free functions)
# ---------------------------------------------------------------------------


def auth_hint() -> str:
    """Return the authentication hint for supported ACP agents."""
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
    auth_methods: list[JsonObject],
) -> str:
    """Select the first authentication method advertised by the ACP agent."""
    method_ids: list[str] = [
        mid
        for method in auth_methods
        for mid in (method.get("id"),)
        if isinstance(mid, str)
    ]
    if not method_ids:
        return "oauth"
    return method_ids[0]


def is_auth_required_error(error: JsonValue) -> bool:
    """Return True when an ACP error indicates authentication is required."""
    if not isinstance(error, dict):
        return False
    err: JsonObject = error
    message = str(err.get("message", "")).lower()
    return bool(
        err.get("code") == AcpErrorCode.UNAUTHENTICATED
        or "authrequired" in message
        or "authentication required" in message
        or "unauthenticated" in message
        or "not authenticated" in message
    )


def is_auth_cancelled_error(error: JsonValue) -> bool:
    """Return True when an auth error indicates operator cancellation."""
    if not isinstance(error, dict):
        return False
    err: JsonObject = error
    message = str(err.get("message", "")).lower()
    return bool(
        "cancelled" in message
        or "canceled" in message
        or "aborted" in message
        or "closed by user" in message
    )


def is_auth_rejected_error(error: JsonValue) -> bool:
    """Return True when an auth error indicates explicit auth rejection."""
    if not isinstance(error, dict):
        return False
    err: JsonObject = error
    message = str(err.get("message", "")).lower()
    return bool(
        "access_denied" in message
        or "access denied" in message
        or "denied" in message
        or "rejected" in message
        or "declined" in message
    )


class _AuthOutcomeRequired(TypedDict):
    message: str
    code: int
    auth_outcome: str


class _AuthOutcomeOptions(_AuthOutcomeRequired, total=False):
    auth_url: str | None
    last_auth_url: str | None
    condition: ProviderCondition


def raise_auth_outcome_error(
    **options: Unpack[_AuthOutcomeOptions],
) -> Never:
    """Raise AcpAuthError with a bounded machine-readable auth outcome."""
    message = options["message"]
    code = options["code"]
    auth_outcome = options["auth_outcome"]
    auth_url = options.get("auth_url")
    last_auth_url = options.get("last_auth_url")
    condition = options.get("condition", ProviderCondition.UNKNOWN)
    raise AcpAuthError(
        f"{message}{auth_url_hint(auth_url, last_auth_url)}",
        code=code,
        data={"auth_outcome": auth_outcome},
        condition=condition,
    )


# ---------------------------------------------------------------------------
# Auth RPCs
# ---------------------------------------------------------------------------


class _AuthenticateRpcRequired(TypedDict):
    ctx: AcpSessionContext | None
    config: AcpModelConfig
    auth_methods: list[JsonObject]
    stdin: asyncio.StreamWriter
    stdin_lock: asyncio.Lock
    response_futures: AcpResponseFutures


class _AuthenticateRpcOptions(_AuthenticateRpcRequired, total=False):
    process: asyncio.subprocess.Process | None
    stderr_event_count: int | None
    auth_url: str | None


async def authenticate_rpc(
    **options: Unpack[_AuthenticateRpcOptions],
) -> JsonObject:
    """Send the ACP authenticate RPC using the advertised method."""
    ctx = options["ctx"]
    config = options["config"]
    auth_methods = options["auth_methods"]
    stdin = options["stdin"]
    stdin_lock = options["stdin_lock"]
    response_futures = options["response_futures"]
    process = options.get("process")
    stderr_event_count = options.get("stderr_event_count")
    auth_url = options.get("auth_url")
    last_auth_url = ctx.last_auth_url if ctx is not None else None
    if ctx is not None:
        ctx.last_auth_url = auth_url
    method_id = select_auth_method_id(auth_methods)
    rpc_id = AcpRequestId.AUTHENTICATE
    response_futures[rpc_id] = asyncio.get_running_loop().create_future()
    req: JsonObject = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "authenticate",
        "params": {"methodId": method_id},
    }
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
                f"{auth_hint()}"
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
            message=(f"Authentication ended before completion: {exc}. {auth_hint()}"),
            code=AcpErrorCode.INTERNAL_ERROR,
            auth_outcome="subprocess_exited_before_auth",
            auth_url=auth_url,
            last_auth_url=last_auth_url,
        )
    return _authenticate_result_or_raise(resp, auth_url, last_auth_url)


def _authenticate_result_or_raise(
    resp: JsonObject,
    auth_url: str | None,
    last_auth_url: str | None,
) -> JsonObject:
    """Map an ACP authentication response to its exact outcome."""
    if "error" in resp:
        raw_err = resp["error"]
        err: JsonObject = lenient_json_object(raw_err)
        err_msg = str(err.get("message", "")) if err else str(raw_err)
        raw_code = err.get("code")
        err_code = (
            raw_code
            if isinstance(raw_code, int) and not isinstance(raw_code, bool)
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
                condition=ProviderCondition.UNAUTHENTICATED,
            )
        raise_auth_outcome_error(
            message=f"Authentication failed: {err_msg}",
            code=err_code,
            auth_outcome="auth_failed",
            auth_url=auth_url,
            last_auth_url=last_auth_url,
            condition=ProviderCondition.UNAUTHENTICATED,
        )
    result = resp.get("result")
    return lenient_json_object(result)


async def wait_for_authenticate_response(
    *,
    response_future: AcpResponseFuture,
    process: asyncio.subprocess.Process | None,
    timeout_seconds: float,
) -> JsonObject:
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
