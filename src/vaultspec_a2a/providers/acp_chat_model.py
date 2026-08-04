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
import logging
import shutil
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Never, override

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
from ._acp_authoring import (
    AUTHORING_MCP_SERVER_NAME,
    config_home_authoring_entry,
)
from ._acp_mcp import harness_spawn_env
from ._acp_protocol import process_stdout_loop
from ._acp_request import await_response, issue_request
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
from ._acp_types import (
    AcpModelConfig,
    AcpResponseFuture,
    AcpResponseFutures,
    AcpSessionContext,
    PermissionCallback,
    RpcHandlerMap,
    require_workspace_root,
)
from ._cleanup import CleanupStep, run_independent_cleanups
from ._json_contract import (
    JsonObject,
    lenient_json_object,
    lenient_json_object_list,
)
from ._mcp_contract import verify_harness_mcp_contract
from ._subprocess import kill_process_tree as _kill_process_tree
from ._subprocess import spawn_acp_process as _spawn_acp_process
from .acp_exceptions import (
    AcpError,
    AcpErrorCode,
    AcpPromptError,
)
from .conditions import condition_from_acp_error
from .gemini_auth import refresh_gemini_token

__all__ = ["AcpChatModel"]

logger = logging.getLogger(__name__)


def _required_session_id(result: JsonObject, *, operation: str) -> str:
    """Return the session id in one successful ACP response result."""
    session_id = result.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        raise AcpError(
            f"ACP {operation} succeeded without a sessionId",
            code=AcpErrorCode.INTERNAL_ERROR,
        )
    return session_id


def _raise_prompt_error(response: JsonObject) -> Never:
    """Raise a typed prompt failure from one JSON-RPC error response.

    The adapter attaches a categorical error kind to this frame precisely so a
    client can dispatch on it rather than pattern-match the message, and this is
    the one place that kind is still in hand. Resolving it here means the
    condition travels with the exception to every reporting site, instead of
    each of them re-deriving it from prose that has already been flattened.
    """
    raw_error = response.get("error")
    error = lenient_json_object(raw_error)
    code_value = error.get("code")
    code = (
        code_value
        if isinstance(code_value, int) and not isinstance(code_value, bool)
        else AcpErrorCode.INTERNAL_ERROR
    )
    raise AcpPromptError(
        f"ACP prompt failed: {raw_error}",
        code=code,
        data=error.get("data"),
        condition=condition_from_acp_error(error),
    )


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
        # (env_vars redaction audit).
        repr=False,
        exclude=True,
    )
    session_id: str | None = Field(
        default=None,
        description="If set, resume an existing session via session/load.",
    )
    mcp_servers: list[JsonObject] = Field(
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
        description="Workspace root override for CWD resolution.",
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
    acp_family: str = Field(
        default="claude",
        description=(
            "Backend family discriminator ('claude' or 'kimi') selecting the ACP "
            "allowlist transport: the claude family emits the Claude-CLI-only "
            "session/new allowedTools _meta; the kimi family omits it."
        ),
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
    desired_model: str | None = Field(
        default=None,
        description=(
            "Concrete model selected by the resolved profile. Claude-family ACP "
            "sessions negotiate this value before any prompt is sent."
        ),
    )
    desired_config_options: dict[str, str] = Field(default_factory=dict)

    # --- Runtime state (private, not model fields) ---
    _config: AcpModelConfig = PrivateAttr()
    _process: asyncio.subprocess.Process | None = PrivateAttr(default=None)
    _stdin: asyncio.StreamWriter | None = PrivateAttr(default=None)
    # Shared lock for _stdin writes — used both by background RPC tasks and
    # by public methods (fork_session, list_sessions, etc.) to prevent
    # interleaved JSON-RPC frames (H14 fix).
    _stdin_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _active_session_id: str | None = PrivateAttr(default=None)
    _response_futures: AcpResponseFutures | None = PrivateAttr(default=None)
    _auth_methods: list[JsonObject] = PrivateAttr(default_factory=list)
    _session_config_options: list[JsonObject] = PrivateAttr(default_factory=list)

    @override
    def model_post_init(self, __context: object) -> None:
        """Initialize mutable instance attributes after Pydantic validation."""
        self._config = AcpModelConfig(
            agent_config=self.agent_config,
            permission_callback=self.permission_callback,
            workspace_root=self.workspace_root,
            command=self.command,
            env_vars=dict(self.env_vars),
            session_id=self.session_id,
            mcp_servers=list(self.mcp_servers),
            allowed_tools=list(self.allowed_tools),
            use_exec=self.use_exec,
            provider=self.provider,
            runtime_authority=self.runtime_authority,
            acp_backend=self.acp_backend,
            acp_family=self.acp_family,
            command_origin=self.command_origin,
            command_kind=self.command_kind,
            command_executable=self.command_executable,
            command_target=self.command_target,
            auth_mode=self.auth_mode,
            desired_model=self.desired_model,
            desired_config_options=dict(self.desired_config_options),
        )
        self._auth_methods = []
        self._session_config_options = []

    @property
    @override
    def _llm_type(self) -> str:
        return "acp-chat-model"

    def with_mcp_servers(
        self,
        mcp_servers: list[JsonObject],
        allowed_tools: list[str] | None = None,
    ) -> "AcpChatModel":
        """Return a copy that advertises ``mcp_servers`` in ``session/new``.

        The frozen ``_config`` snapshot that ``setup_session`` reads is built in
        ``model_post_init``; ``model_copy`` alone does not re-run it, so the new
        servers would never reach the session. This rebuilds the snapshot on the
        copy so the wired servers actually take effect (used by the worker node
        to surface the per-run bridged authoring tools). When
        ``allowed_tools`` is supplied (headless runs only), the exact tool names
        are auto-permitted so the CLI can invoke them without a local prompt.
        """
        update: dict[str, object] = {"mcp_servers": list(mcp_servers)}
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
        prompt_blocks: list[JsonObject] = []
        for msg in messages:
            if isinstance(
                msg,
                (HumanMessage, SystemMessage, ChatMessage, AIMessage, AIMessageChunk),
            ):
                prompt_blocks.append({"type": "text", "text": str(msg.content)})

        # The child inherits the ambient environment (resolve_env_vars passes it
        # through, minus this service's own infra tokens) so the spawned CLI
        # authenticates however the operator ambiently does - a logged-in CLI
        # session, an API key in the environment, either. This layer implements
        # NO authentication: it expresses no preference, reads no credential,
        # and strips none. Provider-specific config (e.g. Z.ai's
        # ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN retarget) rides self.env_vars
        # as an additive overlay from ProviderFactory.
        _ws_path = require_workspace_root(
            self.workspace_root, surface="ACP environment resolution"
        )
        env = resolve_env_vars(_ws_path)
        env.update(self.env_vars)
        # Bypass the adapter's bundled cli.js — drive the same installed claude
        # binary an interactive invocation runs, so the lane's behaviour (and
        # credential resolution) matches the operator's own CLI exactly. Only
        # for the claude-family adapter; Gemini/Kimi run their own CLIs.
        _system_claude = shutil.which("claude")
        if (
            _system_claude
            and self._config.acp_family == "claude"
            and self.command
            and Path(self.command[0]).stem.lower() != "gemini"
        ):
            env.setdefault("CLAUDE_CODE_EXECUTABLE", _system_claude)
        env.pop("CLAUDECODE", None)  # Prevent nested session abort
        # Suppress interactive prompts that
        # stall non-interactive ACP subprocesses.
        env["CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY"] = "1"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        # Bridged runs must EAGERLY load their per-run authoring MCP
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

        # Fail loud: every registry-known harness server this session is about to
        # advertise must actually serve the read-only tools the registry declares
        # for it. The declared names ARE the run's allowlist and the surfacing
        # config's contents, so a server that no longer serves one of them would
        # leave the agent advertising and auto-permitting a tool it can never call
        # - grounding silently absent, run still green. The launch spec carries no
        # version constraint by design; this check, not a pinned version, is what
        # makes the declaration trustworthy. Probed before any config home or
        # workspace projection is written, so a refusal leaves nothing to clean up,
        # and memoized per launch identity so the cost lands once per process.
        await verify_harness_mcp_contract(self._config.mcp_servers, env=env)

        # The CLI runs in the operator's REAL config home (no redirect - the
        # no-auth contract requires the child to resolve exactly the login an
        # interactive `claude` resolves). The declared-surface invariant rides
        # the SESSION itself: setup_session advertises the declared servers in
        # ``session/new`` and, on the claude family, pins the CLI into strict
        # MCP mode so the mounted surface is exactly that advertisement - no
        # ambient user-global, project, plugin, or account-connector server
        # joins it, and a plain run mounts nothing. Nothing is written into the
        # run workspace or the config home for MCP surfacing.
        #
        # The bridge's env values ride the session spec as ``${NAME}``
        # placeholder references (the spec is serialized onto the CLI argv);
        # the real values are hoisted into the spawn env here, the environment
        # the CLI expands those references from at config parse time.
        if self._config.mcp_servers:
            _bridge_entry, bridge_env = config_home_authoring_entry(
                self._config.mcp_servers
            )
            env.update(bridge_env)
            # Every OTHER advertised spec's env is projected the same way and
            # was never hoisted, so a pinned harness server reached the CLI as a
            # dangling reference and started with its pin unset - looking pinned
            # while resolving its project from the inherited directory.
            env.update(
                harness_spawn_env(
                    self._config.mcp_servers, exclude=AUTHORING_MCP_SERVER_NAME
                )
            )

        if self.command and Path(self.command[0]).stem.lower() == "gemini":
            await refresh_gemini_token(env=env)

        # The spawn and session setup run INSIDE the try so the finally below
        # is the single cleanup path: a spawn-time raise (missing binary,
        # startup timeout) or a stdio-pipe failure must not orphan the session
        # tree. ctx and the reader tasks are created here, so the finally
        # guards on their presence before touching the session.
        ctx: AcpSessionContext | None = None
        stdout_task: asyncio.Task[None] | None = None
        stderr_task: asyncio.Task[None] | None = None
        try:
            process = await _spawn_acp_process(
                self.command,
                env,
                str(
                    require_workspace_root(
                        self.workspace_root, surface="ACP subprocess spawn"
                    )
                ),
                use_exec=self.use_exec,
                metadata=runtime_log_extra(
                    self._config,
                    handshake_step="spawn",
                    timeout_seconds=settings.acp_startup_timeout_seconds,
                ),
            )

            if process.stdin is None or process.stdout is None:
                raise RuntimeError("ACP subprocess failed to open stdio pipes")
            ctx = AcpSessionContext(
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

            init_result = await initialize_session(ctx, self._config)
            self._auth_methods = init_result.auth_methods
            result = await setup_session(
                ctx,
                self._config,
                init_result.agent_capabilities,
                init_result.auth_methods,
            )
            self._active_session_id = result.session_id
            self._session_config_options = result.config_options
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
            # Independent cleanup: a failure in any one release must not skip
            # the rest. MCP surfacing writes nothing to the workspace or the
            # config home, so the session tree is the only thing to release;
            # the CLI's own transcript lives in the operator's real config home
            # (like any interactive session) and is not ours to move.
            cleanup_steps: list[CleanupStep] = []
            if ctx is not None and stdout_task is not None and stderr_task is not None:
                session_ctx, out_task, err_task = ctx, stdout_task, stderr_task
                cleanup_steps.append(
                    (
                        "acp-session",
                        lambda: self._cleanup_session(session_ctx, out_task, err_task),
                    )
                )
            await run_independent_cleanups(*cleanup_steps)

    def _enforce_turn_deadline(self, ctx: AcpSessionContext) -> None:
        """Fail the turn once the subprocess has gone silent for too long.

        The queue poll below only ends on a sentinel or on ``prompt_done``, both
        of which require the subprocess to say something. An agent that stays
        alive but stops emitting frames - a wedged tool call, a lost upstream
        connection - therefore parks the caller forever. Bound that by silence
        rather than by total turn length, so a genuinely long run is never cut
        off: every frame resets the clock.
        """
        idle_limit = settings.acp_turn_idle_timeout_seconds
        if idle_limit <= 0:
            return
        idle_seconds = ctx.seconds_since_activity()
        if idle_seconds < idle_limit:
            return
        logger.error(
            "ACP turn exceeded the idle deadline",
            extra=runtime_log_extra(
                self._config,
                process=ctx.process,
                handshake_step="session/prompt",
                timeout_seconds=idle_limit,
                stderr_event_count=ctx.stderr_event_count,
            ),
        )
        raise AcpPromptError(
            f"ACP turn produced no protocol activity for {idle_seconds:.0f}s "
            f"(deadline {idle_limit:.0f}s); treating the session as hung.",
            code=AcpErrorCode.INTERNAL_ERROR,
            data={"acp_outcome": "turn_idle_deadline_expired"},
        )

    async def _yield_chunks(
        self,
        ctx: AcpSessionContext,
        prompt_future: AcpResponseFuture,
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
                            _raise_prompt_error(resp)
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
                        _raise_prompt_error(resp)
                self._enforce_turn_deadline(ctx)
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

        # Propagate any interrupt that raced with end_turn
        if ctx.interrupt_exc:
            raise ctx.interrupt_exc[0]

    async def _cleanup_session(
        self,
        ctx: AcpSessionContext,
        stdout_task: asyncio.Task[None],
        stderr_task: asyncio.Task[None],
    ) -> None:
        """Terminate the subprocess and its tasks independently, aggregating errors.

        Each teardown step - reaping spawned terminals, cancelling the session,
        cancelling the in-flight background RPC tasks, cancelling the reader
        tasks, and killing the process tree - runs regardless of an earlier step's
        failure, so one error can never skip a later release (which would leak the
        subprocess or a terminal). Failures are aggregated rather than discarded.
        Ordering is preserved: session-cancel runs before the kill so the
        subprocess can flush its state.
        """

        async def _reap_terminals() -> None:
            # Each terminal is independent of the others.
            for _tid, proc in list(ctx.terminals.items()):
                with suppress(Exception):
                    await _kill_process_tree(proc)
            ctx.terminals.clear()

        async def _cancel_session() -> None:
            if not (self._active_session_id and not ctx.prompt_done.is_set()):
                return
            # session/cancel must be a proper JSON-RPC (with id) and awaited with a
            # 3-second timeout so the subprocess flushes its state before the kill.
            rpc_id = AcpRequestId.SESSION_CANCEL
            future = await issue_request(
                ctx.response_futures,
                stdin=ctx.stdin,
                stdin_lock=ctx.stdin_lock,
                rpc_id=rpc_id,
                method="session/cancel",
                params={"sessionId": self._active_session_id},
            )
            await await_response(future, timeout=3.0)

        async def _cancel_background_tasks() -> None:
            for task in list(ctx.background_tasks):
                task.cancel()
            if ctx.background_tasks:
                await asyncio.gather(*ctx.background_tasks, return_exceptions=True)

        async def _cancel_reader_tasks() -> None:
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        async def _kill_process() -> None:
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

        await run_independent_cleanups(
            ("acp-terminals", _reap_terminals),
            ("acp-session-cancel", _cancel_session),
            ("acp-background-tasks", _cancel_background_tasks),
            ("acp-reader-tasks", _cancel_reader_tasks),
            ("acp-process-tree", _kill_process),
        )

        self._process = None
        self._response_futures = None
        self._active_session_id = None
        ctx.tool_calls = {}
        ctx.agent_modes = {}
        ctx.last_auth_url = None

    @override
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

    @override
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
    @override
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

    def _require_response_futures(self) -> AcpResponseFutures:
        if self._response_futures is None:
            raise RuntimeError("No active session response futures.")
        return self._response_futures

    async def _read_stderr_loop(self, ctx: AcpSessionContext) -> None:
        if ctx.process.stderr is None:
            return
        while line := await ctx.process.stderr.readline():
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                self._capture_auth_progress(text, ctx)
                ctx.stderr_event_count += 1
                # Diagnostics are proof of life too. The turn deadline exists to
                # catch a silent hang, and the expensive mistake is felling an
                # agent that is genuinely working, so any sign of life resets it.
                # An agent wedged in a chatty retry loop survives longer as a
                # result - the deliberate trade, since that one is at least
                # visible in the log while a silent hang is not.
                ctx.mark_activity()
                logger.debug(
                    "ACP STDERR: %s",
                    text,
                    extra=runtime_log_extra(
                        self._config,
                        process=ctx.process,
                        stderr_event_count=ctx.stderr_event_count,
                    ),
                )

    def _capture_auth_progress(self, text: str, ctx: AcpSessionContext) -> None:
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
        future = await issue_request(
            self._require_response_futures(),
            stdin=self._require_stdin(),
            stdin_lock=self._stdin_lock,
            rpc_id=rpc_id,
            method="session/fork",
            params={"sessionId": sid},
        )
        resp = await await_response(
            future, timeout=settings.acp_startup_timeout_seconds
        )
        return _required_session_id(
            lenient_json_object(resp.get("result")), operation="fork"
        )

    async def list_sessions(self) -> list[JsonObject]:
        """List all sessions."""
        self._require_session()
        rpc_id = AcpRequestId.SESSION_LIST
        future = await issue_request(
            self._require_response_futures(),
            stdin=self._require_stdin(),
            stdin_lock=self._stdin_lock,
            rpc_id=rpc_id,
            method="session/list",
            params={},
        )
        resp = await await_response(future, timeout=settings.acp_rpc_timeout_seconds)
        return lenient_json_object_list(
            lenient_json_object(resp.get("result")).get("sessions")
        )

    async def set_mode(self, mode_id: str) -> JsonObject:
        """Set agent mode."""
        sid = self._require_session()
        rpc_id = AcpRequestId.SESSION_SET_MODE
        future = await issue_request(
            self._require_response_futures(),
            stdin=self._require_stdin(),
            stdin_lock=self._stdin_lock,
            rpc_id=rpc_id,
            method="session/set_mode",
            params={"sessionId": sid, "modeId": mode_id},
        )
        resp = await await_response(future, timeout=settings.acp_rpc_timeout_seconds)
        return lenient_json_object(resp.get("result"))

    async def authenticate(self, token: str) -> JsonObject:
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
        env = resolve_env_vars(
            require_workspace_root(
                self.workspace_root, surface="ACP authentication environment"
            )
        )
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
