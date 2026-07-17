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
import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, override

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field, PrivateAttr

from ..control.config import settings
from ..team.team_config import AgentConfig
from ..workspace.environment import resolve_env_vars
from ._acp_mcp import codex_mcp_server_specs
from ._codex_config_home import build_codex_config_home, cleanup_codex_config_home
from ._subprocess import kill_process_tree, spawn_acp_process

logger = logging.getLogger(__name__)

__all__ = ["CodexChatModel"]

# Client identity advertised in the ``initialize`` handshake. Mirrors the shape
# the codex-companion plugin's own client sends; ``name`` is what the app-server
# stamps into its user-agent.
_CLIENT_INFO: dict[str, str] = {
    "title": "Vaultspec A2A",
    "name": "vaultspec-a2a",
    "version": "0.1.0",
}
# Opt out of the reasoning-summary delta firehose but keep agent-message deltas
# for genuine token streaming (verified against codex-cli 0.144.4).
_CAPABILITIES: dict[str, Any] = {
    "experimentalApi": False,
    "optOutNotificationMethods": [
        "item/reasoning/summaryTextDelta",
        "item/reasoning/summaryPartAdded",
        "item/reasoning/textDelta",
    ],
}


def _messages_to_prompt(messages: list[BaseMessage]) -> str:
    """Flatten LangChain messages into a single Codex turn prompt.

    ``turn/start`` takes one ``UserInput`` array, not role-separated messages, so
    the conversation is rendered to labelled text blocks. System content leads as
    a preamble; human turns pass through verbatim; assistant/tool turns are kept
    with a role label so multi-turn context survives.
    """
    blocks: list[str] = []
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if not content.strip():
            continue
        if isinstance(msg, SystemMessage):
            blocks.append(f"# System\n{content}")
        elif isinstance(msg, HumanMessage):
            blocks.append(content)
        elif isinstance(msg, ToolMessage):
            blocks.append(f"# Tool result\n{content}")
        elif isinstance(msg, (AIMessage, AIMessageChunk)):
            blocks.append(f"# Assistant\n{content}")
        else:
            blocks.append(content)
    return "\n\n".join(blocks)


class _CodexProtocolError(RuntimeError):
    """A JSON-RPC error frame or an unexpected turn failure from the app-server."""


class _CodexAppServerClient:
    """Minimal JSON-RPC-over-stdio client for a spawned ``codex app-server``.

    Owns one subprocess and a reader task. Requests resolve their matching
    ``{id, result}`` frame; notifications land on :attr:`notifications` for the
    turn driver to consume. The process tree is reaped via
    :func:`kill_process_tree` on :meth:`aclose`.
    """

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("codex app-server failed to open stdio pipes")
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._metadata = metadata
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._closed = False
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Parse newline-delimited JSON frames, routing responses vs. notifications."""
        try:
            while True:
                line = await self._stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("codex app-server: unparseable JSONL line: %r", text)
                    continue
                self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
        finally:
            self._fail_pending(
                _CodexProtocolError("codex app-server connection closed")
            )

    def _dispatch(self, message: dict[str, Any]) -> None:
        msg_id = message.get("id")
        method = message.get("method")
        # Server-initiated request (has both id and method): we support none, so
        # answer with a JSON-RPC "method not found" to keep the stream unblocked.
        if msg_id is not None and method:
            self._send({"id": msg_id, "error": {"code": -32601, "message": method}})
            return
        if msg_id is not None:
            future = self._pending.pop(msg_id, None)
            if future is None or future.done():
                return
            error = message.get("error")
            if error is not None:
                future.set_exception(
                    _CodexProtocolError(
                        error.get("message", "codex app-server request failed")
                    )
                )
            else:
                future.set_result(message.get("result") or {})
            return
        if method:
            self.notifications.put_nowait(message)

    def _fail_pending(self, exc: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    def _send(self, message: dict[str, Any]) -> None:
        self._stdin.write((json.dumps(message) + "\n").encode("utf-8"))

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a request and await its matching response frame."""
        if self._closed:
            raise _CodexProtocolError("codex app-server client is closed")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[request_id] = future
        self._send({"id": request_id, "method": method, "params": params})
        await self._stdin.drain()
        return await future

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send a fire-and-forget notification frame."""
        if self._closed:
            return
        self._send({"method": method, "params": params})

    async def aclose(self) -> None:
        """Close stdin, reap the process tree, and cancel the reader."""
        if self._closed:
            return
        self._closed = True
        try:
            self._stdin.close()
        except Exception:
            logger.debug("codex app-server: stdin close failed", exc_info=True)
        await kill_process_tree(self._process, self._metadata)
        self._reader_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await self._reader_task


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
    cwd: str | None = None
    workspace_root: str | None = None
    codex_home: str | None = None
    harness_mcp_servers: list[str] = Field(default_factory=list)
    approval_policy: str = "never"
    sandbox: str = "read-only"
    timeout: float = 300.0
    agent_config: AgentConfig | None = Field(default=None, exclude=True)

    # Observability metadata (mirrors AcpChatModel's runtime fields).
    provider: str = "codex"
    runtime_authority: str | None = None
    command_origin: str | None = None
    command_kind: str | None = None
    command_executable: str | None = None
    command_target: str | None = None

    _agent_config: AgentConfig | None = PrivateAttr(default=None)

    def __init__(self, **kwargs: Any) -> None:
        agent_config = kwargs.get("agent_config")
        super().__init__(**kwargs)
        self._agent_config = agent_config

    @property
    def _llm_type(self) -> str:
        return "codex-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation is unsupported; use the async path."""
        raise NotImplementedError(
            "CodexChatModel only supports async via _astream/_agenerate"
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
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
        )
        return ChatResult(generations=[ChatGeneration(message=final)])

    def _build_env(self) -> dict[str, str]:
        """Return the subprocess env: scrubbed base plus an optional CODEX_HOME.

        Codex's persisted-session auth is file-based, so no secret is injected —
        only the non-secret ``CODEX_HOME`` override when configured.
        """
        workspace = Path(self.workspace_root or self.cwd or str(Path.cwd()))
        env = resolve_env_vars(workspace)
        codex_home = self.codex_home or settings.codex_home
        if codex_home and codex_home.strip():
            env["CODEX_HOME"] = codex_home
        return env

    @override
    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Drive one Codex turn, streaming assistant-message deltas."""
        prompt = _messages_to_prompt(messages)
        if not prompt.strip():
            raise ValueError("CodexChatModel received no prompt content")

        cwd = str(Path(self.workspace_root or self.cwd or str(Path.cwd())))
        env = self._build_env()
        # Per-run isolated CODEX_HOME: when harness servers are declared, emit a
        # worker-owned config.toml carrying exactly those read-only servers and
        # redirect CODEX_HOME to it, suppressing the operator's ambient
        # [mcp_servers.*] config. Auth (auth.json) is copied from the base home.
        # The home is built INSIDE the try so a spawn failure cannot leak the
        # copied credential; it is cleaned up in the finally regardless of where
        # the turn fails.
        codex_config_home: Path | None = None
        client: _CodexAppServerClient | None = None
        try:
            if self.harness_mcp_servers:
                specs = codex_mcp_server_specs(self.harness_mcp_servers)
                base = self.codex_home or settings.codex_home
                base_home = Path(base) if base else Path.home() / ".codex"
                codex_config_home = build_codex_config_home(specs, base_home)
                env["CODEX_HOME"] = str(codex_config_home)
            metadata = {
                "provider": self.provider,
                "command_executable": self.command_executable,
                "command_target": self.command_target,
            }

            process = await spawn_acp_process(
                self.command,
                env,
                cwd,
                use_exec=False,
                metadata=metadata,
            )
            client = _CodexAppServerClient(process, metadata=metadata)
            await asyncio.wait_for(
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
                        "cwd": cwd,
                        "model": self.model_name,
                        "approvalPolicy": self.approval_policy,
                        "sandbox": self.sandbox,
                        "ephemeral": True,
                        "experimentalRawEvents": False,
                    },
                ),
                timeout=self.timeout,
            )
            thread_id = thread["thread"]["id"]

            await asyncio.wait_for(
                client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [
                            {"type": "text", "text": prompt, "text_elements": []}
                        ],
                        "model": self.model_name,
                        "effort": self.effort,
                        "outputSchema": None,
                    },
                ),
                timeout=self.timeout,
            )

            async for chunk in self._consume_turn(client, thread_id):
                yield chunk
        finally:
            if client is not None:
                await client.aclose()
            cleanup_codex_config_home(codex_config_home)

    async def _consume_turn(
        self, client: _CodexAppServerClient, thread_id: str
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Yield delta chunks until the turn completes, raising on failure.

        Only frames scoped to *thread_id* are honored so a stray sub-thread
        notification never terminates the turn early.
        """
        while True:
            message = await asyncio.wait_for(
                client.notifications.get(), timeout=self.timeout
            )
            method = message.get("method")
            params = message.get("params") or {}

            if method == "item/agentMessage/delta":
                if params.get("threadId") not in (None, thread_id):
                    continue
                delta = params.get("delta")
                if isinstance(delta, str) and delta:
                    yield ChatGenerationChunk(message=AIMessageChunk(content=delta))
            elif method == "error":
                error = params.get("error") or {}
                raise _CodexProtocolError(
                    error.get("message", "codex app-server reported an error")
                )
            elif method == "turn/completed":
                if params.get("threadId") not in (None, thread_id):
                    continue
                turn = params.get("turn") or {}
                status = turn.get("status")
                if status != "completed":
                    raise _CodexProtocolError(
                        f"codex turn ended with status {status!r}"
                    )
                return
