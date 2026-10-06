r"""AcpChatModel: A LangChain BaseChatModel that wraps ACP-compatible CLIs.

Architecture:
  - Spawns CLI via ``_spawn_acp_process`` (platform-specific — see below)
  - Sends JSON-RPC requests on stdin using `b"%s\n"` format
  - Reads stdout in a walrus readline loop
  - Dispatches responses to asyncio.Future-based waiters
  - Handles bidirectional RPCs (session/request_permission)
  - Yields streaming `agent_message_chunk` notifications as LangChain chunks
  - Maps `tool_call` / `tool_call_update` to ToolCallChunk for LangGraph
  - Supports session/cancel notification for interruption
  - Terminates on `stopReason: "end_turn"`
  - Propagates LangGraph GraphBubbleUp from permission_callback to caller
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from typing import TYPE_CHECKING, Any, Never, override

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import generate_from_stream
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from ..control.config import settings
from ..desktop.native_isolation import NativeLaunchAuthority, NativeWorkspaceAuthority
from ..team.team_config import AgentConfig
from ..workspace.environment import resolve_env_vars
from ._acp_auth import runtime_log_extra
from ._acp_authoring import (
    AUTHORING_MCP_SERVER_NAME,
    config_home_authoring_entry,
)
from ._acp_chunks import notify_chunk
from ._acp_mcp import harness_spawn_env
from ._acp_model_state import (
    AcpModelState,
    AcpSessionBusyError,
    NativeCommandRequest,
    model_state_or_none,
    model_state_path,
    read_model_state,
    write_model_state,
)
from ._acp_native_commands import (
    native_command_error_result,
    native_command_prompt_blocks,
    validate_native_command,
)
from ._acp_prompt_outcomes import (
    raise_for_prompt_stop_reason as _raise_for_prompt_stop_reason,
)
from ._acp_prompt_outcomes import (
    raise_prompt_error as _raise_prompt_error,
)
from ._acp_protocol import process_stdout_loop
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
from ._acp_session_admin import fork_session as _fork_session
from ._acp_session_admin import list_sessions as _list_sessions
from ._acp_session_admin import session_rpc
from ._acp_session_admin import set_mode as _set_mode
from ._acp_stderr import read_stderr_loop
from ._acp_teardown import cleanup_session
from ._acp_turn_failures import abnormal_exit_error, enforce_turn_deadline
from ._acp_types import (
    AcpModelConfig,
    AcpResponseFuture,
    AcpSessionContext,
    NativeCommandOutcome,
    NativeCommandResult,
    PermissionCallback,
    RpcHandlerMap,
    require_workspace_root,
)
from ._cleanup import CleanupStep, run_independent_cleanups
from ._json_contract import JsonObject
from ._mcp_contract import verify_harness_mcp_contract
from ._native_role import prepare_acp_role, require_native_workspace, role_environment
from ._prompt_render import render_prompt_blocks
from ._runtime_identity import RuntimeIdentityBinding, identity_path, identity_text
from ._stream_lifetime import ProcessChatModel
from ._subprocess import kill_process_tree as _kill_process_tree
from ._subprocess import spawn_acp_process as _spawn_acp_process
from .acp_exceptions import AcpError
from .binary_version import probe_binary_version
from .cli_resolution import pin_claude_executable

if TYPE_CHECKING:
    from ..graph.protocols import RuntimeIdentityRecordArgs

__all__ = ["AcpChatModel"]

logger = logging.getLogger(__name__)


class AcpChatModel(ProcessChatModel):
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
    mcp_servers: list[JsonObject] = Field(
        default_factory=list,
        description="MCP server configs to pass via session/new.",
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
    version_proof_required: bool = Field(default=False, exclude=True)
    execution_mode: str | None = Field(default=None, exclude=True)
    runtime_authority: str | None = Field(
        default=None,
        description="Bounded runtime authority classification for the ACP command.",
    )
    acp_backend: str | None = Field(
        default=None,
        description="ACP backend classification such as node, binary, or kimi-code.",
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

    _state: AcpModelState = PrivateAttr()
    _runtime_identity: RuntimeIdentityBinding | None = PrivateAttr(default=None)
    _native_workspace: NativeWorkspaceAuthority | None = PrivateAttr(default=None)
    _native_authority: NativeLaunchAuthority | None = PrivateAttr(default=None)

    def with_runtime_identity(self, binding: RuntimeIdentityBinding) -> "AcpChatModel":
        """Return a run-bound copy without mutating the compiled model."""
        updated = self.model_copy()
        updated._runtime_identity = binding
        return updated

    def with_native_workspace(
        self, authority: NativeWorkspaceAuthority
    ) -> "AcpChatModel":
        """Bind one invocation without serializing native filesystem grants."""
        updated = self.model_copy()
        updated._native_workspace = authority
        return updated

    def __getattr__(self, name: str) -> Any:
        if name in {"_runtime_identity", "_native_workspace", "_native_authority"}:
            private = self.__pydantic_private__
            if private is not None and name in private:
                return private[name]
        state = model_state_or_none(self)
        state_field = model_state_path(name)
        if name == "_state" and state is not None:
            return state
        if state is not None and state_field is not None:
            return read_model_state(state, state_field)
        raise AttributeError(name)

    @override
    def __setattr__(self, name: str, value: Any) -> None:
        state = model_state_or_none(self)
        state_field = model_state_path(name)
        if state is not None and state_field is not None:
            write_model_state(state, state_field, value)
            return
        super().__setattr__(name, value)

    @override
    def model_post_init(self, __context: object) -> None:
        self._state = AcpModelState.from_config(
            config=AcpModelConfig(
                agent_config=self.agent_config,
                permission_callback=self.permission_callback,
                workspace_root=self.workspace_root,
                command=self.command,
                env_vars=dict(self.env_vars),
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
            ),
            previous=model_state_or_none(self),
        )

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
    async def _provider_astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatGenerationChunk]:
        """Streams responses from the ACP subprocess."""
        async with aclosing(
            self._stream_request(
                messages,
                stop=stop,
                run_manager=run_manager,
                native_command=None,
                **kwargs,
            )
        ) as request:
            async for chunk in request:
                yield chunk

    async def _stream_request(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None,
        run_manager: AsyncCallbackManagerForLLMRun | None,
        native_command: NativeCommandRequest | None,
        **kwargs: Any,
    ) -> AsyncGenerator[ChatGenerationChunk]:
        """Own one provider session and refuse concurrent use explicitly."""
        del stop, kwargs
        if self._state.session.session_busy:
            raise AcpSessionBusyError("the provider session is already busy")
        self._state.session.session_busy = True
        try:
            async with aclosing(
                self._astream_session(
                    messages,
                    run_manager=run_manager,
                    native_command=native_command,
                )
            ) as session:
                async for chunk in session:
                    yield chunk
        finally:
            self._state.session.session_busy = False

    async def _acp_environment(self) -> dict[str, str]:
        _ws_path = require_workspace_root(
            self.workspace_root, surface="ACP environment resolution"
        )
        env = resolve_env_vars(_ws_path)
        env.update(self.env_vars)
        if self._native_authority is not None:
            env.update(role_environment(self._native_authority))
        # The served turn and catalog probe use the same profile-scoped CLI
        # authority. Kimi runs its own CLI.
        if self._state.config.acp_family == "claude" and self.command:
            resolved = pin_claude_executable(env)
            self._state.session.claude_executable = str(resolved.path)
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
        if self._state.config.allowed_tools:
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
        await verify_harness_mcp_contract(
            self._state.config.mcp_servers,
            env=env,
            native_authority=self._native_authority,
        )

        # Unisolated profiles use the operator's config home; prepared native
        # roles use only their fresh home and an already selected credential
        # channel. The default subscription file store remains unavailable
        # there until its identity and refresh-return behavior is qualified.
        # For unisolated profiles, the
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
        if self._state.config.mcp_servers:
            _bridge_entry, bridge_env = config_home_authoring_entry(
                self._state.config.mcp_servers
            )
            env.update(bridge_env)
            # Every OTHER advertised spec's env is projected the same way and
            # was never hoisted, so a pinned harness server reached the CLI as a
            # dangling reference and started with its pin unset - looking pinned
            # while resolving its project from the inherited directory.
            env.update(
                harness_spawn_env(
                    self._state.config.mcp_servers, exclude=AUTHORING_MCP_SERVER_NAME
                )
            )
        return env

    def _record_provider_identity(self, ctx: AcpSessionContext) -> None:
        """Log which adapter and which CLI this session actually ran on.

        Neither is recoverable after the fact: the adapter names itself once, in
        the handshake, and the CLI it drives is whatever the pin resolved on this
        host at this moment. A turn whose behaviour needs explaining later - a
        capability that was present or absent, a permission posture that differed
        from the operator's own - is explained by these two facts and by nothing
        else the run keeps.
        """
        agent_info = self._state.session.agent_info
        name = agent_info.get("name")
        version = agent_info.get("version")
        logger.info(
            "ACP provider identity",
            extra=runtime_log_extra(
                self._state.config,
                process=ctx.process,
                handshake_step="initialize",
                agent_name=name if isinstance(name, str) else None,
                agent_version=version if isinstance(version, str) else None,
                cli_executable=self._state.session.claude_executable,
            ),
        )

    async def _persist_runtime_identity(self, session_id: str) -> None:
        """Write the first initialized session before sending a model prompt."""
        binding = self._runtime_identity
        if binding is None:
            return
        entry = identity_path(self.command_target, field="adapter entry path")
        if self.acp_family == "claude":
            cli = identity_path(
                self._state.session.claude_executable, field="CLI executable path"
            )
            node = (
                identity_path(self.command[0], field="Node executable path")
                if self.acp_backend == "node" and self.command
                else None
            )
        else:
            cli = identity_path(self.command[0], field="CLI executable path")
            node = None
        cli_version = await asyncio.to_thread(
            probe_binary_version, cli, native_authority=self._native_authority
        )
        node_version = (
            await asyncio.to_thread(
                probe_binary_version, node, native_authority=self._native_authority
            )
            if node is not None
            else None
        )
        agent_info = self._state.session.agent_info
        evidence: RuntimeIdentityRecordArgs = {
            "thread_id": binding.thread_id,
            "provider_id": identity_text(self.provider, field="provider ID"),
            "execution_mode": identity_text(
                self.execution_mode, field="execution mode"
            ),
            "runtime_authority": identity_text(
                self.runtime_authority, field="runtime authority"
            ),
            "adapter_name": identity_text(agent_info.get("name"), field="adapter name"),
            "adapter_version": identity_text(
                agent_info.get("version"), field="adapter version"
            ),
            "adapter_entry_path": entry,
            "cli_executable_path": cli,
            "cli_version": cli_version,
            "node_version": node_version,
            "auth_mode": identity_text(self.auth_mode, field="auth mode"),
            "provider_session_id": identity_text(
                session_id, field="provider session ID", maximum=512
            ),
            # ACP does not report whether host managed policy existed or loaded.
            "managed_policy_present": None,
        }
        await binding.port.record_identity(**evidence)

    async def _astream_session(
        self,
        messages: list[BaseMessage],
        *,
        run_manager: AsyncCallbackManagerForLLMRun | None,
        native_command: NativeCommandRequest | None,
    ) -> AsyncGenerator[ChatGenerationChunk]:
        """Prepare one role before any independent probe or provider acquisition."""
        workspace = require_workspace_root(
            self.workspace_root, surface="native ACP role preparation"
        )
        require_native_workspace(self._native_workspace, workspace)
        environment = resolve_env_vars(workspace)
        environment.update(self.env_vars)
        async with prepare_acp_role(
            self._native_workspace, environment=environment, provider=self.provider
        ) as authority:
            self._native_authority = authority
            try:
                async with aclosing(
                    self._astream_prepared_session(
                        messages, run_manager=run_manager, native_command=native_command
                    )
                ) as prepared:
                    async for chunk in prepared:
                        yield chunk
            finally:
                self._native_authority = None

    async def _astream_prepared_session(
        self,
        messages: list[BaseMessage],
        *,
        run_manager: AsyncCallbackManagerForLLMRun | None,
        native_command: NativeCommandRequest | None,
    ) -> AsyncGenerator[ChatGenerationChunk]:
        """Run one ordinary prompt or one negotiated native command."""
        # Rendered through the seam the Codex lane shares: a conversation says
        # who spoke and what a tool answered, and it has to say the same thing on
        # whichever transport carries it. Rendering here instead dropped every
        # role label, every speaker name, and every tool result - leaving the
        # agent's own prior turns, another agent's output, and the system
        # instructions arriving as one anonymous voice.
        prompt_blocks: list[JsonObject] = render_prompt_blocks(messages)

        # Start with a credential-free base, then apply the selected provider's
        # explicit auth and gateway overlay from ProviderFactory.
        env = await self._acp_environment()
        if self.version_proof_required:
            from ..graph.enums import Provider
            from .factory import binary_proof_reason, require_binary_proof

            resolved = pin_claude_executable(env)
            require_binary_proof(
                binary_proof_reason(
                    Provider(self.provider),
                    str(resolved.path),
                    resolved.authority,
                    native_authority=self._native_authority,
                )
            )

        # The spawn and session setup run INSIDE the try so the finally below
        # is the single cleanup path: a spawn-time raise (missing binary,
        # startup timeout) or a stdio-pipe failure must not orphan the session
        # tree. ctx and the reader tasks are created here, so the finally
        # guards on their presence before touching the session.
        ctx: AcpSessionContext | None = None
        process: asyncio.subprocess.Process | None = None
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
                    self._state.config,
                    handshake_step="spawn",
                    timeout_seconds=settings.acp_startup_timeout_seconds,
                ),
                native_authority=self._native_authority,
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
                process_stdout_loop(ctx, self._state.config, rpc_map)
            )

            init_result = await initialize_session(ctx, self._state.config)
            self._state.session.auth_methods = init_result.auth_methods
            self._state.session.agent_info = init_result.agent_info
            self._record_provider_identity(ctx)
            result = await setup_session(
                ctx,
                self._state.config,
                init_result.auth_methods,
            )
            self._state.session.active_session_id = result.session_id
            self._state.session.session_config_options = result.config_options
            # The provider's own session id, logged once per turn: it is the only
            # handle that ties this run's turn to the transcript the CLI wrote in
            # the operator's config home, and nothing else records it.
            logger.info(
                "ACP session opened",
                extra=runtime_log_extra(
                    self._state.config,
                    process=ctx.process,
                    handshake_step="session/new",
                    session_id=result.session_id,
                ),
            )
            await self._persist_runtime_identity(result.session_id)
            self._state.transport.process = ctx.process
            self._state.transport.stdin = ctx.stdin
            self._state.transport.stdin_lock = ctx.stdin_lock
            self._state.session.response_futures = ctx.response_futures
            prompt_blocks = await native_command_prompt_blocks(
                ctx, native_command, prompt_blocks, result.session_id
            )
            prompt_future = await setup_prompt(
                ctx,
                self._state.config,
                prompt_blocks,
                self._state.session.active_session_id,
            )

            async for chunk in self._yield_chunks(ctx, prompt_future, run_manager):
                yield chunk
        finally:
            # Independent cleanup: a failure in any one release must not skip
            # the rest. MCP surfacing writes nothing to the workspace or the
            # config home, so the session tree is the only thing to release;
            # unisolated CLI transcript stays in the operator's config tree.
            # A prepared native role's surrounding owner removes its fresh home
            # only after this session cleanup finishes.
            cleanup_steps: list[CleanupStep] = []
            if ctx is not None:
                session_ctx, out_task, err_task = ctx, stdout_task, stderr_task
                cleanup_steps.append(
                    (
                        "acp-session",
                        lambda: self._cleanup_session(session_ctx, out_task, err_task),
                    )
                )
            elif process is not None:
                orphaned_process = process
                cleanup_steps.append(
                    (
                        "acp-partial-startup",
                        lambda: _kill_process_tree(orphaned_process),
                    )
                )
            await run_independent_cleanups(*cleanup_steps)

    async def execute_native_command(
        self, name: str, arguments: str | None = None
    ) -> NativeCommandResult:
        """Execute one exactly advertised command through ACP prompt syntax."""
        validate_native_command(name, arguments)

        output: list[str] = []
        try:
            async for chunk in self._stream_request(
                [],
                stop=None,
                run_manager=None,
                native_command=NativeCommandRequest(name, arguments),
            ):
                content = chunk.message.content
                if isinstance(content, str):
                    output.append(content)
        except Exception as exc:
            return native_command_error_result(name, exc)
        return NativeCommandResult(
            name=name,
            outcome=NativeCommandOutcome.COMPLETED,
            output="".join(output),
            effects_may_have_occurred=True,
        )

    def _enforce_turn_deadline(self, ctx: AcpSessionContext) -> None:
        """Fail the turn once the subprocess has gone silent for too long."""
        enforce_turn_deadline(
            ctx,
            self._state.config,
            session_id=self._state.session.active_session_id,
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
                    self._raise_for_early_exit(ctx, prompt_future)
                await notify_chunk(run_manager, chunk)
                yield chunk
            except TimeoutError:
                self._raise_if_prompt_future_error(ctx, prompt_future)
                self._enforce_turn_deadline(ctx)
                continue

        while not ctx.chunk_queue.empty():
            chunk = ctx.chunk_queue.get_nowait()
            if chunk is not None:
                await notify_chunk(run_manager, chunk)
                yield chunk

        # Propagate any interrupt that raced with end_turn
        if ctx.interrupt_exc:
            raise ctx.interrupt_exc[0]
        _raise_for_prompt_stop_reason(
            ctx.prompt_stop_reason,
            effects_may_have_occurred=ctx.effects_may_have_occurred,
            usage_metadata=ctx.prompt_usage,
        )
        if ctx.prompt_usage is not None:
            # A terminal-only chunk lets LangChain merge usage into the final
            # message without duplicating text streamed earlier in the turn.
            usage_chunk = ChatGenerationChunk(
                message=AIMessageChunk(content="", usage_metadata=ctx.prompt_usage)
            )
            await notify_chunk(run_manager, usage_chunk)
            yield usage_chunk

    def _raise_for_early_exit(
        self, ctx: AcpSessionContext, prompt_future: AcpResponseFuture
    ) -> Never:
        if ctx.interrupt_exc:
            raise ctx.interrupt_exc[0]
        self._raise_if_prompt_future_error(ctx, prompt_future)
        raise self._abnormal_exit_error(ctx)

    def _abnormal_exit_error(
        self, ctx: AcpSessionContext, cause: BaseException | None = None
    ) -> AcpError:
        """Describe a child that left mid-turn, in its own redacted words."""
        return abnormal_exit_error(
            ctx,
            self._state.config,
            session_id=self._state.session.active_session_id,
            cause=cause,
        )

    def _raise_if_prompt_future_error(
        self, ctx: AcpSessionContext, prompt_future: AcpResponseFuture
    ) -> None:
        if not prompt_future.done():
            return
        # The stdout reader fails every pending request when the child's stream
        # ends, and that failure says only that a pipe closed. What explains it is
        # the child's last words, so the transport error becomes the provider
        # error that carries them rather than reaching the caller bare.
        if (failure := prompt_future.exception()) is not None:
            raise self._abnormal_exit_error(ctx, failure) from failure
        resp = prompt_future.result()
        if "error" in resp:
            _raise_prompt_error(
                resp, effects_may_have_occurred=ctx.effects_may_have_occurred
            )

    async def _cleanup_session(
        self,
        ctx: AcpSessionContext,
        stdout_task: asyncio.Task[None] | None,
        stderr_task: asyncio.Task[None] | None,
    ) -> None:
        """Terminate the subprocess and its tasks independently."""
        await cleanup_session(ctx, self._state, stdout_task, stderr_task)

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
        async with aclosing(
            self._astream(messages, stop=stop, run_manager=run_manager, **kwargs)
        ) as stream:
            async for chunk in stream:
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

    async def _read_stderr_loop(self, ctx: AcpSessionContext) -> None:
        """Drain the child's standard error for the lifetime of the session."""
        await read_stderr_loop(ctx, self._state.config)

    async def fork_session(self) -> str:
        """Fork the current session."""
        return await _fork_session(session_rpc(self._state))

    async def list_sessions(self) -> list[JsonObject]:
        """List all sessions."""
        return await _list_sessions(session_rpc(self._state))

    async def set_mode(self, mode_id: str) -> JsonObject:
        """Set agent mode."""
        return await _set_mode(session_rpc(self._state), mode_id)
