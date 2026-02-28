r"""AcpChatModel: A LangChain BaseChatModel that wraps ACP-compatible CLIs.

Architecture:
  - Spawns CLI via ``_spawn_acp_process`` (platform-specific — see below)
  - Sends JSON-RPC requests on stdin using `b"%s\n"` format
  - Reads stdout in a walrus readline loop
  - Dispatches responses to asyncio.Future-based waiters
  - Handles bidirectional RPCs (session/request_permission)
  - Yields streaming `agent_message_chunk` notifications as LangChain chunks
  - Maps `tool_call` / `tool_call_update` to ToolCallChunk for LangGraph
  - Supports session/load for session resumption
  - Supports session/cancel notification for interruption
  - Terminates on `stopReason: "end_turn"`
  - Propagates LangGraph GraphBubbleUp from permission_callback to caller
"""

import asyncio
import json
import logging
import os
import subprocess
import sys

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import (
    BaseChatModel,
    generate_from_stream,
)
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langgraph.errors import GraphBubbleUp
from pydantic import Field, PrivateAttr

from ..core.team_config import AgentConfig
from ..utils.enums import AcpRequestId
from .acp_exceptions import (
    AcpError,
    AcpErrorCode,
    AcpPromptError,
)
from .gemini_auth import refresh_gemini_token


__all__ = ["AcpChatModel"]

logger = logging.getLogger(__name__)

# Map RPC method -> AgentCapabilities attribute name.
# Used for defense-in-depth capability checks at dispatch time
# (in addition to the clientCapabilities declared at initialize time).
_CAPABILITY_REQUIREMENTS: dict[str, str] = {
    "fs/read_text_file": "filesystem_read",
    "fs/write_text_file": "filesystem_write",
    "terminal/create": "terminal",
    "terminal/kill": "terminal",
    "terminal/output": "terminal",
    "terminal/wait_for_exit": "terminal",
    "terminal/release": "terminal",
}


def _log_task_exception(task: asyncio.Task) -> None:
    """Log unhandled exceptions from fire-and-forget background RPC tasks."""
    if not task.cancelled() and (exc := task.exception()):
        logger.error("Background RPC task failed: %s", exc, exc_info=exc)


async def _spawn_acp_process(
    command: list[str],
    env: dict[str, str],
    cwd: str,
) -> asyncio.subprocess.Process:
    """Spawn an ACP subprocess with platform-appropriate isolation.

    Windows: ``create_subprocess_shell`` with ``CREATE_NEW_PROCESS_GROUP`` so
    that ``.cmd`` shims (e.g. ``gemini.cmd``) work AND the full process tree
    (cmd.exe + node.exe + any grandchildren) can be atomically reaped via
    ``taskkill /T /F`` in ``_kill_process_tree``.

    Unix/Linux/macOS: ``create_subprocess_exec`` — no shell intermediary;
    POSIX signals (SIGTERM/SIGKILL) deliver directly to the target process.
    """
    kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": env,
        "cwd": cwd,
        "limit": 10 * 1024 * 1024,
    }
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP isolates console-signal handling so that
        # Ctrl+C in the parent terminal cannot propagate into the subprocess
        # group. list2cmdline escapes args for cmd.exe to prevent metachar
        # injection when model names or paths contain special characters.
        return await asyncio.create_subprocess_shell(
            subprocess.list2cmdline(command),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            **kwargs,
        )
    return await asyncio.create_subprocess_exec(command[0], *command[1:], **kwargs)


async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    """Terminate an ACP subprocess and its entire process tree.

    Windows: ``process.terminate()`` and ``process.kill()`` both call
    ``TerminateProcess()`` on the **immediate** child (cmd.exe) only.
    node.exe and any grandchildren survive as orphans, holding memory and
    file handles indefinitely.  ``taskkill /T /F /PID`` kills the whole
    tree atomically and is the only reliable approach.

    Unix/Linux/macOS: SIGTERM with a 5-second escalation to SIGKILL is
    sufficient because ACP agents do not spawn independent child processes.

    The asyncio transport handle is closed last in both paths to prevent
    OS handle leaks when the event loop finalizer runs (cpython#114177).
    """
    if sys.platform == "win32":
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/T", "/F", "/PID", str(process.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(killer.wait(), timeout=5.0)
        except Exception:
            with suppress(OSError):
                process.kill()
        with suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=5.0)
    else:
        with suppress(OSError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            logger.warning(
                "ACP process %s did not exit after SIGTERM; escalating to SIGKILL",
                process.pid,
            )
            with suppress(OSError):
                process.kill()
            await process.wait()

    transport = getattr(process, "_transport", None)
    if transport is not None:
        transport.close()


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
    prompt_error_ref: list[dict]
    interrupt_exc: list[BaseException]
    background_tasks: set[asyncio.Task] = field(default_factory=set)
    terminals: dict[str, asyncio.subprocess.Process] = field(default_factory=dict)
    # Serialises all ctx.stdin.write() + drain() calls so concurrent background
    # RPC tasks cannot interleave writes and produce malformed JSON-RPC frames.
    stdin_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AcpChatModel(BaseChatModel):
    """A custom LangChain ChatModel that wraps ACP-compatible CLI agents."""

    command: list[str] = Field(
        description="The command and arguments to launch the ACP agent."
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject (e.g., OAuth tokens).",
    )
    session_id: str | None = Field(
        default=None,
        description="If set, resume an existing session via session/load.",
    )
    mcp_servers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="MCP server configs to pass via session/new or session/load.",
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory for the agent session.",
    )
    permission_callback: Callable[..., Any] | None = Field(
        default=None,
        description="Optional async callback for custom permission handling.",
        exclude=True,
    )
    agent_config: AgentConfig | None = Field(
        default=None,
        description=(
            "Agent configuration driving ACP clientCapabilities flags. "
            "When None, all capability flags default to False (backward-compat)."
        ),
        exclude=True,
    )
    workspace_root: str | None = Field(
        default=None,
        description="Workspace root override for CWD resolution (ADR-014).",
        exclude=True,
    )

    # --- Runtime state (private, not model fields) ---
    _process: asyncio.subprocess.Process | None = PrivateAttr(default=None)
    _stdin: asyncio.StreamWriter | None = PrivateAttr(default=None)
    _active_session_id: str | None = PrivateAttr(default=None)
    _response_futures: dict[int, asyncio.Future] | None = PrivateAttr(default=None)
    _agent_capabilities: dict[str, Any] = PrivateAttr(default_factory=dict)
    _auth_methods: list[dict[str, Any]] = PrivateAttr(default_factory=list)
    _agent_modes: dict[str, Any] = PrivateAttr(default_factory=dict)
    _tool_calls: dict[str, Any] = PrivateAttr(default_factory=dict)

    def model_post_init(self, __context: object) -> None:
        """Initialize mutable instance attributes after Pydantic validation."""
        self._agent_capabilities = {}
        self._auth_methods = []
        self._agent_modes = {}
        self._tool_calls = {}

    @property
    def _llm_type(self) -> str:
        return "acp-chat-model"

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Streams responses from the ACP subprocess."""
        prompt_blocks: list[dict[str, str]] = []
        for msg in messages:
            if isinstance(
                msg, (HumanMessage, SystemMessage, ChatMessage, AIMessageChunk)
            ):
                prompt_blocks.append({"type": "text", "text": str(msg.content)})

        env = os.environ.copy()
        env.update(self.env_vars)
        env.pop("CLAUDECODE", None)  # Prevent nested session abort

        if "gemini" in self.command:
            refresh_gemini_token()

        process = await _spawn_acp_process(
            self.command,
            env,
            self.workspace_root or self.cwd or str(Path.cwd()),
        )

        assert process.stdin is not None
        assert process.stdout is not None
        ctx = _AcpSessionContext(
            process=process,
            stdin=process.stdin,
            stdout=process.stdout,
            response_futures={},
            chunk_queue=asyncio.Queue(maxsize=1024),
            prompt_done=asyncio.Event(),
            prompt_id_ref=[],
            prompt_error_ref=[],
            interrupt_exc=[],
        )

        stderr_task = asyncio.create_task(self._read_stderr_loop(process))
        stdout_task = asyncio.create_task(self._process_stdout_loop(ctx))

        try:
            await self._initialize_session(ctx)
            await self._setup_session(ctx)
            prompt_future = await self._setup_prompt(prompt_blocks, ctx)

            async for chunk in self._yield_chunks(ctx, prompt_future, run_manager):
                yield chunk
        finally:
            await self._cleanup_session(ctx, stdout_task, stderr_task)

    async def _yield_chunks(
        self,
        ctx: _AcpSessionContext,
        prompt_future: asyncio.Future,
        run_manager: AsyncCallbackManagerForLLMRun | None,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Poll the chunk queue and yield results."""
        while not ctx.prompt_done.is_set():
            try:
                chunk = await asyncio.wait_for(ctx.chunk_queue.get(), timeout=0.1)
                if chunk is None:
                    if ctx.interrupt_exc:
                        raise ctx.interrupt_exc[0]
                    if prompt_future.done():
                        resp = prompt_future.result()
                        if "error" in resp:
                            err = resp["error"]
                            raise AcpPromptError(
                                f"ACP prompt failed: {err}",
                                code=err.get("code", AcpErrorCode.INTERNAL_ERROR),
                                data=err.get("data"),
                            )
                    raise AcpError("ACP subprocess exited before end_turn")
                if run_manager:
                    token = chunk.message.content
                    await run_manager.on_llm_new_token(
                        token if isinstance(token, str) else "", chunk=chunk
                    )
                yield chunk
            except TimeoutError:
                if prompt_future.done():
                    resp = prompt_future.result()
                    if "error" in resp:
                        err = resp["error"]
                        raise AcpPromptError(
                            f"ACP prompt failed: {err}",
                            code=err.get("code", AcpErrorCode.INTERNAL_ERROR),
                            data=err.get("data"),
                        ) from None
                continue

        while not ctx.chunk_queue.empty():
            chunk = ctx.chunk_queue.get_nowait()
            if chunk is not None:
                if run_manager:
                    token = chunk.message.content
                    await run_manager.on_llm_new_token(
                        token if isinstance(token, str) else "", chunk=chunk
                    )
                yield chunk

    async def _cleanup_session(
        self,
        ctx: _AcpSessionContext,
        stdout_task: asyncio.Task,
        stderr_task: asyncio.Task,
    ) -> None:
        """Terminate subprocess and clean up tasks."""
        # Kill all spawned terminals before cancelling the session
        for _tid, proc in list(ctx.terminals.items()):
            with suppress(Exception):
                proc.kill()
                await proc.wait()
        ctx.terminals.clear()

        if self._active_session_id and not ctx.prompt_done.is_set():
            with suppress(Exception):
                # ADR-006 §5.1 pt 6: session/cancel must be a proper JSON-RPC
                # (with id) and awaited with a 3-second timeout so the subprocess
                # has a chance to flush its state before we kill it.
                rpc_id = AcpRequestId.SESSION_CANCEL
                loop = asyncio.get_running_loop()
                ctx.response_futures[rpc_id] = loop.create_future()
                req = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "method": "session/cancel",
                    "params": {"sessionId": self._active_session_id},
                }
                async with ctx.stdin_lock:
                    ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
                    await ctx.stdin.drain()
                await asyncio.wait_for(ctx.response_futures[rpc_id], timeout=3.0)

        stdout_task.cancel()
        stderr_task.cancel()
        await _kill_process_tree(ctx.process)

        self._process = None
        self._response_futures = None
        self._active_session_id = None
        self._tool_calls = {}

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Collect _astream chunks into a ChatResult."""
        chunks: list[ChatGenerationChunk] = []
        async for chunk in self._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            chunks.append(chunk)
        return generate_from_stream(iter(chunks))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Synchronous generate not supported."""
        raise NotImplementedError("AcpChatModel only supports async.")

    @property
    def _identifying_params(self) -> Mapping[str, object]:
        return {"command": self.command}

    def _require_session(self) -> str:
        if self._process is None or self._active_session_id is None:
            raise RuntimeError("No active session.")
        return self._active_session_id

    def _require_stdin(self) -> asyncio.StreamWriter:
        if self._stdin is None:
            raise RuntimeError("No active session stdin.")
        return self._stdin

    async def _read_stderr_loop(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        while line := await process.stderr.readline():
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.debug("ACP STDERR: %s", text)

    async def _process_stdout_loop(self, ctx: _AcpSessionContext) -> None:
        try:
            while line := await ctx.stdout.readline():
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.warning(
                        "ACP stdout: malformed line skipped: %s | raw=%r",
                        exc,
                        line[:200],
                    )
                    continue
                # Handle batch JSON-RPC (array of messages)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict):
                            await self._dispatch_packet(item, ctx)
                elif isinstance(parsed, dict):
                    await self._dispatch_packet(parsed, ctx)
        finally:
            for fut in ctx.response_futures.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Subprocess closed"))
            if not ctx.prompt_done.is_set():
                await ctx.chunk_queue.put(None)

    async def _dispatch_packet(self, data: dict, ctx: _AcpSessionContext) -> None:
        if "result" in data or "error" in data:
            await self._handle_client_response(data, ctx)
            return

        method = data.get("method", "")
        rpc_id = data.get("id")
        params = data.get("params", {})

        if rpc_id is not None and method:
            t = asyncio.create_task(
                self._handle_server_rpc(method, rpc_id, params, ctx)
            )
            ctx.background_tasks.add(t)
            t.add_done_callback(ctx.background_tasks.discard)
            t.add_done_callback(_log_task_exception)
            return

        if method == "session/update":
            await self._handle_session_update(params, ctx)

    async def _handle_client_response(
        self, data: dict, ctx: _AcpSessionContext
    ) -> None:
        rid = data.get("id")
        if rid in ctx.response_futures:
            fut = ctx.response_futures[rid]
            if not fut.done():
                try:
                    fut.set_result(data)
                except asyncio.InvalidStateError:
                    # wait_for() already cancelled the future (timeout fired between
                    # the .done() check and set_result()). Discard the late response.
                    logger.debug(
                        "Response for rpc_id=%r arrived after timeout; discarding", rid
                    )

        result = data.get("result", {})
        if isinstance(result, dict) and result.get("stopReason") == "end_turn":
            ctx.prompt_done.set()
        elif "error" in data and ctx.prompt_id_ref and rid == ctx.prompt_id_ref[0]:
            ctx.prompt_error_ref.append(data["error"])
            await ctx.chunk_queue.put(None)

    async def _handle_server_rpc(
        self, method: str, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
    ) -> None:
        # Defense-in-depth capability check at dispatch time.
        # The ACP subprocess was told our capabilities at initialize time, but
        # this guard ensures a misbehaving or confused subprocess cannot invoke
        # methods the agent config does not permit.
        cap_attr = _CAPABILITY_REQUIREMENTS.get(method)
        if cap_attr is not None:
            allowed = (
                getattr(self.agent_config.capabilities, cap_attr, False)
                if self.agent_config is not None
                else False
            )
            if not allowed:
                resp: dict[str, object] = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32601,
                        "message": f"Capability not enabled: {method}",
                    },
                }
                body = json.dumps(resp).encode("utf-8")
                async with ctx.stdin_lock:
                    ctx.stdin.write(body + b"\n")
                    await ctx.stdin.drain()
                return

        _rpc_dispatch: dict[str, Callable[..., Any]] = {
            "session/request_permission": self._on_request_permission,
            "fs/read_text_file": self._on_fs_read_text_file,
            "fs/write_text_file": self._on_fs_write_text_file,
            "terminal/create": self._on_terminal_create,
            "terminal/kill": self._on_terminal_kill,
            "terminal/output": self._on_terminal_output,
            "terminal/wait_for_exit": self._on_terminal_wait_for_exit,
            "terminal/release": self._on_terminal_release,
        }
        handler = _rpc_dispatch.get(method)
        if handler is not None:
            resp = await handler(rpc_id, params, ctx)
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        body = json.dumps(resp).encode("utf-8")
        async with ctx.stdin_lock:
            ctx.stdin.write(body + b"\n")
            await ctx.stdin.drain()

    async def _on_request_permission(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
    ) -> dict[str, object]:
        """Handle session/request_permission RPC."""
        options = params.get("options", [])
        tool_call = params.get("toolCall", {})
        name = tool_call.get("title", "unknown")
        args = tool_call.get("input", {})

        if self.permission_callback:
            try:
                option_id = await self.permission_callback(name, args, options)
            except GraphBubbleUp as exc:
                ctx.interrupt_exc.append(exc)
                await ctx.chunk_queue.put(None)
                return {}
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
        else:
            option_id = options[0]["optionId"] if options else "allow_once"

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"outcome": {"optionId": option_id, "outcome": "selected"}},
        }

    def _sandbox_path(self, path: str) -> Path:
        """Resolve and sandbox a path to the agent cwd."""
        cwd = Path(self.workspace_root or self.cwd or str(Path.cwd()))
        resolved = (cwd / path).resolve()
        if not resolved.is_relative_to(cwd.resolve()):
            raise ValueError(f"Path {path!r} escapes sandbox")
        return resolved

    async def _on_fs_read_text_file(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
    ) -> dict[str, object]:
        """Handle fs/read_text_file RPC.

        Supports optional ``offset`` (byte offset) and ``limit`` (byte count)
        params for partial reads, avoiding loading entire large files into memory.
        Uses asyncio.to_thread so blocking I/O does not stall the event loop.
        """
        try:
            file_path = self._sandbox_path(params["path"])
            offset: int = int(params.get("offset") or 0)
            limit: int | None = (
                int(params["limit"]) if params.get("limit") is not None else None
            )

            def _read() -> str:
                with file_path.open(encoding="utf-8", errors="ignore") as fh:
                    if offset:
                        fh.seek(offset)
                    return fh.read(limit) if limit is not None else fh.read()

            text = await asyncio.to_thread(_read)
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": text}}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32603, "message": str(exc)},
            }

    async def _on_fs_write_text_file(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
    ) -> dict[str, object]:
        """Handle fs/write_text_file RPC.

        Acquires the global git mutex before writing to prevent races with
        concurrent git operations (ADR-001 §2). Uses asyncio.to_thread so
        blocking I/O does not stall the event loop.
        """
        from ..workspace.git_manager import _git_mutex  # noqa: PLC0415

        try:
            file_path = self._sandbox_path(params["path"])
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

    async def _on_terminal_create(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
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

            # Sandbox the terminal cwd: must be within the agent workspace root.
            raw_cwd = (
                params.get("cwd") or self.workspace_root or self.cwd or str(Path.cwd())
            )
            sandbox_root = Path(
                self.workspace_root or self.cwd or str(Path.cwd())
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

            # Build env: start from current environment, apply any overrides
            terminal_env = os.environ.copy()
            if extra_env := params.get("env"):
                if isinstance(extra_env, list):
                    # ACP protocol: env is list[EnvVariable] with name/value keys
                    terminal_env.update({v["name"]: v["value"] for v in extra_env})
                elif isinstance(extra_env, dict):
                    terminal_env.update(extra_env)
            process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(resolved_cwd),
                env=terminal_env,
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

    async def _on_terminal_kill(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
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
        with suppress(OSError):
            process.kill()
        await process.wait()
        ctx.terminals.pop(terminal_id, None)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    async def _on_terminal_output(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
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

    async def _on_terminal_wait_for_exit(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
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

    async def _on_terminal_release(
        self, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
    ) -> dict[str, object]:
        """Handle terminal/release RPC."""
        terminal_id = params.get("terminalId", "")
        process = ctx.terminals.pop(terminal_id, None)
        if process is not None and process.returncode is None:
            with suppress(OSError):
                process.kill()
            await process.wait()
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    async def _handle_session_update(
        self, params: dict, ctx: _AcpSessionContext
    ) -> None:
        update = params.get("update", {})
        u_type = update.get("sessionUpdate")

        if u_type in ("agent_message_chunk", "agent_thought_chunk"):
            text = update.get("content", {}).get("text", "")
            if text:
                await ctx.chunk_queue.put(
                    ChatGenerationChunk(message=AIMessageChunk(content=text))
                )
        elif u_type == "tool_call":
            await self._on_tool_call(update, ctx)
        elif u_type == "tool_call_update":
            await self._on_tool_call_update(update, ctx)
        elif u_type == "current_mode_update":
            self._agent_modes["currentModeId"] = update.get("currentModeId")
        elif u_type == "available_commands_update":
            self._agent_modes["availableCommands"] = update.get("commands", [])
        elif u_type == "plan":
            # Plan updates are metadata; log receipt and let graph-level plan
            # handling in the supervisor/aggregator layer process them.
            plan_steps = update.get("plan", {}).get("steps", [])
            logger.debug("ACP plan update: %d steps received", len(plan_steps))

    async def _on_tool_call(self, update: dict, ctx: _AcpSessionContext) -> None:
        tid = update.get("toolCallId", "")
        self._tool_calls[tid] = dict(update)
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "id": tid,
                        "name": update.get("title", ""),
                        "args": json.dumps(update.get("input")),
                        "index": 0,
                    }
                ],
            )
        )
        await ctx.chunk_queue.put(chunk)

    async def _on_tool_call_update(self, update: dict, ctx: _AcpSessionContext) -> None:
        tid = update.get("toolCallId", "")
        if tid not in self._tool_calls:
            # Unknown toolCallId: synthesise a tool_call entry so the update
            # is not silently lost (TOAD reference pattern for late/out-of-order
            # tool_call_update notifications).
            self._tool_calls[tid] = {
                "toolCallId": tid,
                "title": update.get("title", tid),
            }
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "id": tid,
                            "name": update.get("title", tid),
                            "args": "{}",
                            "index": 0,
                        }
                    ],
                )
            )
            await ctx.chunk_queue.put(chunk)
        for k, v in update.items():
            if v is not None:
                self._tool_calls[tid][k] = v
        if status := update.get("status"):
            logger.debug("Tool %s status: %s", tid, status)

    async def _initialize_session(self, ctx: _AcpSessionContext) -> None:
        """Send ACP initialize request."""
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
                            self.agent_config.capabilities.filesystem_read
                            if self.agent_config is not None
                            else False
                        ),
                        "writeTextFile": (
                            self.agent_config.capabilities.filesystem_write
                            if self.agent_config is not None
                            else False
                        ),
                    },
                    "terminal": (
                        self.agent_config.capabilities.terminal
                        if self.agent_config is not None
                        else False
                    ),
                },
                "clientInfo": {"name": "vaultspec", "version": "1.0.0"},
            },
        }
        async with ctx.stdin_lock:
            ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await ctx.stdin.drain()
        resp = await asyncio.wait_for(ctx.response_futures[rpc_id], timeout=60)
        if "error" in resp:
            raise RuntimeError(f"Init failed: {resp['error']}")
        res = resp.get("result", {})
        self._agent_capabilities = res.get("agentCapabilities", {})
        self._auth_methods = res.get("authMethods", [])

    async def _setup_session(self, ctx: _AcpSessionContext) -> None:
        """Create or load an ACP session."""
        working_dir = self.workspace_root or self.cwd or str(Path.cwd())
        method = "session/new"
        params: dict[str, object] = {"cwd": working_dir, "mcpServers": self.mcp_servers}
        if self.session_id and self._agent_capabilities.get("loadSession"):
            method = "session/load"
            params["sessionId"] = self.session_id

        rpc_id = AcpRequestId.SESSION_SETUP
        ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        async with ctx.stdin_lock:
            ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await ctx.stdin.drain()
        resp = await asyncio.wait_for(ctx.response_futures[rpc_id], timeout=60)
        if "error" in resp:
            raise RuntimeError(f"Session failed: {resp['error']}")
        res = resp["result"]
        self._active_session_id = res["sessionId"]
        if modes := res.get("modes"):
            self._agent_modes = {
                "currentModeId": modes.get("currentModeId"),
                "availableModes": modes.get("availableModes", []),
            }
        self._tool_calls = {}
        self._process = ctx.process
        self._stdin = ctx.stdin
        self._response_futures = ctx.response_futures

    async def _setup_prompt(
        self, blocks: list[dict], ctx: _AcpSessionContext
    ) -> asyncio.Future:
        """Send the initial prompt."""
        rpc_id = AcpRequestId.SESSION_PROMPT
        ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/prompt",
            "params": {"sessionId": self._active_session_id, "prompt": blocks},
        }
        async with ctx.stdin_lock:
            ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await ctx.stdin.drain()
        ctx.prompt_id_ref.append(rpc_id)
        return ctx.response_futures[rpc_id]

    async def _send_notification(
        self, method: str, params: dict, ctx: _AcpSessionContext
    ) -> None:
        """Send an ACP notification."""
        req = {"jsonrpc": "2.0", "method": method, "params": params}
        async with ctx.stdin_lock:
            ctx.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await ctx.stdin.drain()

    async def fork_session(self) -> str:
        """Fork the current session."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_FORK
        assert self._response_futures is not None
        self._response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/fork",
            "params": {"sessionId": sid},
        }
        stdin = self._require_stdin()
        stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await stdin.drain()
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=60)
        return resp["result"]["sessionId"]

    async def list_sessions(self) -> list[dict[str, object]]:
        """List all sessions."""
        self._require_session()
        rpc_id = AcpRequestId.SESSION_LIST
        assert self._response_futures is not None
        self._response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/list",
            "params": {},
        }
        stdin = self._require_stdin()
        stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await stdin.drain()
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp["result"].get("sessions", [])

    async def set_mode(self, mode_id: str) -> dict[str, object]:
        """Set agent mode."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_SET_MODE
        assert self._response_futures is not None
        self._response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/set_mode",
            "params": {"sessionId": sid, "modeId": mode_id},
        }
        stdin = self._require_stdin()
        stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await stdin.drain()
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})

    async def set_model(self, model_id: str) -> dict[str, object]:
        """Set LLM model."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_SET_MODEL
        assert self._response_futures is not None
        self._response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/set_model",
            "params": {"sessionId": sid, "modelId": model_id},
        }
        stdin = self._require_stdin()
        stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await stdin.drain()
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})

    async def set_config_option(self, key: str, value: object) -> dict[str, object]:
        """Set config option."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_SET_CONFIG_OPTION
        assert self._response_futures is not None
        self._response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/set_config_option",
            "params": {"sessionId": sid, "key": key, "value": value},
        }
        stdin = self._require_stdin()
        stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await stdin.drain()
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})

    async def authenticate(self, token: str) -> dict[str, object]:
        """Authenticate session."""
        self._require_session()
        rpc_id = AcpRequestId.AUTHENTICATE
        assert self._response_futures is not None
        self._response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "authenticate",
            "params": {"token": token},
        }
        stdin = self._require_stdin()
        stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await stdin.drain()
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})
