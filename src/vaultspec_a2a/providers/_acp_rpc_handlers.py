"""ACP RPC handler implementations.

Extracted from ``acp_chat_model.py`` (ADR D-06).  Contains permission,
filesystem, and terminal RPC handlers as free functions.  Constants are
placed next to their consumers.
"""

import asyncio
import logging
import re
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from langgraph.errors import GraphBubbleUp

from ..control.config import settings
from ..workspace.environment import resolve_env_vars
from ._acp_session import _AcpModelConfig, _AcpSessionContext
from ._subprocess import kill_process_tree as _kill_process_tree

__all__: list[str] = []

logger = logging.getLogger(__name__)

# Allowlist of permitted executable names for terminal/create.
# Only the base name (no path component) is checked so that full paths like
# /usr/bin/python3 or C:\Python313\python.exe are also accepted.
_TERMINAL_COMMAND_ALLOWLIST: frozenset[str] = frozenset(
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
_SHELL_METACHAR_RE = re.compile(r"[|&;`$()<>]")

# Valid POSIX environment variable name pattern (PROV-M3).
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sandbox_path(path: str, config: _AcpModelConfig) -> Path:
    """Resolve and sandbox a path to the agent cwd."""
    cwd = Path(config.workspace_root or config.cwd or str(Path.cwd()))
    resolved = (cwd / path).resolve()
    if not resolved.is_relative_to(cwd.resolve()):
        raise ValueError(f"Path {path!r} escapes sandbox")
    return resolved


async def on_request_permission(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
    config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle session/request_permission RPC."""
    options = params.get("options", [])
    tool_call = params.get("toolCall", {})
    name = tool_call.get("title", "unknown")
    args = tool_call.get("rawInput", {})

    if config.permission_callback:
        try:
            option_id = await config.permission_callback(name, args, options)
        except GraphBubbleUp as exc:
            ctx.interrupt_exc.append(exc)
            try:
                ctx.chunk_queue.put_nowait(None)
            except asyncio.QueueFull:
                logger.warning("Chunk queue full — dropping interrupt sentinel")
            # H9 fix: return a proper JSON-RPC denial response instead of
            # an empty dict `{}` which would produce a malformed frame.
            deny_id = next(
                (
                    o["optionId"]
                    for o in options
                    if "deny" in o.get("optionId", "").lower()
                ),
                options[-1]["optionId"] if options else "deny",
            )
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"outcome": {"optionId": deny_id, "outcome": "selected"}},
            }
        except Exception:
            logger.exception(
                "Permission callback raised; denying permission (fail-closed)"
            )
            # TOAD reference pattern: return a denial outcome (not a JSON-RPC
            # error) so the ACP subprocess can cleanly decline the tool call.
            # Prefer the first option whose id contains "deny"; fall back to
            # the last option in the list (conventionally the most restrictive).
            deny_id = next(
                (
                    o["optionId"]
                    for o in options
                    if "deny" in o.get("optionId", "").lower()
                ),
                options[-1]["optionId"] if options else "deny",
            )
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"outcome": {"optionId": deny_id, "outcome": "selected"}},
            }
    elif options and isinstance(options[0], dict) and "optionId" in options[0]:
        # M14: guard against malformed option dicts lacking optionId
        option_id = options[0]["optionId"]
    else:
        option_id = "allow_once"

    # M17: validate that option_id is among the offered options before returning.
    # Reject a callback-supplied id that is not in the options list to prevent
    # sending an invalid response to the ACP subprocess.
    valid_ids = {o.get("optionId") for o in options if isinstance(o, dict)}
    if valid_ids and option_id not in valid_ids:
        logger.warning(
            "Permission callback returned option_id=%r not in valid options %r; "
            "falling back to first option",
            option_id,
            sorted(valid_ids),
        )
        option_id = options[0]["optionId"]

    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"outcome": {"optionId": option_id, "outcome": "selected"}},
    }


async def on_fs_read_text_file(
    rpc_id: int | str,
    params: dict,
    config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle fs/read_text_file RPC.

    Supports optional ``offset`` (byte offset) and ``limit`` (byte count)
    params for partial reads, avoiding loading entire large files into memory.
    Uses asyncio.to_thread so blocking I/O does not stall the event loop.
    """
    try:
        file_path = sandbox_path(params["path"], config)
        offset: int = int(params.get("offset") or 0)
        limit: int | None = (
            int(params["limit"]) if params.get("limit") is not None else None
        )

        # ACP-03: cap reads at _FS_READ_MAX_BYTES.  When the caller also
        # supplies a limit, honour whichever is smaller.
        effective_limit = settings.acp_fs_read_max_bytes
        if limit is not None:
            effective_limit = min(limit, settings.acp_fs_read_max_bytes)

        def _read() -> str:
            with file_path.open(encoding="utf-8", errors="ignore") as fh:
                if offset:
                    fh.seek(offset)
                return fh.read(effective_limit)

        text = await asyncio.to_thread(_read)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": text}}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": str(exc)},
        }


async def on_fs_write_text_file(
    rpc_id: int | str,
    params: dict,
    config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle fs/write_text_file RPC.

    Acquires the global git mutex before writing to prevent races with
    concurrent git operations (ADR-001 §2). Uses asyncio.to_thread so
    blocking I/O does not stall the event loop.
    """
    from ..workspace.git_manager import _git_mutex

    try:
        file_path = sandbox_path(params["path"], config)
        content: str = params["content"]

        def _write() -> None:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        async with _git_mutex:
            await asyncio.to_thread(_write)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": str(exc)},
        }


async def on_terminal_create(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
    config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle terminal/create RPC.

    Validates that the working directory is within the sandbox, logs
    the command for audit purposes, then spawns the subprocess.
    Passes optional ``env`` overrides from params on top of the current
    environment so the subprocess inherits PATH and other required vars.
    """
    try:
        command = params["command"]
        args = params.get("args") or []

        # --- Security: command allowlist validation (C4) ----------------
        # Extract the base name without directory path and .exe suffix so
        # that both "python" and "/usr/bin/python3.13" resolve the same.
        cmd_base = Path(command).stem.lower()
        if cmd_base not in _TERMINAL_COMMAND_ALLOWLIST:
            raise ValueError(
                f"Command {command!r} is not in the terminal allowlist. "
                f"Permitted executables: {sorted(_TERMINAL_COMMAND_ALLOWLIST)}"
            )
        # Reject shell metacharacters in the command or any argument.
        for token in [command, *args]:
            if _SHELL_METACHAR_RE.search(str(token)):
                raise ValueError(
                    f"Shell metacharacter detected in terminal token {token!r}. "
                    "Command injection attempt rejected."
                )
        # ----------------------------------------------------------------

        # Sandbox the terminal cwd: must be within the agent workspace root.
        raw_cwd = (
            params.get("cwd") or config.workspace_root or config.cwd or str(Path.cwd())
        )
        sandbox_root = Path(
            config.workspace_root or config.cwd or str(Path.cwd())
        ).resolve()
        resolved_cwd = Path(raw_cwd).resolve()
        if not resolved_cwd.is_relative_to(sandbox_root):
            raise ValueError(
                f"Terminal cwd {raw_cwd!r} escapes sandbox root {sandbox_root}"
            )

        # Audit log for all terminal commands (ADR-001 §2)
        logger.info(
            "terminal/create: command=%r args=%r cwd=%s",
            command,
            args,
            resolved_cwd,
        )

        # Build env: use resolve_env_vars() to scrub API credentials (ACP-02),
        # then apply any agent-supplied overrides from the RPC params.
        terminal_env = resolve_env_vars(resolved_cwd)
        if extra_env := params.get("env"):
            if isinstance(extra_env, list):
                # ACP protocol: env is list[EnvVariable] with name/value keys
                # PROV-M3: validate env variable names before applying
                for v in extra_env:
                    if not _ENV_NAME_RE.match(v["name"]):
                        raise ValueError(
                            f"Invalid environment variable name: {v['name']!r}"
                        )
                terminal_env.update({v["name"]: v["value"] for v in extra_env})
            elif isinstance(extra_env, dict):
                for name in extra_env:
                    if not _ENV_NAME_RE.match(name):
                        raise ValueError(f"Invalid environment variable name: {name!r}")
                terminal_env.update(extra_env)
        # M12: on Windows, use CREATE_NEW_PROCESS_GROUP so child
        # processes don't become orphans when the terminal is killed.
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(resolved_cwd),
            env=terminal_env,
            creationflags=creation_flags,
        )
        terminal_id = uuid4().hex[:8]
        ctx.terminals[terminal_id] = process
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


async def on_terminal_kill(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
) -> dict[str, object]:
    """Handle terminal/kill RPC."""
    terminal_id = params.get("terminalId", "")
    process = ctx.terminals.get(terminal_id)
    if process is None:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {
                "code": -32602,
                "message": f"Unknown terminal: {terminal_id}",
            },
        }
    await _kill_process_tree(process)
    ctx.terminals.pop(terminal_id, None)
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}


async def on_terminal_output(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
) -> dict[str, object]:
    """Handle terminal/output RPC."""
    terminal_id = params.get("terminalId", "")
    process = ctx.terminals.get(terminal_id)
    if process is None:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {
                "code": -32602,
                "message": f"Unknown terminal: {terminal_id}",
            },
        }
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
    output_result: dict[str, object] = {
        "output": stdout_data.decode("utf-8", errors="replace")
        + stderr_data.decode("utf-8", errors="replace"),
        "truncated": False,
    }
    # Conditionally include exitStatus when the process has already exited
    if process.returncode is not None:
        output_result["exitStatus"] = process.returncode
    return {"jsonrpc": "2.0", "id": rpc_id, "result": output_result}


async def on_terminal_wait_for_exit(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
) -> dict[str, object]:
    """Handle terminal/wait_for_exit RPC."""
    terminal_id = params.get("terminalId", "")
    process = ctx.terminals.get(terminal_id)
    if process is None:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {
                "code": -32602,
                "message": f"Unknown terminal: {terminal_id}",
            },
        }
    timeout = params.get("timeout") or 60.0
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": "Timeout waiting for exit"},
        }
    exit_result: dict[str, object] = {"exitCode": process.returncode}
    # On Unix, negative returncode means the process was killed by a signal
    # (returncode == -signum). Include the signal number for completeness.
    if process.returncode is not None and process.returncode < 0:
        exit_result["signal"] = -process.returncode
    return {"jsonrpc": "2.0", "id": rpc_id, "result": exit_result}


async def on_terminal_release(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
) -> dict[str, object]:
    """Handle terminal/release RPC."""
    terminal_id = params.get("terminalId", "")
    process = ctx.terminals.pop(terminal_id, None)
    if process is not None and process.returncode is None:
        await _kill_process_tree(process)
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
