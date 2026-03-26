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
import re
import shutil
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast, override
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
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langgraph.errors import GraphBubbleUp
from pydantic import Field, PrivateAttr

from ..control.config import settings
from ..team.team_config import AgentConfig
from ..utils.enums import AcpRequestId
from ..workspace.environment import resolve_env_vars
from ._subprocess import kill_process_tree as _kill_process_tree
from ._subprocess import spawn_acp_process as _spawn_acp_process
from .acp_exceptions import (
    AcpAuthError,
    AcpError,
    AcpErrorCode,
    AcpPromptError,
    AcpSessionError,
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
    # M13: session/request_permission is intentionally excluded — it is a
    # server→client RPC initiated by the agent, not a capability-gated
    # client→server request.  No clientCapability flag governs it.
}

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


def _log_task_exception(task: asyncio.Task) -> None:
    """Log unhandled exceptions from fire-and-forget background RPC tasks."""
    if not task.cancelled() and (exc := task.exception()):
        logger.error("Background RPC task failed: %s", exc, exc_info=exc)


class _AuthResponseCancelledError(RuntimeError):
    """Raised when the authenticate response future is cancelled in-band."""


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
    use_exec: bool = Field(
        default=False,
        description=(
            "When True, use create_subprocess_exec on Windows instead of "
            "create_subprocess_shell. Set for native PE32+ binaries (e.g. "
            "precompiled Bun executable) that do not need a .cmd shim."
        ),
    )
    provider: str | None = Field(
        default=None,
        description="Bounded provider identity for ACP runtime evidence.",
    )
    runtime_authority: str | None = Field(
        default=None,
        description="Bounded runtime authority classification for the ACP command.",
    )
    acp_backend: str | None = Field(
        default=None,
        description="ACP backend classification such as node, binary, or gemini-cli.",
    )
    command_origin: str | None = Field(
        default=None,
        description="Bounded origin of the resolved ACP command.",
    )
    command_kind: str | None = Field(
        default=None,
        description="Bounded command kind such as node_entry or bun_binary.",
    )
    command_executable: str | None = Field(
        default=None,
        description="Resolved ACP executable basename for evidence logs.",
    )
    command_target: str | None = Field(
        default=None,
        description="Resolved ACP entrypoint or executable target for evidence logs.",
    )
    auth_mode: str | None = Field(
        default=None,
        description="Bounded authentication mode classification for the ACP runtime.",
    )

    # --- Runtime state (private, not model fields) ---
    _process: asyncio.subprocess.Process | None = PrivateAttr(default=None)
    _stdin: asyncio.StreamWriter | None = PrivateAttr(default=None)
    # Shared lock for _stdin writes — used both by background RPC tasks and
    # by public methods (fork_session, list_sessions, etc.) to prevent
    # interleaved JSON-RPC frames (H14 fix).
    _stdin_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _active_session_id: str | None = PrivateAttr(default=None)
    _response_futures: dict[int, asyncio.Future] | None = PrivateAttr(default=None)
    _agent_capabilities: dict[str, Any] = PrivateAttr(default_factory=dict)
    _auth_methods: list[dict[str, Any]] = PrivateAttr(default_factory=list)
    _agent_modes: dict[str, Any] = PrivateAttr(default_factory=dict)
    _tool_calls: dict[str, Any] = PrivateAttr(default_factory=dict)
    _last_auth_url: str | None = PrivateAttr(default=None)

    def model_post_init(self, __context: object) -> None:
        """Initialize mutable instance attributes after Pydantic validation."""
        self._agent_capabilities = {}
        self._auth_methods = []
        self._agent_modes = {}
        self._tool_calls = {}
        self._last_auth_url = None

    @property
    def _llm_type(self) -> str:
        return "acp-chat-model"

    @override
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Streams responses from the ACP subprocess."""
        prompt_blocks: list[dict[str, str]] = []
        for msg in messages:
            if isinstance(
                msg,
                (HumanMessage, SystemMessage, ChatMessage, AIMessage, AIMessageChunk),
            ):
                prompt_blocks.append({"type": "text", "text": str(msg.content)})

        # ACP-02: use resolve_env_vars() as base so API credentials are scrubbed
        # from the subprocess environment.  Provider-specific keys (e.g.
        # CLAUDE_CODE_OAUTH_TOKEN) are re-injected explicitly via self.env_vars,
        # which is set by ProviderFactory with only the required token.
        _ws_path = Path(self.workspace_root or self.cwd or str(Path.cwd()))
        env = resolve_env_vars(_ws_path)
        env.update(self.env_vars)
        # ADR-002 §2: When using CLAUDE_CODE_OAUTH_TOKEN (flat-rate subscription),
        # ANTHROPIC_API_KEY must be explicitly removed. If both are present,
        # claude-agent-acp will use pay-as-you-go billing instead of the OAuth
        # subscription, causing auth/billing failures.
        if "CLAUDE_CODE_OAUTH_TOKEN" in env:
            env.pop("ANTHROPIC_API_KEY", None)
        # ADR-002 §5.1: bypass bundled cli.js — use system
        # claude binary (native PE32+ Bun exe)
        _system_claude = shutil.which("claude")
        if "CLAUDE_CODE_OAUTH_TOKEN" in env and _system_claude:
            env["CLAUDE_CODE_EXECUTABLE"] = _system_claude
        env.pop("CLAUDECODE", None)  # Prevent nested session abort
        # ACP-ENV-006: suppress interactive prompts that
        # stall non-interactive ACP subprocesses.
        env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] = "1"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

        if self.command and Path(self.command[0]).stem.lower() == "gemini":
            await refresh_gemini_token(env=env)

        process = await _spawn_acp_process(
            self.command,
            env,
            self.workspace_root or self.cwd or str(Path.cwd()),
            use_exec=self.use_exec,
            metadata=self._runtime_log_extra(
                handshake_step="spawn",
                timeout_seconds=settings.acp_startup_timeout_seconds,
            ),
        )

        if process.stdin is None or process.stdout is None:
            raise RuntimeError("ACP subprocess failed to open stdio pipes")
        ctx = _AcpSessionContext(
            process=process,
            stdin=process.stdin,
            stdout=process.stdout,
            response_futures={},
            chunk_queue=asyncio.Queue(maxsize=settings.acp_chunk_queue_maxsize),
            prompt_done=asyncio.Event(),
            prompt_id_ref=[],
            interrupt_exc=[],
        )

        stderr_task = asyncio.create_task(self._read_stderr_loop(ctx))
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
                    logger.warning(
                        "ACP subprocess exited before end_turn",
                        extra=self._runtime_log_extra(
                            process=ctx.process,
                            handshake_step="session/prompt",
                            stderr_event_count=ctx.stderr_event_count,
                            exit_code=ctx.process.returncode,
                        ),
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

        # PROV-M2: propagate any interrupt that raced with end_turn
        if ctx.interrupt_exc:
            raise ctx.interrupt_exc[0]

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
                await _kill_process_tree(proc)
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

        # PROV-C1: cancel all in-flight background RPC tasks before killing process
        for task in list(ctx.background_tasks):
            task.cancel()
        if ctx.background_tasks:
            await asyncio.gather(*ctx.background_tasks, return_exceptions=True)

        # PROV-M1: await task cancellation before killing the process
        stdout_task.cancel()
        stderr_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        await _kill_process_tree(
            ctx.process,
            metadata=self._runtime_log_extra(
                process=ctx.process,
                handshake_step="cleanup",
                stderr_event_count=ctx.stderr_event_count,
                kill_strategy="taskkill_tree"
                if sys.platform == "win32"
                else "sigterm_then_sigkill",
            ),
        )

        self._process = None
        self._response_futures = None
        self._active_session_id = None
        self._tool_calls = {}

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
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

    def _require_response_futures(self) -> dict[int, asyncio.Future]:
        if self._response_futures is None:
            raise RuntimeError("No active session response futures.")
        return self._response_futures

    def _runtime_log_extra(
        self,
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
            "provider": self.provider,
            "runtime_authority": self.runtime_authority,
            "acp_backend": self.acp_backend,
            "command_origin": self.command_origin,
            "command_kind": self.command_kind,
            "command_executable": self.command_executable,
            "command_target": self.command_target,
            "auth_mode": self.auth_mode,
            "use_exec": self.use_exec,
            "workspace_root_present": bool(self.workspace_root),
            "cwd": self.workspace_root or self.cwd or str(Path.cwd()),
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
        elif self._active_session_id is not None:
            extra["session_id"] = self._active_session_id
        if stderr_event_count is not None:
            extra["stderr_event_count"] = stderr_event_count
        if exit_code is not None:
            extra["exit_code"] = exit_code
        if kill_strategy is not None:
            extra["kill_strategy"] = kill_strategy
        return {key: value for key, value in extra.items() if value is not None}

    async def _read_stderr_loop(self, ctx: _AcpSessionContext) -> None:
        if ctx.process.stderr is None:
            return
        while line := await ctx.process.stderr.readline():
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                self._capture_auth_progress(text, ctx)
                ctx.stderr_event_count += 1
                logger.debug(
                    "ACP STDERR: %s",
                    text,
                    extra=self._runtime_log_extra(
                        process=ctx.process,
                        stderr_event_count=ctx.stderr_event_count,
                    ),
                )

    def _capture_auth_progress(self, text: str, ctx: _AcpSessionContext) -> None:
        """Capture browser-auth progress from ACP stderr lines."""
        if "Please visit the following URL to authorize the application" in text:
            ctx.auth_prompt_active = True
            logger.info(
                "ACP browser authentication prompt detected",
                extra=self._runtime_log_extra(
                    process=ctx.process,
                    handshake_step="authenticate",
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )
            return
        if ctx.auth_prompt_active and text.startswith(("http://", "https://")):
            ctx.auth_url = text
            ctx.auth_prompt_active = False
            self._last_auth_url = text
            logger.info(
                "ACP browser authentication URL captured",
                extra=self._runtime_log_extra(
                    process=ctx.process,
                    handshake_step="authenticate",
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )

    def _auth_url_hint(self, auth_url: str | None = None) -> str:
        """Return a short browser-auth hint when an auth URL is available."""
        url = auth_url or self._last_auth_url
        if not url:
            return ""
        return f" Browser auth URL: {url}"

    @staticmethod
    def _is_auth_cancelled_error(error: object) -> bool:
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

    @staticmethod
    def _is_auth_rejected_error(error: object) -> bool:
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

    def _raise_auth_outcome_error(
        self,
        *,
        message: str,
        code: int,
        auth_outcome: str,
        auth_url: str | None = None,
    ) -> None:
        """Raise AcpAuthError with a bounded machine-readable auth outcome."""
        raise AcpAuthError(
            f"{message}{self._auth_url_hint(auth_url)}",
            code=code,
            data={"auth_outcome": auth_outcome},
        )

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
                        extra=self._runtime_log_extra(
                            process=ctx.process,
                            stderr_event_count=ctx.stderr_event_count,
                        ),
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
                try:
                    ctx.chunk_queue.put_nowait(None)
                except asyncio.QueueFull:
                    logger.warning(
                        "Chunk queue full — dropping EOF sentinel; consumer may hang"
                    )

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
            try:
                ctx.chunk_queue.put_nowait(None)
            except asyncio.QueueFull:
                logger.warning("Chunk queue full — dropping error sentinel")

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
        args = tool_call.get("rawInput", {})

        if self.permission_callback:
            try:
                option_id = await self.permission_callback(name, args, options)
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

    def _sandbox_path(self, path: str) -> Path:
        """Resolve and sandbox a path to the agent cwd."""
        cwd = Path(self.workspace_root or self.cwd or str(Path.cwd()))
        resolved = (cwd / path).resolve()
        if not resolved.is_relative_to(cwd.resolve()):
            raise ValueError(f"Path {path!r} escapes sandbox")
        return resolved

    async def _on_fs_read_text_file(
        self, rpc_id: int | str, params: dict, _ctx: _AcpSessionContext
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

    async def _on_fs_write_text_file(
        self, rpc_id: int | str, params: dict, _ctx: _AcpSessionContext
    ) -> dict[str, object]:
        """Handle fs/write_text_file RPC.

        Acquires the global git mutex before writing to prevent races with
        concurrent git operations (ADR-001 §2). Uses asyncio.to_thread so
        blocking I/O does not stall the event loop.
        """
        from ..workspace.git_manager import _git_mutex

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
                            raise ValueError(
                                f"Invalid environment variable name: {name!r}"
                            )
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
        await _kill_process_tree(process)
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
            await _kill_process_tree(process)
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    async def _handle_session_update(
        self, params: dict, ctx: _AcpSessionContext
    ) -> None:
        update = params.get("update", {})
        u_type = update.get("sessionUpdate")

        if u_type in ("agent_message_chunk", "agent_thought_chunk"):
            text = update.get("content", {}).get("text", "")
            if text:
                try:
                    ctx.chunk_queue.put_nowait(
                        ChatGenerationChunk(message=AIMessageChunk(content=text))
                    )
                except asyncio.QueueFull:
                    logger.warning(
                        "Chunk queue full — dropping chunk to prevent deadlock"
                    )
        elif u_type == "tool_call_chunk":
            # M20: handle incremental tool call argument streaming.
            # ACP agents stream partial JSON args via tool_call_chunk before the
            # final tool_call event.  Forwarded as a streaming ToolCallChunk so
            # LangGraph can accumulate args progressively.
            tid = update.get("toolCallId", "")
            args_delta = update.get("inputDelta", "")
            if tid and args_delta:
                try:
                    ctx.chunk_queue.put_nowait(
                        ChatGenerationChunk(
                            message=AIMessageChunk(
                                content="",
                                tool_call_chunks=[
                                    {
                                        "id": tid,
                                        "name": "",
                                        "args": args_delta,
                                        "index": 0,
                                    }
                                ],
                            )
                        )
                    )
                except asyncio.QueueFull:
                    logger.warning(
                        "Chunk queue full — dropping tool_call_chunk to prevent "
                        "deadlock"
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
            plan_entries = update.get("entries", [])
            logger.debug("ACP plan update: %d entries received", len(plan_entries))

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
                        "args": json.dumps(update.get("rawInput")),
                        "index": 0,
                    }
                ],
            )
        )
        try:
            ctx.chunk_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            logger.warning(
                "Chunk queue full — dropping tool_call chunk to prevent deadlock"
            )

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
            try:
                ctx.chunk_queue.put_nowait(chunk)
            except asyncio.QueueFull:
                logger.warning(
                    "Chunk queue full — dropping tool_call_update chunk to "
                    "prevent deadlock"
                )
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
                    # ACP-AUTH-002: signal support for terminal-based auth and
                    # terminal output to claude-agent-acp ≥0.20.2.  Without
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
                extra=self._runtime_log_extra(
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
                extra=self._runtime_log_extra(
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
        self._agent_capabilities = res.get("agentCapabilities", {})
        # _auth_methods stores the authMethods list from the initialize response
        # so session setup can execute the ACP authenticate handshake when an
        # agent requires it before session/new.
        self._auth_methods = res.get("authMethods", [])

    def _auth_hint(self) -> str:
        """Return a provider-specific authentication hint for error messages."""
        exe = self.command[0] if self.command else ""
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

    def _select_auth_method_id(self, env: Mapping[str, str]) -> str:
        """Select the best advertised ACP auth method for the current env."""
        method_ids: list[str] = [
            mid
            for method in self._auth_methods
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
            or self.auth_mode in {"local_oauth_mount", "local_oauth_refresh"}
        ) and "oauth-personal" in method_ids:
            return "oauth-personal"
        return method_ids[0]

    @staticmethod
    def _is_auth_required_error(error: object) -> bool:
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

    async def _authenticate_rpc(
        self,
        *,
        stdin: asyncio.StreamWriter,
        stdin_lock: asyncio.Lock,
        response_futures: dict[int, asyncio.Future],
        env: Mapping[str, str],
        process: asyncio.subprocess.Process | None = None,
        stderr_event_count: int | None = None,
        auth_url: str | None = None,
    ) -> dict[str, object]:
        """Send the ACP authenticate RPC using the advertised method."""
        self._last_auth_url = auth_url
        method_id = self._select_auth_method_id(env)
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
            extra=self._runtime_log_extra(handshake_step="authenticate"),
        )
        async with stdin_lock:
            stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await stdin.drain()
        try:
            resp = await self._wait_for_authenticate_response(
                response_future=response_futures[rpc_id],
                process=process,
                timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
            )
        except TimeoutError:
            logger.error(
                "ACP authenticate timed out",
                extra=self._runtime_log_extra(
                    process=process,
                    handshake_step="authenticate",
                    timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
                    stderr_event_count=stderr_event_count,
                ),
            )
            self._raise_auth_outcome_error(
                message=(
                    "Authentication did not complete before the interactive auth "
                    f"watchdog expired after "
                    f"{settings.acp_interactive_auth_timeout_seconds:.0f}s. "
                    f"{self._auth_hint()}"
                ),
                code=AcpErrorCode.INTERNAL_ERROR,
                auth_outcome="watchdog_expired",
                auth_url=auth_url,
            )
        except _AuthResponseCancelledError:
            logger.warning(
                "ACP authenticate was cancelled",
                extra=self._runtime_log_extra(
                    process=process,
                    handshake_step="authenticate",
                    timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
                    stderr_event_count=stderr_event_count,
                ),
            )
            self._raise_auth_outcome_error(
                message="Authentication was cancelled before completion.",
                code=AcpErrorCode.INTERNAL_ERROR,
                auth_outcome="operator_cancelled",
                auth_url=auth_url,
            )
        except RuntimeError as exc:
            logger.error(
                "ACP authenticate ended before completion",
                extra=self._runtime_log_extra(
                    process=process,
                    handshake_step="authenticate",
                    timeout_seconds=settings.acp_interactive_auth_timeout_seconds,
                    stderr_event_count=stderr_event_count,
                ),
            )
            self._raise_auth_outcome_error(
                message=(
                    "Authentication ended before completion: "
                    f"{exc}. {self._auth_hint()}"
                ),
                code=AcpErrorCode.INTERNAL_ERROR,
                auth_outcome="subprocess_exited_before_auth",
                auth_url=auth_url,
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
            if self._is_auth_cancelled_error(err):
                self._raise_auth_outcome_error(
                    message=(
                        f"Authentication was cancelled before completion: {err_msg}"
                    ),
                    code=err_code,
                    auth_outcome="operator_cancelled",
                    auth_url=auth_url,
                )
            if self._is_auth_rejected_error(err):
                self._raise_auth_outcome_error(
                    message=f"Authentication was explicitly rejected: {err_msg}",
                    code=err_code,
                    auth_outcome="auth_rejected",
                    auth_url=auth_url,
                )
            self._raise_auth_outcome_error(
                message=f"Authentication failed: {err_msg}",
                code=err_code,
                auth_outcome="auth_failed",
                auth_url=auth_url,
            )
        result = resp.get("result")
        return cast("dict[str, object]", result) if isinstance(result, dict) else {}

    async def _wait_for_authenticate_response(
        self,
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

    async def _setup_session(self, ctx: _AcpSessionContext) -> None:
        """Create or load an ACP session."""
        working_dir = self.workspace_root or self.cwd or str(Path.cwd())
        method = "session/new"
        params: dict[str, object] = {"cwd": working_dir, "mcpServers": self.mcp_servers}
        if self.session_id and self._agent_capabilities.get("loadSession"):
            method = "session/load"
            params["sessionId"] = self.session_id

        env = resolve_env_vars(Path(working_dir))
        env.update(self.env_vars)
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
                    extra=self._runtime_log_extra(
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
            err_msg = (
                str(err.get("message", err)) if isinstance(err, dict) else str(err)
            )
            if (
                not attempted_auth
                and self._auth_methods
                and self._is_auth_required_error(err)
            ):
                attempted_auth = True
                await self._authenticate_rpc(
                    stdin=ctx.stdin,
                    stdin_lock=ctx.stdin_lock,
                    response_futures=ctx.response_futures,
                    env=env,
                    process=ctx.process,
                    stderr_event_count=ctx.stderr_event_count,
                    auth_url=ctx.auth_url,
                )
                continue
            if self._is_auth_required_error(err):
                logger.error(
                    "ACP session setup requires authentication",
                    extra=self._runtime_log_extra(
                        process=ctx.process,
                        handshake_step=method,
                        timeout_seconds=settings.acp_startup_timeout_seconds,
                        stderr_event_count=ctx.stderr_event_count,
                    ),
                )
                hint = self._auth_hint()
                raise AcpSessionError(
                    f"ACP {method} failed — authentication required. {hint}",
                    code=err_code,
                )
            logger.error(
                "ACP session setup returned an error",
                extra=self._runtime_log_extra(
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
        self._active_session_id = res["sessionId"]
        if modes := res.get("modes"):
            self._agent_modes = {
                "currentModeId": modes.get("currentModeId"),
                "availableModes": modes.get("availableModes", []),
            }
        self._tool_calls = {}
        self._process = ctx.process
        self._stdin = ctx.stdin
        # Share the session's stdin_lock so public methods (fork_session, etc.)
        # use the same mutex as background RPC tasks (H14 fix).
        self._stdin_lock = ctx.stdin_lock
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
        futures = self._require_response_futures()
        futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/fork",
            "params": {"sessionId": sid},
        }
        stdin = self._require_stdin()
        async with self._stdin_lock:
            stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await stdin.drain()
        resp = await asyncio.wait_for(
            futures[rpc_id], timeout=settings.acp_startup_timeout_seconds
        )
        return resp["result"]["sessionId"]

    async def list_sessions(self) -> list[dict[str, object]]:
        """List all sessions."""
        self._require_session()
        rpc_id = AcpRequestId.SESSION_LIST
        futures = self._require_response_futures()
        futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/list",
            "params": {},
        }
        stdin = self._require_stdin()
        async with self._stdin_lock:
            stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await stdin.drain()
        resp = await asyncio.wait_for(
            futures[rpc_id], timeout=settings.acp_rpc_timeout_seconds
        )
        return resp["result"].get("sessions", [])

    async def set_mode(self, mode_id: str) -> dict[str, object]:
        """Set agent mode."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_SET_MODE
        futures = self._require_response_futures()
        futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/set_mode",
            "params": {"sessionId": sid, "modeId": mode_id},
        }
        stdin = self._require_stdin()
        async with self._stdin_lock:
            stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await stdin.drain()
        resp = await asyncio.wait_for(
            futures[rpc_id], timeout=settings.acp_rpc_timeout_seconds
        )
        return resp.get("result", {})

    async def set_model(self, model_id: str) -> dict[str, object]:
        """Set LLM model."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_SET_MODEL
        futures = self._require_response_futures()
        futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/set_model",
            "params": {"sessionId": sid, "modelId": model_id},
        }
        stdin = self._require_stdin()
        async with self._stdin_lock:
            stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await stdin.drain()
        resp = await asyncio.wait_for(
            futures[rpc_id], timeout=settings.acp_rpc_timeout_seconds
        )
        return resp.get("result", {})

    async def set_config_option(self, key: str, value: object) -> dict[str, object]:
        """Set config option."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_SET_CONFIG_OPTION
        futures = self._require_response_futures()
        futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "session/set_config_option",
            "params": {"sessionId": sid, "key": key, "value": value},
        }
        stdin = self._require_stdin()
        async with self._stdin_lock:
            stdin.write(json.dumps(req).encode("utf-8") + b"\n")
            await stdin.drain()
        resp = await asyncio.wait_for(
            futures[rpc_id], timeout=settings.acp_rpc_timeout_seconds
        )
        return resp.get("result", {})

    async def authenticate(self, token: str) -> dict[str, object]:
        """Authenticate session.

        Sends the ACP ``authenticate`` RPC per spec (§3.4). The ``methodId``
        is selected from the auth methods advertised by the agent during
        ``initialize``. ``token`` is retained for API compatibility; Gemini's
        ACP implementation expects ``api-key`` in ``_meta`` for key-based auth
        and no raw token in params.
        """
        logger.debug(
            "Sending authenticate RPC (token redacted, length=%d)",
            len(token),
        )
        env = resolve_env_vars(Path(self.workspace_root or self.cwd or str(Path.cwd())))
        env.update(self.env_vars)
        return await self._authenticate_rpc(
            stdin=self._require_stdin(),
            stdin_lock=self._stdin_lock,
            response_futures=self._require_response_futures(),
            env=env,
            process=self._process,
            auth_url=self._last_auth_url,
        )
