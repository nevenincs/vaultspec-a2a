"""ACP data carriers: config, context, and result types.

Extracted from ``_acp_session.py`` to isolate pure data definitions
from auth logic and session lifecycle RPCs.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.outputs import ChatGenerationChunk

from ..team.team_config import AgentConfig
from ._json_contract import JsonObject

__all__: list[str] = []


type AcpRpcId = int | str
type AcpResponseFuture = asyncio.Future[JsonObject]
type AcpResponseFutures = dict[int, AcpResponseFuture]

PermissionCallback = Callable[[str, JsonObject, list[JsonObject]], Awaitable[str]]


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
    return Path(value)


@dataclass(frozen=True)
class AcpModelConfig:
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
    session_id: str | None
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


@dataclass
class AcpSessionContext:
    """Consolidated state for an active ACP session."""

    process: asyncio.subprocess.Process
    stdin: asyncio.StreamWriter
    stdout: asyncio.StreamReader
    response_futures: AcpResponseFutures
    chunk_queue: asyncio.Queue[ChatGenerationChunk | None]
    prompt_done: asyncio.Event
    prompt_id_ref: list[int]
    interrupt_exc: list[BaseException]
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    terminals: dict[str, asyncio.subprocess.Process] = field(default_factory=dict)
    stderr_event_count: int = 0
    auth_prompt_active: bool = False
    auth_url: str | None = None
    # Serialises all ctx.stdin.write() + drain() calls so concurrent background
    # RPC tasks cannot interleave writes and produce malformed JSON-RPC frames.
    stdin_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Session-scoped mutables (moved from AcpChatModel PrivateAttrs)
    tool_calls: dict[str, JsonObject] = field(default_factory=dict)
    agent_modes: JsonObject = field(default_factory=dict)
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

    def seconds_since_activity(self) -> float:
        """Return seconds elapsed since the last observed protocol frame."""
        return time.monotonic() - self.last_activity_monotonic


@dataclass(frozen=True)
class InitializeResult:
    """Return value of ``initialize_session``."""

    agent_capabilities: JsonObject
    auth_methods: list[JsonObject]


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
