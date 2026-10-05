"""Codex ``app-server`` provider — a non-ACP JSON-RPC-over-stdio chat model.

``codex app-server`` speaks a bespoke JSON-RPC-over-stdio protocol (newline-
delimited JSON, ``{id, method, params}`` requests answered by ``{id, result}``
or ``{id, error}``, ``{method, params}`` notifications in both directions). It is
neither ACP nor an OpenAI Chat-Completions endpoint, so it cannot reuse
``AcpChatModel`` or ``ChatOpenAI``. This module drives the protocol directly,
following the ``mock_chat_model.py`` precedent of a non-ACP ``BaseChatModel`` and
reusing ``_subprocess.py``'s protocol-agnostic process-lifecycle helpers.

Authentication is file-based: ``codex app-server`` inherits the persisted local
session from the Codex home (``~/.codex`` by default, ``CODEX_HOME`` override),
which survives the workspace env scrub because only secret *keys* are stripped,
never ``USERPROFILE``/``HOME``. No API key or secret env injection is required for
the ChatGPT-session auth mode.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, override

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
)
from langchain_core.messages.ai import (
    UsageMetadata,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from ..control.config import settings
from ..desktop.native_isolation import NativeLaunchAuthority, NativeWorkspaceAuthority
from ..team.team_config import AgentConfig
from ..utils.enums import CodexWebSearchMode
from ..workspace.environment import resolve_env_vars
from ._acp_mcp import codex_mcp_server_specs
from ._acp_types import (
    NativeCommandOutcome,
    NativeCommandResult,
    PermissionCallback,
    require_workspace_root,
)
from ._cleanup import CleanupStep, run_independent_cleanups
from ._codex_app_server_client import (
    _CAPABILITIES,
    _CLIENT_INFO,
    _MAX_CODEX_RUNTIME_ID_LENGTH,
    _NATIVE_CONTROL_TIMEOUT_SECONDS,
    _STREAM_CLOSED,
    _CodexAppServerClient,
)
from ._codex_authoring_ready import verify_authoring_ready
from ._codex_config_home import (
    build_codex_config_home,
    cleanup_codex_config_home,
    resolve_codex_web_search_mode,
)
from ._codex_permission import (
    CodexPermissionRung,
)
from ._codex_protocol import (
    _ACTION_ITEM_TYPES,
    _carry_condition,
    _CodexProtocolError,
    _completed_action_chunk,
    _failed_turn_error,
    _messages_to_prompt,
    _required_object_field,
    _required_string_field,
    _turn_failure,
    _usage_metadata,
)
from ._json_contract import JsonObject, lenient_json_object
from ._mcp_contract import verify_harness_mcp_contract
from ._native_role import require_native_workspace
from ._project_scope import RunProjectScope
from ._runtime_identity import RuntimeIdentityBinding, identity_path, identity_text
from ._subprocess import kill_process_tree, spawn_acp_process
from .binary_version import probe_binary_version
from .conditions import ProviderCondition
from .lane_admission import is_web_lane_proven

if TYPE_CHECKING:
    from ..graph.protocols import RuntimeIdentityRecordArgs

logger = logging.getLogger(__name__)

__all__ = [
    "CodexChatModel",
]


@dataclass(slots=True)
class _ActiveCodexTurn:
    client: "_CodexAppServerClient"
    interrupt_in_flight: bool = False
    terminal_status: str | None = None
    terminal_seen: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(slots=True)
class _TurnStreamState:
    """Keep retry evidence and cumulative usage until the turn settles once."""

    deferred: _CodexProtocolError | None = None
    usage: UsageMetadata | None = None
    effects_may_have_occurred: bool = False


class CodexChatModel(BaseChatModel):
    """Chat model backed by a ``codex app-server`` JSON-RPC-over-stdio subprocess.

    Each generation spawns a fresh ``codex app-server``, performs the
    ``initialize``/``initialized`` handshake, opens an ephemeral read-only thread,
    and drives one turn. Assistant-message deltas stream out as
    :class:`ChatGenerationChunk`; the terminal ``turn/completed`` frame closes the
    stream. The subprocess and its tree are always reaped, even on error.
    """

    command: list[str] = Field(default_factory=lambda: ["codex", "app-server"])
    model_name: str | None = None
    effort: str | None = None
    service_tier: str | None = None
    workspace_root: str | None = None
    codex_home: str | None = None
    # Per-model override of the deployment's web-search posture, resolved against
    # ``settings.codex_web_search_mode`` when unset - the same precedence
    # ``codex_home`` above uses. Never an escape from lane admission: the gate is
    # applied after this value is read, so an override can narrow a proven lane's
    # reach and can never widen an unproven one's.
    web_search_mode: CodexWebSearchMode | None = None
    harness_mcp_servers: list[str] = Field(default_factory=list)
    # The run's per-run authoring bridge, in the same flat spec shape
    # ``codex_mcp_server_specs`` returns for the read-only harness registry
    # (``{name, command, args, env, tools}``) - set via ``with_authoring_mcp_
    # server`` (the Codex counterpart of the ACP lane's ``with_mcp_servers``
    # authoring attach, dispatched from ``_acp_authoring.attach_authoring_
    # tools``). Kept separate from ``harness_mcp_servers`` (names only, resolved
    # through the closed registry) because the bridge is a per-run, non-registry
    # spec the worker builds fresh every turn from the engine catalog.
    authoring_mcp_server: JsonObject | None = Field(default=None, exclude=True)
    # The Codex counterpart of ``AcpChatModel.permission_callback``, in the same
    # field shape so the two lanes converge: the worker node wires a supervised
    # run's human rung onto any model that DECLARES this attribute
    # (``resolve_effective_worker_model``), which is why its absence used to
    # skip Codex silently rather than fail. Left unset, the lane is autonomous
    # and decides against the run's composed surface.
    permission_callback: PermissionCallback | None = Field(
        default=None,
        description="Optional async callback for custom permission handling.",
        exclude=True,
    )
    approval_policy: str = "never"
    sandbox: str = "read-only"
    # Bounds the startup and per-request RPC waits only - the single-shot calls
    # the factory's ``provider_timeout_seconds`` is documented for. A silent
    # streaming turn is a different quantity and is bounded separately by
    # ``acp_turn_idle_timeout_seconds``; see ``_consume_turn``.
    timeout: float = 300.0
    agent_config: AgentConfig | None = Field(default=None, exclude=True)

    # Observability metadata (mirrors AcpChatModel's runtime fields).
    provider: str = "codex"
    execution_mode: str | None = Field(default=None, exclude=True)
    runtime_authority: str | None = None
    command_origin: str | None = None
    command_kind: str | None = None
    command_executable: str | None = None
    command_target: str | None = None
    version_proof_required: bool = Field(default=False, exclude=True)

    _active_turns: dict[tuple[str, str], _ActiveCodexTurn] = PrivateAttr(
        default_factory=dict
    )
    _runtime_identity: RuntimeIdentityBinding | None = PrivateAttr(default=None)
    _native_workspace: NativeWorkspaceAuthority | None = PrivateAttr(default=None)

    def with_native_workspace(
        self, authority: NativeWorkspaceAuthority
    ) -> "CodexChatModel":
        """Bind one invocation without retaining its later role home on the model."""
        updated = self.model_copy()
        updated._native_workspace = authority
        return updated

    def with_runtime_identity(
        self, binding: RuntimeIdentityBinding
    ) -> "CodexChatModel":
        """Return a run-bound copy without mutating the compiled model."""
        updated = self.model_copy()
        updated._runtime_identity = binding
        return updated

    async def _persist_runtime_identity(
        self,
        initialize_result: JsonObject,
        provider_thread_id: str,
        *,
        native_authority: NativeLaunchAuthority | None = None,
    ) -> None:
        """Record the first app-server thread before starting its model turn."""
        binding = self._runtime_identity
        if binding is None:
            return
        user_agent = identity_text(
            initialize_result.get("userAgent"),
            field="Codex server user agent",
            maximum=512,
        )
        match = re.match(r"^[^/\s]+/(\d+\.\d+\.\d+)\s+\(", user_agent)
        if match is None:
            raise _CodexProtocolError(
                "Codex initialize omitted a versioned server identity"
            )
        cli = identity_path(self.command_target, field="Codex CLI executable path")
        cli_version = await asyncio.to_thread(
            probe_binary_version, cli, native_authority=native_authority
        )
        if match.group(1) != cli_version:
            raise _CodexProtocolError(
                "Codex initialize version disagrees with the resolved launcher"
            )
        evidence: RuntimeIdentityRecordArgs = {
            "thread_id": binding.thread_id,
            "provider_id": identity_text(self.provider, field="provider ID"),
            "execution_mode": identity_text(
                self.execution_mode, field="execution mode"
            ),
            "runtime_authority": identity_text(
                self.runtime_authority, field="runtime authority"
            ),
            "adapter_name": "codex-app-server",
            "adapter_version": match.group(1),
            "adapter_entry_path": cli,
            "cli_executable_path": cli,
            "cli_version": cli_version,
            "node_version": None,
            "auth_mode": "codex_home",
            "provider_session_id": identity_text(
                provider_thread_id, field="provider thread ID", maximum=512
            ),
            "managed_policy_present": None,
        }
        await binding.port.record_identity(**evidence)

    @property
    @override
    def _llm_type(self) -> str:
        return "codex-chat-model"

    def with_harness_mcp_servers(self, names: Sequence[str]) -> "CodexChatModel":
        """Return a copy that delivers the declared harness servers to Codex.

        Codex's harness-delivery mechanism, parallel to ``AcpChatModel.with_mcp_
        servers`` on the ACP lane: it records the declared server NAMES, which
        ``_astream`` serializes into the per-run ``CODEX_HOME`` ``config.toml``
        (the read-verb constraint is applied there). ``compose_harness_mcp_servers``
        dispatches to this method, so the preset's ``[team.harness]`` declaration
        reaches Codex through the same composition seam as the ACP providers rather
        than being silently dropped.
        """
        return self.model_copy(update={"harness_mcp_servers": list(names)})

    def with_authoring_mcp_server(self, spec: JsonObject | None) -> "CodexChatModel":
        """Return a copy carrying the run's per-run authoring bridge spec.

        Codex's counterpart of the ACP lane's ``with_mcp_servers`` authoring
        attach: ``_acp_authoring.attach_authoring_tools`` calls this with the
        flat spec ``codex_authoring_mcp_server_spec`` builds from the run's
        ``AuthoringToolBinding`` so ``_build_codex_config_home`` can union it
        into the per-run ``config.toml`` alongside any declared harness servers.
        """
        return self.model_copy(update={"authoring_mcp_server": spec})

    def _compose_mcp_specs(self) -> list[JsonObject]:
        """Return the MCP servers this turn declares, harness first then bridge.

        The single composition: the ``config.toml`` the provider reads and the
        permission rung that approves its calls are both derived from this one
        list, so the surface a run auto-approves cannot drift from the surface it
        actually delivered. The authoring bridge never replaces a same-named
        harness entry - the two cannot collide in practice, but the order keeps
        the harness registry as the trust root regardless.
        """
        specs = (
            codex_mcp_server_specs(
                self.harness_mcp_servers, project_root=self.workspace_root
            )
            if self.harness_mcp_servers
            else []
        )
        if self.authoring_mcp_server is not None:
            known = {
                _required_string_field(spec, "name", context="MCP server")
                for spec in specs
            }
            authoring_name = _required_string_field(
                self.authoring_mcp_server, "name", context="authoring MCP server"
            )
            if authoring_name not in known:
                specs = [*specs, self.authoring_mcp_server]
        return specs

    def _composed_tool_pairs(self) -> frozenset[tuple[str, str]]:
        """Return every ``(server, tool)`` this turn composed.

        The exact set the autonomous permission rung may approve. Read from the
        same specs that become the ``enabled_tools`` allowlist, so a tool the run
        never declared can never be approved by it.
        """
        pairs: set[tuple[str, str]] = set()
        for spec in self._compose_mcp_specs():
            name = _required_string_field(spec, "name", context="MCP server")
            tools = spec.get("tools")
            if not isinstance(tools, list):
                continue
            pairs.update(
                (name, tool) for tool in tools if isinstance(tool, str) and tool
            )
        return frozenset(pairs)

    def _build_codex_config_home(self) -> Path:
        """Build the worker-owned per-run CODEX_HOME for this Codex turn.

        Returns the home path (whose ``config.toml`` carries the declared
        read-only harness servers PLUS, when armed, the run's own authoring
        bridge, its explicit web-grounding posture, and whose ``auth.json`` is
        copied from the base home). The home is created even with no declared
        servers: otherwise app-server would read the operator's ambient
        ``~/.codex/config.toml`` and inherit unowned MCP servers. The caller
        sets ``CODEX_HOME`` to it and cleans it up after reap. Extracted from
        ``_astream`` so the composition-to-emission path is testable without a
        live Codex turn.

        ADD-only union by name, mirroring the ACP lane's session-inject union in
        ``_project_composition_onto_model``: the harness registry's read-only
        servers first, then the authoring bridge appended (never replacing a
        same-named harness entry - the registry and the bridge's own
        ``AUTHORING_MCP_SERVER_NAME`` cannot collide in practice, but the order
        keeps the harness registry as the trust root regardless).

        The web posture is resolved here, at the only place a Codex home is built,
        from the lane-admission verdict for this model's own declared lane. Codex
        has no allowlistable web tool name to withhold, so this config write is the
        entire activation surface for the capability on this lane: a lane with no
        recorded retrieval proof emits ``disabled`` and can reach nothing.
        """
        # The Codex lane carries harness NAMES across the seam and renders its
        # specs here, so the run's project is applied at render time rather than
        # to an already-rendered spec as the ACP lane does. Same channel, same
        # refusal to invent a root when the run names none.
        specs = self._compose_mcp_specs()
        base = self.codex_home or settings.codex_home
        # Codex keeps its own login here; a2a only reads it to seed a run home.
        base_home = Path(base) if base else Path.home() / ".codex"  # storage-anchor-ok
        configured = self.web_search_mode
        if configured is None:
            configured = settings.codex_web_search_mode
        return build_codex_config_home(
            specs,
            base_home,
            web_search=resolve_codex_web_search_mode(
                web_proven=is_web_lane_proven(self.provider),
                configured=configured,
            ),
            base_url_override=settings.codex_base_url_override,
        )

    @override
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Synchronous generation is unsupported; use the async path."""
        raise NotImplementedError(
            "CodexChatModel only supports async via _astream/_agenerate"
        )

    @override
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        """Accumulate the streamed chunks into a single ``ChatResult``."""
        generation: ChatGenerationChunk | None = None
        async for chunk in self._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            generation = chunk if generation is None else generation + chunk

        message = generation.message if generation else AIMessageChunk(content="")
        final = AIMessage(
            content=message.content,
            additional_kwargs=message.additional_kwargs,
            response_metadata=message.response_metadata,
            # Carried across the chunk-to-message boundary explicitly: dropping
            # it here is what made the turn's real token accounting invisible to
            # every caller of the non-streaming path.
            usage_metadata=(
                message.usage_metadata if isinstance(message, AIMessageChunk) else None
            ),
        )
        return ChatResult(generations=[ChatGeneration(message=final)])

    def _workspace(self) -> Path:
        """Return the one precedence-resolved workspace path for a Codex turn."""
        return require_workspace_root(
            self.workspace_root, surface="Codex turn workspace"
        )

    def _build_env(self, workspace: Path) -> dict[str, str]:
        """Return the subprocess env: scrubbed base plus an optional CODEX_HOME.

        Codex's persisted-session auth is file-based, so no secret is injected —
        only the non-secret ``CODEX_HOME`` override when configured.
        """
        env = resolve_env_vars(workspace)
        codex_home = self.codex_home or settings.codex_home
        if codex_home and codex_home.strip():
            env["CODEX_HOME"] = codex_home
        return env

    @staticmethod
    def _validate_runtime_id(value: str, *, field: str) -> None:
        if (
            not value
            or value != value.strip()
            or not value.isprintable()
            or len(value) > _MAX_CODEX_RUNTIME_ID_LENGTH
        ):
            raise ValueError(f"{field} is not an exact bounded runtime identity")

    def active_native_control_targets(self) -> tuple[tuple[str, str], ...]:
        """Return the exact Codex thread/turn pairs this instance currently owns."""
        return tuple(sorted(self._active_turns))

    def _native_control_admission(
        self, name: str, thread_id: str, turn_id: str
    ) -> _ActiveCodexTurn | NativeCommandResult:
        if name != "interrupt":
            return NativeCommandResult(
                name=name,
                outcome=NativeCommandOutcome.UNSUPPORTED,
                reason="Codex did not expose this control through the admitted lane",
            )
        self._validate_runtime_id(thread_id, field="thread_id")
        self._validate_runtime_id(turn_id, field="turn_id")
        active = self._active_turns.get((thread_id, turn_id))
        if active is None:
            return NativeCommandResult(
                name=name,
                outcome=NativeCommandOutcome.BLOCKED,
                reason="the exact Codex turn is not active on this provider instance",
            )
        if active.terminal_seen.is_set():
            return NativeCommandResult(
                name=name,
                outcome=NativeCommandOutcome.BLOCKED,
                reason="the exact Codex turn has already ended",
            )
        if active.interrupt_in_flight:
            return NativeCommandResult(
                name=name,
                outcome=NativeCommandOutcome.BUSY,
                reason="an interrupt request already owns this exact Codex turn",
            )
        return active

    async def execute_native_control(
        self,
        name: str,
        *,
        thread_id: str,
        turn_id: str,
    ) -> NativeCommandResult:
        """Execute one proven Codex control against one exact active turn."""
        admission = self._native_control_admission(name, thread_id, turn_id)
        if isinstance(admission, NativeCommandResult):
            return admission
        active = admission

        active.interrupt_in_flight = True
        deadline = asyncio.get_running_loop().time() + _NATIVE_CONTROL_TIMEOUT_SECONDS
        try:
            await asyncio.wait_for(
                active.client.request(
                    "turn/interrupt",
                    {"threadId": thread_id, "turnId": turn_id},
                ),
                timeout=_NATIVE_CONTROL_TIMEOUT_SECONDS,
            )
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError
            await asyncio.wait_for(active.terminal_seen.wait(), timeout=remaining)
        except TimeoutError:
            return NativeCommandResult(
                name=name,
                outcome=NativeCommandOutcome.FAILED,
                reason=(
                    "Codex did not confirm the exact turn as interrupted before "
                    "the deadline"
                ),
                effects_may_have_occurred=True,
            )
        except _CodexProtocolError as exc:
            return NativeCommandResult(
                name=name,
                outcome=NativeCommandOutcome.FAILED,
                reason=str(exc),
                effects_may_have_occurred=True,
            )
        finally:
            active.interrupt_in_flight = False
        if active.terminal_status != "interrupted":
            return NativeCommandResult(
                name=name,
                outcome=NativeCommandOutcome.FAILED,
                reason=(
                    "Codex acknowledged interruption but the exact turn ended as "
                    f"{active.terminal_status!r}"
                ),
                effects_may_have_occurred=True,
            )
        return NativeCommandResult(
            name=name,
            outcome=NativeCommandOutcome.COMPLETED,
            effects_may_have_occurred=True,
        )

    @override
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Drive one Codex turn, streaming assistant-message deltas."""
        prompt = _messages_to_prompt(messages)
        if not prompt.strip():
            raise ValueError("CodexChatModel received no prompt content")

        workspace = self._workspace()
        require_native_workspace(self._native_workspace, workspace)
        env = self._build_env(workspace)
        # Per-run isolated CODEX_HOME: ALWAYS emit a worker-owned config.toml,
        # carrying exactly the declared read-only servers when any are armed,
        # and redirect CODEX_HOME to it. This suppresses the operator's ambient
        # [mcp_servers.*] config even for an otherwise tool-free turn. Auth
        # (auth.json) is copied from the base home.
        # The home is built INSIDE the try so a spawn failure cannot leak the
        # copied credential; it is cleaned up in the finally regardless of where
        # the turn fails.
        # Verify inside the cleanup scope after role preparation: independent
        # probes need the same selected home and filesystem authority. The
        # declared tool names become
        # this lane's ``enabled_tools`` allowlist, so a server that no longer
        # serves one of them would leave Codex permitted to call a tool that does
        # not exist. The ACP lane applies the identical check at its own spawn
        # seam; one registry, one contract, both transports. The launch spec
        # carries no version constraint by design - this check is what makes the
        # declaration trustworthy - and it is memoized per launch identity.
        codex_config_home: Path | None = None
        client: _CodexAppServerClient | None = None
        process: asyncio.subprocess.Process | None = None
        try:
            codex_config_home = self._build_codex_config_home()
            native_authority = (
                self._native_workspace.for_home(codex_config_home)
                if self._native_workspace is not None
                else None
            )
            env["CODEX_HOME"] = str(codex_config_home)
            await verify_harness_mcp_contract(
                codex_mcp_server_specs(
                    self.harness_mcp_servers, project_root=self.workspace_root
                ),
                env=env,
                native_authority=native_authority,
            )
            if self.version_proof_required:
                from .factory import codex_binary_proof_reason, require_binary_proof

                require_binary_proof(
                    codex_binary_proof_reason(
                        self.command, native_authority=native_authority
                    )
                )
            metadata = {
                "provider": self.provider,
                "command_executable": self.command_executable,
                "command_target": self.command_target,
            }

            process = await spawn_acp_process(
                self.command,
                env,
                str(workspace),
                use_exec=False,
                metadata=metadata,
                native_authority=native_authority,
            )
            client = _CodexAppServerClient(
                process,
                metadata=metadata,
                permission_rung=CodexPermissionRung(
                    allowed_tools=self._composed_tool_pairs(),
                    permission_callback=self.permission_callback,
                    project_scope=RunProjectScope(self.workspace_root),
                ),
            )
            initialize_result = await asyncio.wait_for(
                client.request(
                    "initialize",
                    {"clientInfo": _CLIENT_INFO, "capabilities": _CAPABILITIES},
                ),
                timeout=self.timeout,
            )
            client.notify("initialized", {})

            thread = await asyncio.wait_for(
                client.request(
                    "thread/start",
                    {
                        "cwd": str(workspace),
                        "model": self.model_name,
                        "approvalPolicy": self.approval_policy,
                        "sandbox": self.sandbox,
                        "ephemeral": True,
                        "experimentalRawEvents": False,
                    },
                ),
                timeout=self.timeout,
            )
            thread_id = _required_string_field(
                _required_object_field(thread, "thread", context="thread/start result"),
                "id",
                context="thread/start result thread",
            )
            await self._persist_runtime_identity(
                initialize_result, thread_id, native_authority=native_authority
            )

            await verify_authoring_ready(
                client,
                thread_id,
                self.authoring_mcp_server,
                timeout=self.timeout,
            )

            turn_started = await asyncio.wait_for(
                client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [
                            {"type": "text", "text": prompt, "text_elements": []}
                        ],
                        "model": self.model_name,
                        "effort": self.effort,
                        "serviceTier": self.service_tier,
                        "outputSchema": None,
                    },
                ),
                timeout=self.timeout,
            )
            turn_id = _required_string_field(
                _required_object_field(
                    turn_started, "turn", context="turn/start result"
                ),
                "id",
                context="turn/start result turn",
            )
            # The lane's own turn identity, reported once per turn: the
            # app-server runs ephemeral inside a per-run home that is deleted
            # afterwards, so these two ids are the only handles tying this run's
            # turn to anything the provider itself saw.
            logger.info(
                "Codex turn started",
                extra={
                    **metadata,
                    "codex_thread_id": thread_id,
                    "codex_turn_id": turn_id,
                },
            )
            active_key = (thread_id, turn_id)
            if active_key in self._active_turns:
                raise _CodexProtocolError(
                    "codex app-server reused an active thread/turn identity"
                )
            active_turn = _ActiveCodexTurn(client)
            self._active_turns[active_key] = active_turn
            try:
                async for chunk in self._consume_turn(
                    client, thread_id, active_turn=active_turn
                ):
                    yield chunk
            finally:
                if self._active_turns.get(active_key) is active_turn:
                    self._active_turns.pop(active_key, None)
        finally:
            # Independent cleanup: a failure reaping the app-server session must
            # not skip removing the per-run CODEX_HOME (it holds a copied
            # credential), and vice versa. Each runs regardless of the other.
            cleanup_steps: list[CleanupStep] = []
            if client is not None:
                cleanup_steps.append(("codex-app-server-session", client.aclose))
            elif process is not None:
                orphaned_process = process
                cleanup_steps.append(
                    (
                        "codex-partial-startup",
                        lambda: kill_process_tree(orphaned_process),
                    )
                )
            # Off the loop: the write-back waits on a lock another run's
            # teardown may hold, and every other run on this loop would wait
            # with it.
            cleanup_steps.append(
                (
                    "codex-config-home",
                    lambda: asyncio.to_thread(
                        cleanup_codex_config_home, codex_config_home
                    ),
                )
            )
            await run_independent_cleanups(*cleanup_steps)

    async def _next_turn_message(
        self,
        client: _CodexAppServerClient,
        idle_limit: float,
        state: _TurnStreamState,
    ) -> JsonObject:
        try:
            message = await asyncio.wait_for(
                client.notifications.get(),
                timeout=idle_limit if idle_limit > 0 else None,
            )
            if message is _STREAM_CLOSED:
                # Prefer the lane's last stated retry failure to a bare EOF.
                if state.deferred is not None:
                    state.deferred.effects_may_have_occurred |= (
                        state.effects_may_have_occurred
                    )
                    raise _carry_condition(state.deferred, None)
                raise await client.unexpected_eof_error()
        except TimeoutError:
            # A stated retry failure is more useful than later silence.
            if state.deferred is not None:
                state.deferred.effects_may_have_occurred |= (
                    state.effects_may_have_occurred
                )
                raise state.deferred from None
            raise
        if client.pending_interrupt is not None:
            raise client.pending_interrupt
        return message

    @staticmethod
    def _turn_item_chunks(
        method: object, params: JsonObject, state: _TurnStreamState
    ) -> list[ChatGenerationChunk]:
        if method == "item/agentMessage/delta":
            delta = params.get("delta")
            if isinstance(delta, str) and delta:
                return [ChatGenerationChunk(message=AIMessageChunk(content=delta))]
        elif method == "item/started":
            item = lenient_json_object(params.get("item"))
            if item.get("type") in _ACTION_ITEM_TYPES:
                state.effects_may_have_occurred = True
        elif method == "item/completed":
            action = _completed_action_chunk(params)
            if action is not None:
                state.effects_may_have_occurred = True
                return [action]
        return []

    @staticmethod
    def _record_turn_error(params: JsonObject, state: _TurnStreamState) -> None:
        failure = _turn_failure(params.get("error"), will_retry=params.get("willRetry"))
        failure.effects_may_have_occurred = state.effects_may_have_occurred
        if failure.will_retry:
            # Preserve the most useful attempted failure while the lane retries.
            if (
                state.deferred is None
                or state.deferred.condition is ProviderCondition.UNKNOWN
            ):
                state.deferred = failure
            return
        raise _carry_condition(failure, state.deferred)

    @staticmethod
    def _complete_turn(
        params: JsonObject,
        active_turn: _ActiveCodexTurn | None,
        state: _TurnStreamState,
    ) -> ChatGenerationChunk | None:
        turn = _required_object_field(
            params, "turn", context="turn/completed notification"
        )
        status = turn.get("status")
        if active_turn is not None:
            active_turn.terminal_status = status if isinstance(status, str) else None
            active_turn.terminal_seen.set()
        if status != "completed":
            failure = _failed_turn_error(turn, status)
            failure.effects_may_have_occurred = state.effects_may_have_occurred
            raise _carry_condition(failure, state.deferred)
        if state.usage is not None:
            # The empty content preserves the accumulated message text.
            return ChatGenerationChunk(
                message=AIMessageChunk(content="", usage_metadata=state.usage)
            )
        return None

    @staticmethod
    def _foreign_turn_notification(
        method: object, params: JsonObject, thread_id: str
    ) -> bool:
        return method != "error" and params.get("threadId") not in (None, thread_id)

    @classmethod
    def _turn_control_notification(
        cls,
        method: object,
        params: JsonObject,
        active_turn: _ActiveCodexTurn | None,
        state: _TurnStreamState,
    ) -> tuple[bool, ChatGenerationChunk | None]:
        if method == "error":
            cls._record_turn_error(params, state)
        elif method == "thread/tokenUsage/updated":
            state.usage = _usage_metadata(
                _required_object_field(
                    _required_object_field(
                        params,
                        "tokenUsage",
                        context="thread/tokenUsage/updated notification",
                    ),
                    "total",
                    context="thread/tokenUsage/updated tokenUsage",
                )
            )
        elif method == "turn/completed":
            return True, cls._complete_turn(params, active_turn, state)
        return False, None

    async def _consume_turn(
        self,
        client: _CodexAppServerClient,
        thread_id: str,
        *,
        active_turn: _ActiveCodexTurn | None = None,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Yield delta chunks until the turn completes, raising on failure.

        Only frames scoped to *thread_id* are honored so a stray sub-thread
        notification never terminates the turn early.

        The wait below is re-armed on every frame, so it bounds the GAP between
        frames, not the turn - the same quantity the other ACP-family providers
        bound with ``acp_turn_idle_timeout_seconds``, and it reads that setting
        for exactly that reason. ``self.timeout`` is deliberately not used here:
        it carries ``provider_timeout_seconds``, a single-shot API-call budget
        that also governs this model's startup RPCs. Spending a request budget
        as a streaming idle backstop cut Codex turns off after 120s of quiet
        while the identical workload survived 600s on every other provider.
        Zero or less disables the backstop, matching the setting's contract.
        """
        idle_limit = settings.acp_turn_idle_timeout_seconds
        state = _TurnStreamState()
        while True:
            message = await self._next_turn_message(client, idle_limit, state)

            method = message.get("method")
            raw_params = message.get("params")
            params = lenient_json_object(raw_params)

            if self._foreign_turn_notification(method, params, thread_id):
                continue
            if method in (
                "item/agentMessage/delta",
                "item/started",
                "item/completed",
            ):
                for chunk in self._turn_item_chunks(method, params, state):
                    yield chunk
                continue
            completed, final_chunk = self._turn_control_notification(
                method, params, active_turn, state
            )
            if final_chunk is not None:
                yield final_chunk
            if completed:
                return
