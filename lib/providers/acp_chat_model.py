r"""AcpChatModel: A LangChain BaseChatModel that wraps ACP-compatible CLIs.

Architecture:
  - Spawns CLI via `asyncio.create_subprocess_shell`
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

from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def _log_task_exception(task: asyncio.Task) -> None:
    """Log unhandled exceptions from fire-and-forget background RPC tasks."""
    if not task.cancelled() and (exc := task.exception()):
        logger.error("Background RPC task failed: %s", exc, exc_info=exc)


@dataclass
class _AcpSessionContext:
    """Consolidated state for an active ACP session."""

    process: asyncio.subprocess.Process
    response_futures: dict[int, asyncio.Future]
    chunk_queue: asyncio.Queue[ChatGenerationChunk | None]
    prompt_done: asyncio.Event
    prompt_id_ref: list[int]
    prompt_error_ref: list[dict]
    interrupt_exc: list[BaseException]
    background_tasks: set[asyncio.Task] | None = None

    def __post_init__(self) -> None:
        if self.background_tasks is None:
            self.background_tasks = set()


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
    permission_callback: object = Field(
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

    # --- Runtime state (private, not model fields) ---
    _process: asyncio.subprocess.Process | None = PrivateAttr(default=None)
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

        shell_command = " ".join(self.command)
        env = os.environ.copy()
        env.update(self.env_vars)
        env.pop("CLAUDECODE", None)  # Prevent nested session abort

        if "gemini" in self.command:
            refresh_gemini_token()

        process = await asyncio.create_subprocess_shell(
            shell_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self.cwd or str(Path.cwd()),
            limit=10 * 1024 * 1024,
        )

        ctx = _AcpSessionContext(
            process=process,
            response_futures={},
            chunk_queue=asyncio.Queue(),
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
                    await run_manager.on_llm_new_token(
                        chunk.message.content, chunk=chunk
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
                    await run_manager.on_llm_new_token(
                        chunk.message.content, chunk=chunk
                    )
                yield chunk

    async def _cleanup_session(
        self,
        ctx: _AcpSessionContext,
        stdout_task: asyncio.Task,
        stderr_task: asyncio.Task,
    ) -> None:
        """Terminate subprocess and clean up tasks."""
        if self._active_session_id and not ctx.prompt_done.is_set():
            with suppress(Exception):
                await self._send_notification(
                    "session/cancel", {"sessionId": self._active_session_id}, ctx
                )

        stdout_task.cancel()
        stderr_task.cancel()
        with suppress(OSError):
            ctx.process.terminate()

        transport = getattr(ctx.process, "_transport", None)
        if transport is not None:
            transport.close()

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

    async def _read_stderr_loop(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        while line := await process.stderr.readline():
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.debug("ACP STDERR: %s", text)

    async def _process_stdout_loop(self, ctx: _AcpSessionContext) -> None:
        try:
            while line := await ctx.process.stdout.readline():
                if not line.strip():
                    continue
                try:
                    agent_data = json.loads(line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.warning(
                        "ACP stdout: malformed line skipped: %s | raw=%r",
                        exc,
                        line[:200],
                    )
                    continue
                if not isinstance(agent_data, dict):
                    continue
                await self._dispatch_packet(agent_data, ctx)
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
        if rid in ctx.response_futures and not ctx.response_futures[rid].done():
            ctx.response_futures[rid].set_result(data)

        result = data.get("result", {})
        if isinstance(result, dict) and result.get("stopReason") == "end_turn":
            ctx.prompt_done.set()
        elif "error" in data and ctx.prompt_id_ref and rid == ctx.prompt_id_ref[0]:
            ctx.prompt_error_ref.append(data["error"])
            await ctx.chunk_queue.put(None)

    async def _handle_server_rpc(
        self, method: str, rpc_id: int | str, params: dict, ctx: _AcpSessionContext
    ) -> None:
        if method == "session/request_permission":
            resp = await self._on_request_permission(rpc_id, params, ctx)
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": "Not found"},
            }

        body = json.dumps(resp).encode("utf-8")
        ctx.process.stdin.write(body + b"\n")
        await ctx.process.stdin.drain()

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
                    "Permission callback raised; auto-granting first option"
                )
                option_id = options[0]["optionId"] if options else "allow_once"
        else:
            option_id = options[0]["optionId"] if options else "allow_once"

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"outcome": {"optionId": option_id, "outcome": "selected"}},
        }

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
        if tid in self._tool_calls:
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
        ctx.process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.process.stdin.drain()
        resp = await asyncio.wait_for(ctx.response_futures[rpc_id], timeout=60)
        if "error" in resp:
            raise RuntimeError(f"Init failed: {resp['error']}")
        res = resp.get("result", {})
        self._agent_capabilities = res.get("agentCapabilities", {})
        self._auth_methods = res.get("authMethods", [])

    async def _setup_session(self, ctx: _AcpSessionContext) -> None:
        """Create or load an ACP session."""
        working_dir = self.cwd or str(Path.cwd())
        method = "session/new"
        params: dict[str, object] = {"cwd": working_dir, "mcpServers": self.mcp_servers}
        if self.session_id and self._agent_capabilities.get("loadSession"):
            method = "session/load"
            params["sessionId"] = self.session_id

        rpc_id = AcpRequestId.SESSION_SETUP
        ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()
        req = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}
        ctx.process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.process.stdin.drain()
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
        ctx.process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.process.stdin.drain()
        ctx.prompt_id_ref.append(rpc_id)
        return ctx.response_futures[rpc_id]

    async def _send_notification(
        self, method: str, params: dict, ctx: _AcpSessionContext
    ) -> None:
        """Send an ACP notification."""
        req = {"jsonrpc": "2.0", "method": method, "params": params}
        ctx.process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await ctx.process.stdin.drain()

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
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await self._process.stdin.drain()
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
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await self._process.stdin.drain()
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
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await self._process.stdin.drain()
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
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await self._process.stdin.drain()
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
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await self._process.stdin.drain()
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
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(req).encode("utf-8") + b"\n")
        await self._process.stdin.drain()
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})
