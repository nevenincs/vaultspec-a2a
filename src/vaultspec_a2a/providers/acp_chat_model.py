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
import shutil
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, override

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
from pydantic import Field, PrivateAttr

from ..control.config import settings
from ..team.team_config import AgentConfig
from ..utils.enums import AcpRequestId
from ..workspace.environment import resolve_env_vars
from ._acp_auth import authenticate_rpc, runtime_log_extra
from ._acp_protocol import RpcHandlerMap, process_stdout_loop
from ._acp_rpc_handlers import (
    on_fs_read_text_file,
    on_fs_write_text_file,
    on_request_permission,
    on_terminal_create,
    on_terminal_kill,
    on_terminal_output,
    on_terminal_release,
    on_terminal_wait_for_exit,
)
from ._acp_session import initialize_session, setup_prompt, setup_session
from ._acp_types import PermissionCallback, _AcpModelConfig, _AcpSessionContext
from ._subprocess import kill_process_tree as _kill_process_tree
from ._subprocess import spawn_acp_process as _spawn_acp_process
from .acp_exceptions import (
    AcpError,
    AcpErrorCode,
    AcpPromptError,
)
from .gemini_auth import refresh_gemini_token

__all__ = ["AcpChatModel"]

logger = logging.getLogger(__name__)


class AcpChatModel(BaseChatModel):
    """A custom LangChain ChatModel that wraps ACP-compatible CLI agents."""

    command: list[str] = Field(
        description="The command and arguments to launch the ACP agent."
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject (e.g., OAuth tokens).",
        # Carries provider auth tokens (CLAUDE_CODE_OAUTH_TOKEN,
        # ANTHROPIC_AUTH_TOKEN). Keep it out of repr and model_dump so a token
        # value can never reach a log, checkpoint, or traceback via serialization
        # (multi-provider-execution env_vars redaction audit).
        repr=False,
        exclude=True,
    )
    session_id: str | None = Field(
        default=None,
        description="If set, resume an existing session via session/load.",
    )
    mcp_servers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="MCP server configs to pass via session/new or session/load.",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Exact tool names auto-permitted for a headless run (mcp__<server>__"
            "<tool>); passed to the CLI via session/new _meta. Empty keeps the "
            "default prompt for human-in-loop runs."
        ),
    )
    cwd: str | None = Field(
        default=None,
        description="Working directory for the agent session.",
    )
    permission_callback: PermissionCallback | None = Field(
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
    _config: _AcpModelConfig = PrivateAttr()
    _process: asyncio.subprocess.Process | None = PrivateAttr(default=None)
    _stdin: asyncio.StreamWriter | None = PrivateAttr(default=None)
    # Shared lock for _stdin writes — used both by background RPC tasks and
    # by public methods (fork_session, list_sessions, etc.) to prevent
    # interleaved JSON-RPC frames (H14 fix).
    _stdin_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _active_session_id: str | None = PrivateAttr(default=None)
    _response_futures: dict[int, asyncio.Future] | None = PrivateAttr(default=None)
    _auth_methods: list[dict[str, Any]] = PrivateAttr(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        """Initialize mutable instance attributes after Pydantic validation."""
        self._config = _AcpModelConfig(
            agent_config=self.agent_config,
            permission_callback=self.permission_callback,
            workspace_root=self.workspace_root,
            cwd=self.cwd,
            command=self.command,
            env_vars=dict(self.env_vars),
            session_id=self.session_id,
            mcp_servers=list(self.mcp_servers),
            allowed_tools=list(self.allowed_tools),
            use_exec=self.use_exec,
            provider=self.provider,
            runtime_authority=self.runtime_authority,
            acp_backend=self.acp_backend,
            command_origin=self.command_origin,
            command_kind=self.command_kind,
            command_executable=self.command_executable,
            command_target=self.command_target,
            auth_mode=self.auth_mode,
        )
        self._auth_methods = []

    @property
    def _llm_type(self) -> str:
        return "acp-chat-model"

    def with_mcp_servers(
        self,
        mcp_servers: list[dict[str, Any]],
        allowed_tools: list[str] | None = None,
    ) -> "AcpChatModel":
        """Return a copy that advertises ``mcp_servers`` in ``session/new``.

        The frozen ``_config`` snapshot that ``setup_session`` reads is built in
        ``model_post_init``; ``model_copy`` alone does not re-run it, so the new
        servers would never reach the session. This rebuilds the snapshot on the
        copy so the wired servers actually take effect (used by the worker node
        to surface the per-run bridged authoring tools, ADR R4). When
        ``allowed_tools`` is supplied (headless runs only), the exact tool names
        are auto-permitted so the CLI can invoke them without a local prompt.
        """
        update: dict[str, Any] = {"mcp_servers": list(mcp_servers)}
        if allowed_tools is not None:
            update["allowed_tools"] = list(allowed_tools)
        updated = self.model_copy(update=update)
        updated.model_post_init(None)
        return updated

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
        # ADR R4: bridged runs must EAGERLY load their per-run authoring MCP
        # tools. The pinned CLI defers MCP tool schemas under Tool Search
        # ("deferred-tool registry"); a stdio bridge's tools are then deferred
        # and unindexed, so the agent connects to the server but never finds the
        # tools. ENABLE_TOOL_SEARCH=0 forces "standard" eager loading, landing
        # the schemas directly in reasoning context. Scoped to bridged runs
        # (allowed_tools present) so default agents keep Tool Search's context
        # savings. This is transport-dependent: for HTTP MCP the flag is inert
        # (that path is not surfaced at all in the pinned CLI); for stdio it is
        # load-bearing, which is why it is gated on the bridge, not the transport.
        if self._config.allowed_tools:
            env["ENABLE_TOOL_SEARCH"] = "0"

        if self.command and Path(self.command[0]).stem.lower() == "gemini":
            await refresh_gemini_token(env=env)

        process = await _spawn_acp_process(
            self.command,
            env,
            self.workspace_root or self.cwd or str(Path.cwd()),
            use_exec=self.use_exec,
            metadata=runtime_log_extra(
                self._config,
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
            tool_calls={},
            agent_modes={},
            last_auth_url=None,
        )

        stderr_task = asyncio.create_task(self._read_stderr_loop(ctx))
        rpc_map: RpcHandlerMap = {
            "session/request_permission": on_request_permission,
            "fs/read_text_file": on_fs_read_text_file,
            "fs/write_text_file": on_fs_write_text_file,
            "terminal/create": on_terminal_create,
            "terminal/kill": on_terminal_kill,
            "terminal/output": on_terminal_output,
            "terminal/wait_for_exit": on_terminal_wait_for_exit,
            "terminal/release": on_terminal_release,
        }
        stdout_task = asyncio.create_task(
            process_stdout_loop(ctx, self._config, rpc_map)
        )

        try:
            init_result = await initialize_session(ctx, self._config)
            self._auth_methods = init_result.auth_methods
            result = await setup_session(
                ctx,
                self._config,
                init_result.agent_capabilities,
                init_result.auth_methods,
            )
            self._active_session_id = result.session_id
            self._process = ctx.process
            self._stdin = ctx.stdin
            self._stdin_lock = ctx.stdin_lock
            self._response_futures = ctx.response_futures
            prompt_future = await setup_prompt(
                ctx,
                self._config,
                prompt_blocks,
                self._active_session_id,
            )

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
                        extra=runtime_log_extra(
                            self._config,
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
            metadata=runtime_log_extra(
                self._config,
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
        ctx.tool_calls = {}
        ctx.agent_modes = {}
        ctx.last_auth_url = None

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
                    extra=runtime_log_extra(
                        self._config,
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
                extra=runtime_log_extra(
                    self._config,
                    process=ctx.process,
                    handshake_step="authenticate",
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )
            return
        if ctx.auth_prompt_active and text.startswith(("http://", "https://")):
            ctx.auth_url = text
            ctx.auth_prompt_active = False
            ctx.last_auth_url = text
            logger.info(
                "ACP browser authentication URL captured",
                extra=runtime_log_extra(
                    self._config,
                    process=ctx.process,
                    handshake_step="authenticate",
                    stderr_event_count=ctx.stderr_event_count,
                ),
            )

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
        return await authenticate_rpc(
            ctx=None,
            config=self._config,
            env=env,
            auth_methods=self._auth_methods,
            stdin=self._require_stdin(),
            stdin_lock=self._stdin_lock,
            response_futures=self._require_response_futures(),
            process=self._process,
            auth_url=None,
        )
