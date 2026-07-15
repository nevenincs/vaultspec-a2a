"""ACP data carriers: config, context, and result types.

Extracted from ``_acp_session.py`` (D-04) to isolate pure data definitions
from auth logic and session lifecycle RPCs.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.outputs import ChatGenerationChunk

from ..team.team_config import AgentConfig

__all__: list[str] = []


PermissionCallback = Callable[[str, dict, list[dict[str, Any]]], Awaitable[str]]


@dataclass(frozen=True)
class _AcpModelConfig:
    """Frozen snapshot of read-only ACP model configuration.

    Built once in ``AcpChatModel.model_post_init`` and threaded through
    every extracted free function so they never need a reference to the
    Pydantic model instance.
    """

    agent_config: AgentConfig | None
    permission_callback: PermissionCallback | None
    workspace_root: str | None
    cwd: str | None
    command: list[str]
    # repr=False keeps injected auth tokens out of the frozen config's default
    # dataclass repr (multi-provider-execution env_vars redaction audit).
    env_vars: dict[str, str] = field(repr=False)
    session_id: str | None
    mcp_servers: list[dict[str, Any]]
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
    # so the CLI can invoke the bridged authoring tools without a local prompt
    # (ADR R4). Empty for human-in-loop runs, which keep the default prompt.
    # Defaulted (trailing) so existing config constructions need no change.
    allowed_tools: list[str] = field(default_factory=list)


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
    # Session-scoped mutables (moved from AcpChatModel PrivateAttrs)
    tool_calls: dict[str, Any] = field(default_factory=dict)
    agent_modes: dict[str, Any] = field(default_factory=dict)
    last_auth_url: str | None = None


@dataclass(frozen=True)
class InitializeResult:
    """Return value of ``initialize_session``."""

    agent_capabilities: dict[str, Any]
    auth_methods: list[dict[str, Any]]


@dataclass(frozen=True)
class SessionSetupResult:
    """Return value of ``setup_session``."""

    session_id: str
    agent_modes: dict[str, Any]
