"""ACP data carriers: config, context, and result types.

Extracted from ``_acp_session.py`` to isolate pure data definitions
from auth logic and session lifecycle RPCs.
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from langchain_core.messages import UsageMetadata
from langchain_core.outputs import ChatGenerationChunk

from ..control.workspace import (
    canonical_workspace_root,
    configured_workspace_boundary,
    require_admitted_workspace_root,
)
from ..team.team_config import AgentConfig
from ..utils import redact_text
from ._acp_terminal_output import AcpTerminalOutput
from ._json_contract import JsonObject
from ._project_scope import RunProjectScope
from ._subprocess import STDERR_TAIL_LINES

__all__: list[str] = []


type AcpRpcId = int | str
type AcpResponseFuture = asyncio.Future[JsonObject]
type AcpResponseFutures = dict[int, AcpResponseFuture]

PermissionCallback = Callable[[str, JsonObject, list[JsonObject]], Awaitable[str]]
MAX_ACP_SESSION_ID_LENGTH = 512
MAX_NATIVE_COMMAND_NAME_LENGTH = 128
MAX_SESSION_COMMAND_CATALOGS = 16


class AcpUsageMetadata(UsageMetadata, total=False):
    """LangChain turn usage with the ACP adapter's per-model breakdown."""

    model_usage: dict[str, UsageMetadata]


class NativeCommandDisposition(StrEnum):
    """Whether one command can be invoked in the current provider session."""

    SUPPORTED = "supported"
    BLOCKED = "blocked"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class NativeCommandAvailability:
    """One exact command's session-scoped availability and input contract."""

    name: str
    disposition: NativeCommandDisposition
    description: str | None = None
    input_hint: str | None = None
    reason: str | None = None


@dataclass(slots=True)
class AcpNativeCommandCatalog:
    """Validated replacement snapshots from ACP available-command updates."""

    commands: dict[str, NativeCommandAvailability] = field(default_factory=dict)
    received: bool = False
    blocked_reason: str | None = None

    def replace(
        self,
        commands: dict[str, NativeCommandAvailability],
        *,
        blocked_reason: str | None = None,
    ) -> None:
        """Replace the session snapshot atomically, including its validity state."""
        self.commands = dict(commands)
        self.received = True
        self.blocked_reason = blocked_reason

    def resolve(self, name: str) -> NativeCommandAvailability:
        """Resolve one exact command without inventing aliases or default support."""
        if (
            not name
            or name != name.strip()
            or not name.isprintable()
            or len(name) > MAX_NATIVE_COMMAND_NAME_LENGTH
        ):
            raise ValueError("native command name must be non-empty, trimmed text")
        if self.blocked_reason is not None:
            return NativeCommandAvailability(
                name=name,
                disposition=NativeCommandDisposition.BLOCKED,
                reason=self.blocked_reason,
            )
        if not self.received:
            return NativeCommandAvailability(
                name=name,
                disposition=NativeCommandDisposition.BLOCKED,
                reason="the provider has not advertised commands for this session",
            )
        advertised = self.commands.get(name)
        if advertised is not None:
            return advertised
        return NativeCommandAvailability(
            name=name,
            disposition=NativeCommandDisposition.UNSUPPORTED,
            reason="the provider did not advertise this command for the session",
        )


def require_workspace_root(value: str | None, *, surface: str) -> Path:
    """Return the run's workspace root, or refuse to invent one.

    Every directory an agent lane touches - the subprocess spawn directory, the
    environment resolution root, the session working directory, and the
    filesystem and terminal sandbox roots - is the active project the run was
    created with. There is no default. The absent case used to resolve to the
    serving process's own working directory, which put agent execution and its
    sandbox boundary inside this service's tree; a sandbox root derived from
    ambient process state is not a boundary at all.

    Reaching this raise means a run was admitted without an active project,
    which the run-creation seam refuses, so it indicates a construction path
    that bypassed it rather than a user error.
    """
    if not value:
        msg = (
            f"{surface} requires the run's workspace root; none was supplied. "
            "The active project is carried from run creation and is never "
            "derived from the serving process."
        )
        raise ValueError(msg)
    if configured_workspace_boundary() is not None:
        return canonical_workspace_root(require_admitted_workspace_root(value))
    return Path(value)


@dataclass(frozen=True)
# Frozen ACP configuration is passed unchanged through provider helpers.
class AcpModelConfig:  # pylint: disable=too-many-instance-attributes
    """Frozen snapshot of read-only ACP model configuration.

    Built once in ``AcpChatModel.model_post_init`` and threaded through
    every extracted free function so they never need a reference to the
    Pydantic model instance.
    """

    agent_config: AgentConfig | None
    permission_callback: PermissionCallback | None
    workspace_root: str | None
    command: list[str]
    # repr=False keeps injected auth tokens out of the frozen config's default
    # dataclass repr (env_vars redaction audit).
    env_vars: dict[str, str] = field(repr=False)
    mcp_servers: list[JsonObject]
    use_exec: bool
    provider: str | None
    runtime_authority: str | None
    acp_backend: str | None
    command_origin: str | None
    command_kind: str | None
    command_executable: str | None
    command_target: str | None
    auth_mode: str | None
    # Exact tool names (mcp__<server>__<tool>) auto-permitted for a headless run
    # so the CLI can invoke the bridged authoring tools without a local prompt.
    # Empty for human-in-loop runs, which keep the default prompt.
    # Defaulted (trailing) so existing config constructions need no change.
    allowed_tools: list[str] = field(default_factory=list)
    # Backend family discriminator selecting the ACP allowlist TRANSPORT only:
    # "claude" (Claude/Z.ai) serializes allowed_tools into the Claude-CLI-only
    # session/new _meta.claudeCode.options.allowedTools namespace; "kimi" omits
    # that namespace (Kimi has no claudeCode analogue) and enforces read-only at
    # the permission-RPC handler instead. Defaults to the incumbent claude family
    # so existing constructions are unchanged.
    acp_family: str = "claude"
    # Concrete model resolved by the profile layer. Claude-family ACP adapters
    # select it through the session's negotiated configuration surface.
    desired_model: str | None = None
    # Exact session-wide provider config values frozen at run admission, keyed
    # by the ACP adapter's advertised configuration option id.
    desired_config_options: dict[str, str] = field(default_factory=dict)

    @property
    def project_scope(self) -> RunProjectScope:
        """Return the project scope this run's tool calls are measured against.

        ``workspace_root`` is the active project the run was created with - the
        value every directory the lane touches is derived from - so it is also
        the authority a permission decision compares a call against.
        """
        return RunProjectScope(self.workspace_root)


@dataclass
# Session context mirrors the ACP lifecycle contract consumed by helpers.
class AcpSessionContext:  # pylint: disable=too-many-instance-attributes
    """Consolidated state for an active ACP session."""

    process: asyncio.subprocess.Process
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader
    response_futures: AcpResponseFutures
    chunk_queue: asyncio.Queue[ChatGenerationChunk | None]
    prompt_done: asyncio.Event
    prompt_id_ref: list[int]
    interrupt_exc: list[BaseException]
    session_id: str | None = None
    prompt_stop_reason: str | None = None
    prompt_usage: AcpUsageMetadata | None = None
    effects_may_have_occurred: bool = False
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    terminals: dict[str, asyncio.subprocess.Process] = field(default_factory=dict)
    terminal_outputs: dict[str, AcpTerminalOutput] = field(default_factory=dict)
    closing: bool = False
    stderr_event_count: int = 0
    # The child's own account of what went wrong, redacted at capture and bounded
    # to the shared tail length. A count of lines says a failure was noisy; the
    # lines themselves are what a failed startup or a refused login can be read
    # from, and this lane previously kept only the count.
    stderr_tail: deque[str] = field(
        default_factory=lambda: deque(maxlen=STDERR_TAIL_LINES)
    )
    auth_prompt_active: bool = False
    auth_url: str | None = None
    # Serialises all ctx.stdin.write() + drain() calls so concurrent background
    # RPC tasks cannot interleave writes and produce malformed JSON-RPC frames.
    stdin_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Session-scoped mutables (moved from AcpChatModel PrivateAttrs)
    tool_calls: dict[str, JsonObject] = field(default_factory=dict)
    agent_modes: JsonObject = field(default_factory=dict)
    native_command_catalogs: dict[str, AcpNativeCommandCatalog] = field(
        default_factory=dict
    )
    config_options: list[JsonObject] = field(default_factory=list)
    last_auth_url: str | None = None
    # Monotonic stamp of the last frame read from the subprocess. The turn loop
    # measures silence against this, so any protocol traffic - streamed content,
    # a session update, a server RPC, even a malformed line - proves liveness
    # and resets the deadline. Monotonic so a wall-clock jump cannot fake it.
    last_activity_monotonic: float = field(default_factory=time.monotonic)

    def mark_activity(self) -> None:
        """Record that the subprocess just produced a protocol frame."""
        self.last_activity_monotonic = time.monotonic()

    def retain_stderr_line(self, text: str) -> None:
        """Keep one redacted line of the child's standard error."""
        self.stderr_tail.append(redact_text(text))

    def rendered_stderr_tail(self) -> str:
        """Return the retained, redacted tail, or the empty string when silent."""
        return "\n".join(self.stderr_tail)

    def native_commands_for(self, session_id: str) -> AcpNativeCommandCatalog:
        """Return the command authority for one exact protocol session."""
        if (
            not session_id
            or session_id != session_id.strip()
            or not session_id.isprintable()
            or len(session_id) > MAX_ACP_SESSION_ID_LENGTH
        ):
            raise ValueError("ACP session id must be non-empty, trimmed text")
        catalog = self.native_command_catalogs.get(session_id)
        if catalog is None:
            if len(self.native_command_catalogs) >= MAX_SESSION_COMMAND_CATALOGS:
                raise ValueError("ACP session command catalog limit reached")
            catalog = AcpNativeCommandCatalog()
            self.native_command_catalogs[session_id] = catalog
        return catalog

    def seconds_since_activity(self) -> float:
        """Return seconds elapsed since the last observed protocol frame."""
        return time.monotonic() - self.last_activity_monotonic


@dataclass(frozen=True)
class InitializeResult:
    """Return value of ``initialize_session``."""

    agent_capabilities: JsonObject
    auth_methods: list[JsonObject]
    # Who answered the handshake, as the agent named itself. Optional in the
    # protocol and therefore possibly empty; carried rather than dropped because
    # it is the only statement of adapter identity a run ever receives.
    agent_info: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class SessionSetupResult:
    """Return value of ``setup_session``."""

    session_id: str
    agent_modes: JsonObject
    config_options: list[JsonObject]


type AcpRpcHandler = Callable[
    [AcpRpcId, JsonObject, AcpSessionContext, AcpModelConfig], Awaitable[JsonObject]
]
type RpcHandlerMap = Mapping[str, AcpRpcHandler]
