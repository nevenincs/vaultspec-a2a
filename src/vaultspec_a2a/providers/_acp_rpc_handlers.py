"""ACP RPC handler implementations.

Extracted from ``acp_chat_model.py``.  Contains permission,
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
from ..graph.acp_options import option_id_of, valid_option_ids
from ..utils.process import ProcessContainment, ProcessContainmentError
from ..workspace.environment import resolve_env_vars
from ._acp_types import _AcpModelConfig, _AcpSessionContext
from ._subprocess import _CONTAINMENT_ATTR
from ._subprocess import kill_process_tree as _kill_process_tree
from .acp_exceptions import AcpErrorCode

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

# Server-side cap for subprocess-supplied terminal wait_for_exit timeout.
_MAX_TERMINAL_TIMEOUT: float = 300.0

# Valid POSIX environment variable name pattern.
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sandbox_path(path: str, config: _AcpModelConfig) -> Path:
    """Resolve and sandbox a path to the agent cwd."""
    cwd = Path(config.workspace_root or config.cwd or str(Path.cwd()))
    resolved = (cwd / path).resolve()
    if not resolved.is_relative_to(cwd.resolve()):
        raise ValueError(f"Path {path!r} escapes sandbox")
    return resolved


def _targets_vault(file_path: Path, _config: _AcpModelConfig) -> bool:
    """Return True if a sandbox-resolved path lies within any ``.vault`` dir.

    Agents may not write the vault corpus through their coding-CLI file
    tools. ``file_path`` is already ``.resolve()``-d and confined to the agent
    cwd by :func:`sandbox_path`, so symlinks and ``..`` traversal are already
    collapsed to a real path under the workspace. We deny if ANY component of
    the resolved ABSOLUTE path is ``.vault`` — compared case-insensitively via
    ``casefold()`` because the Windows/macOS filesystems are case-insensitive (a
    ``.VAULT`` write resolves to the same directory).

    Checking the absolute path (not the workspace-relative one) closes the case
    where the workspace root is ITSELF rooted inside a ``.vault`` ancestor: such
    a workspace makes every write a vault write even though no ``.vault``
    component appears relative to the root. It also still catches a ``.vault``
    dir nested under the workspace.
    """
    return any(part.casefold() == ".vault" for part in file_path.parts)


def _vault_write_denial(rpc_id: int | str, path: str) -> dict[str, object]:
    """Build the value-typed ``.vault`` write denial.

    Mirrors the engine's ``forbidden_actor`` 200-value shape (wire-shapes
    reference §2): a value-typed ``result`` carrying a snake_case
    ``denial_kind`` beside a human-readable ``eligibility.reason`` that names
    the authoring tools as the correct path — never a bare JSON-RPC error, so
    the agent is steered rather than left retrying a failed write.
    """
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "status": "denied",
            "denial_kind": "forbidden_actor",
            "eligibility": {
                "command": "fs/write_text_file",
                "allowed": False,
                "reason": (
                    "Agents may not write .vault/ files directly. Propose the "
                    "change through the authoring tools (propose_changeset / "
                    "append_draft / replace_draft); a human reviews and applies "
                    "it in the dashboard."
                ),
            },
            "path": path,
        },
    }


# Kimi's native READ tools that mirror the tool-cores read floor (Claude's
# Read/Grep/Glob), enumerated from the installed kimi-cli 1.49.0 source and
# cross-checked against executor-service's P04.S15 verification:
#   ReadFile (tools/file/read.py:64), Grep (tools/file/grep_local.py:386),
#   Glob (tools/file/glob.py:56)
# NOTE the name divergence from Claude: Kimi's read tool is `ReadFile`, not `Read`.
# The write tools WriteFile/StrReplaceFile, the bash/shell exec tool, and every
# plan/dmail/agent/todo mutator are NOT listed and are rejected in autonomous mode.
# `ReadMediaFile` (image reads) and the web tools FetchURL/SearchWeb are read-only
# but DELIBERATELY EXCLUDED: neither is part of the text-grounding floor (Kimi has
# no Claude-floor analogue for them), so the conservative posture omits them.
_KIMI_NATIVE_READ_TOOLS: frozenset[str] = frozenset({"ReadFile", "Grep", "Glob"})


def _strip_mcp_prefix(tool_name: str) -> str:
    """Reduce a Claude-form ``mcp__<server>__<tool>`` allowlist entry to the raw
    tool name Kimi exposes. Kimi registers MCP tools by their RAW ``mcp_tool.name``
    (kimi-cli ``soul/toolset.py`` ``MCPTool.name = mcp_tool.name``), so its
    permission title carries ``search_vault``, not ``mcp__vaultspec-rag__search_vault``.
    """
    if tool_name.startswith("mcp__"):
        return tool_name.split("__", 2)[-1]
    return tool_name


def _option_id_at(options: list, index: int, *, default: str) -> str:
    """Return the id of the option at ``index``, or ``default`` if it has none.

    Positional, never scanning: these call sites pick an option by CONVENTION
    (first is the least restrictive, last the most), so silently sliding to a
    neighbour when the conventional entry is malformed would substitute an
    option with the opposite meaning. Reading the id through the canonical
    extractor instead of subscripting is what keeps a malformed entry from
    raising ``KeyError`` on a path that exists to handle malformed input.
    """
    if not options:
        return default
    return option_id_of(options[index]) or default


def _first_offered_option_id(options: list, *, default: str) -> str:
    """Return the first option id actually offered, or ``default`` if none is.

    Unlike :func:`_option_id_at` this scans, because its caller has already
    established that SOME id is on offer and only needs a real one.
    """
    return next(
        (option_id for option in options if (option_id := option_id_of(option))),
        default,
    )


def _denial_option_id(options: list) -> str:
    """Return the id of the most restrictive offered option.

    Prefer the first option whose id names a denial; fall back to the last
    option in the list (conventionally the most restrictive), then to the
    literal ``"deny"``. The literal is the deliberate answer when the last
    option is malformed: an id the agent does not recognise makes it decline
    the tool call, whereas scanning back down the list for any usable id could
    hand this fail-closed path an APPROVAL.
    """
    return next(
        (
            option_id
            for option in options
            if (option_id := option_id_of(option)) and "deny" in option_id.lower()
        ),
        _option_id_at(options, -1, default="deny"),
    )


def _kimi_autonomous_option_id(
    name: str, config: _AcpModelConfig, options: list
) -> str:
    """Return the option id for a Kimi autonomous permission decision.

    Read-only enforcement re-expressed at our RPC layer for a lane whose CLI
    carries no config allowlist: auto-approve EXACTLY the composed read tools
    (raw MCP tool names from ``config.allowed_tools``) plus Kimi's native read
    tools; reject every other request. The tool identity is the prefix of Kimi's
    ``get_title()`` (``"ToolName: subtitle"`` or ``"ToolName"``).
    """
    canonical = name.split(": ", 1)[0]
    allowed = {_strip_mcp_prefix(t) for t in config.allowed_tools} | (
        _KIMI_NATIVE_READ_TOOLS
    )
    if canonical in allowed:
        return next(
            (
                option_id
                for option in options
                if isinstance(option, dict)
                and option.get("kind") in ("allow_once", "allow_always")
                and (option_id := option_id_of(option))
            ),
            _option_id_at(options, 0, default="approve"),
        )
    return next(
        (
            option_id
            for option in options
            if isinstance(option, dict)
            and (option_id := option_id_of(option))
            and (
                option.get("kind") in ("reject_once", "reject_always")
                or "reject" in option_id.lower()
                or "deny" in option_id.lower()
            )
        ),
        _option_id_at(options, -1, default="reject"),
    )


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

    # Diagnostic (R7: tool name + option ids only, never rawInput/payloads):
    # this handler firing means the SDK's canUseTool rung was reached — i.e. no
    # allow-rule pre-empted the call. Logging it disambiguates which permission
    # rung resolved a bridged authoring tool during headless runs.
    logger.info(
        "ACP permission requested (canUseTool rung): tool=%s options=%s",
        name,
        sorted(valid_option_ids(options)),
    )

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
            deny_id = _denial_option_id(options)
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
            deny_id = _denial_option_id(options)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"outcome": {"optionId": deny_id, "outcome": "selected"}},
            }
    elif config.acp_family == "kimi":
        # Autonomous (no permission_callback) Kimi lane: enforce read-only as an
        # exact-name auto-approve set at our RPC handler, because Kimi's CLI has
        # no config allowlist. Auto-approve exactly the composed read tools plus
        # Kimi's native read tools; reject everything else. Blanket approve is
        # NOT used - a read-only-only compose still leaves Kimi's native write
        # and shell tools reachable, so the enforcement is what the agent CAN do.
        option_id = _kimi_autonomous_option_id(name, config, options)
    else:
        # M14: an option list whose leading entry carries no usable id falls back
        # to the conventional allow-once id rather than subscripting it.
        option_id = _option_id_at(options, 0, default="allow_once")

    # M17: validate that option_id is among the offered options before returning.
    # Reject a callback-supplied id that is not in the options list to prevent
    # sending an invalid response to the ACP subprocess. The valid set is built
    # by the canonical predicate, so an option dict missing its id contributes
    # nothing instead of admitting ``None`` as a "valid" answer.
    valid_ids = valid_option_ids(options)
    if valid_ids and option_id not in valid_ids:
        logger.warning(
            "Permission callback returned option_id=%r not in valid options %r; "
            "falling back to first option",
            option_id,
            sorted(valid_ids),
        )
        option_id = _first_offered_option_id(options, default=option_id)

    logger.info("ACP permission decision: tool=%s option=%s", name, option_id)
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"outcome": {"optionId": option_id, "outcome": "selected"}},
    }


async def on_fs_read_text_file(
    rpc_id: int | str,
    params: dict,
    _ctx: _AcpSessionContext,
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

        # Cap reads at _FS_READ_MAX_BYTES.  When the caller also
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
    _ctx: _AcpSessionContext,
    config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle fs/write_text_file RPC.

    Acquires the global git mutex before writing to prevent races with
    concurrent git operations. Uses asyncio.to_thread so
    blocking I/O does not stall the event loop.
    """
    from ..workspace.concurrency import git_workspace_mutex

    try:
        file_path = sandbox_path(params["path"], config)

        # Deny agent writes into the vault corpus. Returns a value-typed
        # forbidden_actor denial (not a transport error) so the agent is steered
        # to the authoring tools. Reads (on_fs_read_text_file) stay permitted.
        if _targets_vault(file_path, config):
            logger.info(
                "Denied .vault/ write via ACP fs (R2 forbidden_actor): %r",
                params["path"],
            )
            return _vault_write_denial(rpc_id, params["path"])

        content: str = params["content"]

        def _write() -> None:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        async with git_workspace_mutex:
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

        # Audit log for all terminal commands
        logger.info(
            "terminal/create: command=%r args=%r cwd=%s",
            command,
            args,
            resolved_cwd,
        )

        # Build env: use resolve_env_vars() to scrub API credentials,
        # then apply any agent-supplied overrides from the RPC params.
        terminal_env = resolve_env_vars(resolved_cwd)
        if extra_env := params.get("env"):
            if isinstance(extra_env, list):
                # ACP protocol: env is list[EnvVariable] with name/value keys
                # Validate env variable names before applying
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
        # Seat the terminal child in its own OS containment before it runs, so the
        # whole terminal subtree (a shell and anything it spawns) is reaped as one
        # by `_kill_process_tree` - a POSIX process-group killpg escalation or a
        # Windows Job Object - not a per-pid kill that would orphan a POSIX shell's
        # grandchildren. Without this the terminal child carried no containment and
        # fell back to the single-pid POSIX path.
        containment = ProcessContainment.create()
        # The containment is an OS handle on Windows, allocated before the spawn
        # it contains. Everything from here to the point the terminal is
        # registered can raise - the spawn itself, an unexpected assignment
        # failure - and the outer handler converts any of it into an RPC error
        # the caller sees as a refused terminal. A refused terminal that left a
        # job handle open leaks one per attempt for the life of the session, so
        # the handle is released on the way out, along with any process that did
        # start (which nothing would otherwise reach: it is not yet in
        # ``ctx.terminals``, so terminal/release could never find it).
        try:
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd),
                env=terminal_env,
                creationflags=creation_flags,
                **containment.spawn_kwargs(),
            )
        except BaseException:
            containment.close()
            raise
        try:
            try:
                containment.assign(process.pid)
            except ProcessContainmentError:
                logger.warning(
                    "Could not seat terminal child PID %d in its OS containment;"
                    " termination will fall back to a per-pid tree kill",
                    process.pid,
                    exc_info=True,
                )
            setattr(process, _CONTAINMENT_ATTR, containment)
            terminal_id = uuid4().hex[:8]
            ctx.terminals[terminal_id] = process
        except BaseException:
            await containment.terminate(term_timeout=5.0, kill_timeout=5.0)
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
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
) -> tuple[asyncio.subprocess.Process | None, dict[str, object]]:
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
    terminal_id = params.get("terminalId", "")
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


async def on_terminal_kill(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
    _config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle terminal/kill RPC."""
    terminal_id = params.get("terminalId", "")
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    await _kill_process_tree(process)
    ctx.terminals.pop(terminal_id, None)
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}


async def on_terminal_output(
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
    _config: _AcpModelConfig,
) -> dict[str, object]:
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
    _config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle terminal/wait_for_exit RPC."""
    process, refusal = _resolve_terminal(rpc_id, params, ctx)
    if process is None:
        return refusal
    timeout = min(float(params.get("timeout") or 60.0), _MAX_TERMINAL_TIMEOUT)
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
    _config: _AcpModelConfig,
) -> dict[str, object]:
    """Handle terminal/release RPC."""
    terminal_id = params.get("terminalId", "")
    process = ctx.terminals.pop(terminal_id, None)
    if process is not None and process.returncode is None:
        await _kill_process_tree(process)
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
