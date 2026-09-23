"""ACP terminal RPC handler implementations.

Split out of ``_acp_rpc_handlers`` (module size). ``_acp_rpc_handlers``
re-exports the ``on_terminal_*`` handlers for its existing callers; the three
validation constants a test drives directly are public here and imported from
this module rather than through that facade. Contains the ``terminal/*`` RPC
handlers and the command, cwd, and environment validation they share.
"""

import asyncio
import logging
import re
import signal
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from ..utils.async_cleanup import complete_cleanup
from ..workspace.environment import resolve_env_vars
from ._acp_types import (
    AcpModelConfig,
    AcpRpcId,
    AcpSessionContext,
    require_workspace_root,
)
from ._json_contract import JsonObject, JsonValue, lenient_json_object_list
from ._subprocess import kill_process_tree as _kill_process_tree
from ._subprocess import spawn_acp_process
from .acp_exceptions import AcpErrorCode

__all__ = [
    "ENV_NAME_RE",
    "SHELL_METACHAR_RE",
    "TERMINAL_COMMAND_ALLOWLIST",
    "on_terminal_create",
    "on_terminal_kill",
    "on_terminal_output",
    "on_terminal_release",
    "on_terminal_wait_for_exit",
]

logger = logging.getLogger(__name__)

# Allowlist of permitted executable names for terminal/create.
# Only the base name (no path component) is checked so that full paths like
# /usr/bin/python3 or C:\Python313\python.exe are also accepted.
TERMINAL_COMMAND_ALLOWLIST: frozenset[str] = frozenset(
    {
        "python",
        "python3",
        "python3.13",
        "pip",
        "pip3",
        "git",
        "npm",
        "node",
        "npx",
        "uv",
        "uvicorn",
        "ruff",
        "mypy",
        "pytest",
        "bash",
        "sh",
        "zsh",
        "pwsh",
        "powershell",
        "cmd",
    }
)

# Shell metacharacters that must never appear in command or args strings
# when executing via create_subprocess_exec (defense-in-depth; exec does not
# invoke a shell but these chars indicate injection attempts).
SHELL_METACHAR_RE = re.compile(r"[|&;`$()<>]")

# Server-side cap for subprocess-supplied terminal wait_for_exit timeout.
_MAX_TERMINAL_TIMEOUT: float = 300.0

# Valid POSIX environment variable name pattern.
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _required_string(params: JsonObject, field: str) -> str:
    """Read one required string field from an ACP RPC payload."""
    value = params.get(field)
    if not isinstance(value, str):
        raise ValueError(f"ACP field {field!r} must be a string")
    return value


def _number(value: object, *, field: str) -> float:
    """Convert a JSON numeric/string field without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"ACP field {field!r} must be numeric")
    return float(value)


def _terminal_command_args(params: JsonObject) -> tuple[str, list[str]]:
    command = _required_string(params, "command")
    raw_args = params.get("args")
    if raw_args is None:
        args: list[str] = []
    elif isinstance(raw_args, list):
        args = [argument for argument in raw_args if isinstance(argument, str)]
        if len(args) != len(raw_args):
            raise ValueError("ACP field 'args' must be a list of strings")
    else:
        raise ValueError("ACP field 'args' must be a list of strings")

    cmd_base = Path(command).stem.lower()
    if cmd_base not in TERMINAL_COMMAND_ALLOWLIST:
        raise ValueError(
            f"Command {command!r} is not in the terminal allowlist. "
            f"Permitted executables: {sorted(TERMINAL_COMMAND_ALLOWLIST)}"
        )
    for token in [command, *args]:
        if SHELL_METACHAR_RE.search(str(token)):
            raise ValueError(
                f"Shell metacharacter detected in terminal token {token!r}. "
                "Command injection attempt rejected."
            )
    return command, args


def _terminal_cwd(params: JsonObject, config: AcpModelConfig) -> Path:
    requested_cwd = params.get("cwd")
    raw_cwd = (
        requested_cwd
        if isinstance(requested_cwd, str) and requested_cwd
        else str(
            require_workspace_root(config.workspace_root, surface="agent terminal cwd")
        )
    )
    sandbox_root = require_workspace_root(
        config.workspace_root, surface="agent terminal sandbox root"
    ).resolve()
    resolved_cwd = Path(raw_cwd).resolve()
    if not resolved_cwd.is_relative_to(sandbox_root):
        raise ValueError(
            f"Terminal cwd {raw_cwd!r} escapes sandbox root {sandbox_root}"
        )
    return resolved_cwd


def _terminal_env_list_overrides(extra_env: list[JsonValue]) -> dict[str, str]:
    validated_env: dict[str, str] = {}
    env_entries = lenient_json_object_list(extra_env)
    if len(env_entries) != len(extra_env):
        raise ValueError("ACP terminal env entries must be objects")
    for entry in env_entries:
        name = _required_string(entry, "name")
        value = _required_string(entry, "value")
        if not ENV_NAME_RE.match(name):
            raise ValueError(f"Invalid environment variable name: {name!r}")
        validated_env[name] = value
    return validated_env


def _terminal_env_dict_overrides(extra_env: dict[str, JsonValue]) -> dict[str, str]:
    validated_env: dict[str, str] = {}
    for name, value in extra_env.items():
        if not ENV_NAME_RE.match(name):
            raise ValueError(f"Invalid environment variable name: {name!r}")
        if not isinstance(value, str):
            raise ValueError(f"ACP terminal env value for {name!r} must be a string")
        validated_env[name] = value
    return validated_env


def _terminal_env_overrides(extra_env: JsonValue | None) -> dict[str, str]:
    if isinstance(extra_env, list) and extra_env:
        return _terminal_env_list_overrides(extra_env)
    if isinstance(extra_env, dict) and extra_env:
        return _terminal_env_dict_overrides(extra_env)
    return {}


def _terminal_environment(params: JsonObject, resolved_cwd: Path) -> dict[str, str]:
    terminal_env = resolve_env_vars(resolved_cwd)
    terminal_env.update(_terminal_env_overrides(params.get("env")))
    return terminal_env


async def on_terminal_create(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/create RPC.

    Validates that the working directory is within the sandbox, logs
    the command for audit purposes, then spawns the subprocess.
    Passes optional ``env`` overrides from params on top of the current
    environment so the subprocess inherits PATH and other required vars.
    """
    try:
        if ctx.closing:
            raise RuntimeError("ACP session is closing")
        command, args = _terminal_command_args(params)
        resolved_cwd = _terminal_cwd(params, config)

        # Audit log for all terminal commands
        logger.info(
            "terminal/create: command=%r args=%r cwd=%s",
            command,
            args,
            resolved_cwd,
        )

        # Build env: use resolve_env_vars() to scrub API credentials,
        # then apply any agent-supplied overrides from the RPC params.
        terminal_env = _terminal_environment(params, resolved_cwd)
        process = await spawn_acp_process(
            [command, *args], terminal_env, str(resolved_cwd), use_exec=True
        )
        try:
            if ctx.closing:
                raise RuntimeError("ACP session closed while creating terminal")
            terminal_id = uuid4().hex[:8]
            ctx.terminals[terminal_id] = process
        except BaseException:
            await _kill_process_tree(process)
            raise
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"terminalId": terminal_id},
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": str(exc)},
        }


def _resolve_terminal(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
) -> tuple[asyncio.subprocess.Process | None, JsonObject]:
    """Resolve ``params["terminalId"]`` to its live process, or to the refusal.

    Returns ``(process, refusal)``: on a hit the live process and an empty
    refusal, on a miss ``None`` and the ready-to-send JSON-RPC response. The
    caller branches on the process being ``None`` - which is what narrows it for
    the type checker - and returns the refusal verbatim.

    The refusal is protocol error-MAPPING, not framework preamble: its code, its
    message wording and its envelope are all wire contract, so every handler that
    addresses a live terminal by id owes an unknown one the same answer. Built in
    one place, a correction to any part of that contract cannot land in two of the
    three handlers and miss the third. The code comes from the canonical
    :class:`AcpErrorCode` rather than a literal, so the wire value has a single
    definition across the ACP surface.

    ``terminal/release`` is deliberately NOT a caller: releasing a terminal that
    is already gone is idempotent success, not an invalid-params refusal.
    """
    terminal_id_value = params.get("terminalId")
    terminal_id = terminal_id_value if isinstance(terminal_id_value, str) else ""
    process = ctx.terminals.get(terminal_id)
    if process is not None:
        return process, {}
    return None, {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {
            "code": AcpErrorCode.INVALID_PARAMS,
            "message": f"Unknown terminal: {terminal_id}",
        },
    }


def _signal_name(signal_number: int) -> str:
    """Name the signal that killed a process, for the v1 string ``signal`` field.

    ACP v1 types ``signal`` as a STRING, not the raw number the OS reports, so a
    reader is not left decoding platform-specific integers. The number is
    resolved through the stdlib enum where the running platform defines it and
    falls back to the bare digits otherwise - Windows defines only a handful of
    ``Signals`` members, and an unmappable number is still better reported than
    turned into an error on a path describing how a process already died.
    """
    try:
        return signal.Signals(signal_number).name
    except ValueError:
        return str(signal_number)


def _exit_status(process: asyncio.subprocess.Process) -> JsonObject | None:
    """Build the ACP v1 ``TerminalExitStatus`` for a process, or ``None``.

    Returns ``None`` while the process is still running, which is what lets
    ``terminal/output`` omit the optional field rather than assert an exit that
    has not happened.

    The two fields are mutually exclusive by construction. POSIX reports a
    signal death as a NEGATIVE return code, which is not a valid ``exitCode``
    (the schema types it as an unsigned integer), so that case reports a null
    exit code beside the named signal; a normal exit reports the code beside a
    null signal. Emitting the negative number as an ``exitCode`` - the shape
    this replaces - told a reader the process exited with a code it never
    returned.
    """
    returncode = process.returncode
    if returncode is None:
        return None
    if returncode < 0:
        return {"exitCode": None, "signal": _signal_name(-returncode)}
    return {"exitCode": returncode, "signal": None}


async def on_terminal_kill(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/kill RPC.

    Kill stops the command; it does NOT release the terminal. The id stays
    registered in ``ctx.terminals`` so the agent can still collect the output it
    killed the command to inspect and read its exit status. Only
    ``terminal/release`` ends addressability - see :func:`on_terminal_release`.
    """
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    await _kill_process_tree(process)
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}


async def on_terminal_output(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/output RPC."""
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    stdout_data = b""
    stderr_data = b""
    if process.stdout:
        with suppress(TimeoutError):
            stdout_data = await asyncio.wait_for(
                process.stdout.read(65536), timeout=0.5
            )
    if process.stderr:
        with suppress(TimeoutError):
            stderr_data = await asyncio.wait_for(
                process.stderr.read(65536), timeout=0.5
            )
    output_result: JsonObject = {
        "output": stdout_data.decode("utf-8", errors="replace")
        + stderr_data.decode("utf-8", errors="replace"),
        "truncated": False,
    }
    # The optional exitStatus is present only once the command has completed,
    # and is the v1 status OBJECT rather than a bare return code.
    if (exit_status := _exit_status(process)) is not None:
        output_result["exitStatus"] = exit_status
    return {"jsonrpc": "2.0", "id": rpc_id, "result": output_result}


async def on_terminal_wait_for_exit(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/wait_for_exit RPC."""
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    timeout = min(
        _number(params.get("timeout") or 60.0, field="timeout"), _MAX_TERMINAL_TIMEOUT
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": "Timeout waiting for exit"},
        }
    # The wait returned, so the process has exited and the status is never None;
    # the fallback keeps the response well-formed rather than raising on a path
    # that exists to report an outcome.
    exit_result = _exit_status(process) or {"exitCode": None, "signal": None}
    return {"jsonrpc": "2.0", "id": rpc_id, "result": exit_result}


async def on_terminal_release(
    rpc_id: AcpRpcId,
    params: JsonObject,
    ctx: AcpSessionContext,
    _config: AcpModelConfig,
) -> JsonObject:
    """Handle terminal/release RPC."""
    terminal_id_value = params.get("terminalId")
    terminal_id = terminal_id_value if isinstance(terminal_id_value, str) else ""
    process = ctx.terminals.get(terminal_id)
    if process is not None:

        async def _release() -> None:
            # An exited root can still own live descendants and native handles.
            await _kill_process_tree(process)
            if ctx.terminals.get(terminal_id) is process:
                del ctx.terminals[terminal_id]

        await complete_cleanup(_release())
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
