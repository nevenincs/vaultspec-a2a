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
"""

import asyncio
import json
import logging
import os

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessageChunk,
    BaseMessage,
    ChatMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.language_models.chat_models import generate_from_stream
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field

from .gemini_auth import refresh_gemini_token


__all__ = ["AcpChatModel"]

logger = logging.getLogger(__name__)

# Type alias for permission callback.
# Receives (tool_name, tool_input, options) → selected optionId string.
# Ref: claude-agent-sdk CanUseTool pattern, adapted for raw ACP.
PermissionCallback = Callable[
    [str, dict[str, Any], list[dict[str, Any]]],
    Awaitable[str],
]


class AcpChatModel(BaseChatModel):
    """A custom LangChain ChatModel that wraps ACP-compatible CLI agents.

    Communicates with ACP CLI agents (like `claude-agent-acp` or
    `gemini --experimental-acp`) via JSON-RPC over a subprocess stdio pipe.
    """

    command: list[str] = Field(
        description="The command and arguments to launch the ACP agent."
    )
    env_vars: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject (e.g., OAuth tokens).",
    )
    session_id: str | None = Field(
        default=None,
        description=(
            "If set, resume an existing session via session/load instead of "
            "creating a new one via session/new. Ref: acp-python-sdk "
            "ClientSideConnection.load_session."
        ),
    )
    mcp_servers: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "MCP server configs to pass via session/new or session/load. "
            "Each dict should match the ACP McpServer schema "
            '(e.g., {"type": "stdio", "command": "mcp-server", "args": []}).'
        ),
    )
    cwd: str | None = Field(
        default=None,
        description=(
            "Working directory for the agent session. Defaults to os.getcwd()."
        ),
    )
    permission_callback: PermissionCallback | None = Field(
        default=None,
        description=(
            "Optional async callback for custom permission handling. "
            "If None, auto-grants first option (headless mode). "
            "Signature: async (tool_name, tool_input, options) -> optionId"
        ),
        exclude=True,  # Not serializable
    )

    # --- Runtime state (not model fields) ---
    _process: Any = None
    _active_session_id: str | None = None
    _send_rpc: Any = None
    _send_notification: Any = None
    _response_futures: dict[int, asyncio.Future] | None = None

    def model_post_init(self, __context: Any) -> None:
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
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Streams responses from the ACP subprocess."""
        prompt_blocks: list[dict[str, str]] = []
        for msg in messages:
            if isinstance(
                msg,
                (HumanMessage, SystemMessage, ChatMessage, AIMessageChunk),
            ):
                prompt_blocks.append({"type": "text", "text": str(msg.content)})

        # Toad uses get_os_matrix() to get a single command string,
        # then passes it to create_subprocess_shell. We join our argv list.
        shell_command = " ".join(self.command)

        env = os.environ.copy()
        env.update(self.env_vars)

        # Pre-flight: refresh Gemini OAuth token before spawning the subprocess.
        # gemini-cli v0.18.0 regression (#13853): expired token causes silent hang
        # in headless/piped mode because the CLI tries a browser auth flow on stdin.
        if "gemini" in self.command:
            refresh_gemini_token()

        pipe = asyncio.subprocess.PIPE
        process = await asyncio.create_subprocess_shell(
            shell_command,
            stdin=pipe,
            stdout=pipe,
            stderr=pipe,
            env=env,
            cwd=str(Path.cwd()),
            limit=10 * 1024 * 1024,  # Toad line 490: 10MB buffer
        )

        assert process.stdin is not None
        assert process.stdout is not None

        request_id = 0
        response_futures: dict[int, asyncio.Future] = {}
        _active_session_id: str | None = None

        def send_rpc(method: str, params: dict) -> int:
            """Send a JSON-RPC request on stdin (Toad line 196)."""
            nonlocal request_id
            request_id += 1
            req = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
            body = json.dumps(req).encode("utf-8")
            process.stdin.write(b"%s\n" % body)  # Toad: stdin.write(b"%s\n" % body)
            response_futures[request_id] = asyncio.get_running_loop().create_future()
            return request_id

        def send_notification(method: str, params: dict) -> None:
            """Send a JSON-RPC notification (no id, no response expected).

            Used for session/cancel. Ref: acp-python-sdk cancel() method.
            """
            notif = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
            body = json.dumps(notif).encode("utf-8")
            process.stdin.write(b"%s\n" % body)

        async def read_stderr() -> None:
            assert process.stderr is not None
            while _ := await process.stderr.readline():
                pass  # Silently consume stderr; errors surface via JSON-RPC

        stderr_task = asyncio.create_task(read_stderr())

        # We need to yield chunks from _astream, so we use an asyncio.Queue
        # to bridge between the stdout reader task and the generator.
        chunk_queue: asyncio.Queue[ChatGenerationChunk | None] = asyncio.Queue()
        prompt_done = asyncio.Event()

        # Mutable refs so process_stdout (defined before prompt_id is assigned)
        # can see the prompt request id and surface errors back to the main loop.
        prompt_id_ref: list[int] = []
        prompt_error_ref: list[dict] = []

        async def process_stdout() -> None:
            """Read stdout and dispatch responses/notifications/RPCs."""
            try:
                while line := await process.stdout.readline():  # Toad line 513
                    if not line.strip():
                        continue

                    try:
                        line_str = line.decode("utf-8")
                    except Exception:
                        continue

                    try:
                        agent_data: dict = json.loads(line_str)
                    except Exception:
                        continue

                    if not isinstance(agent_data, dict):
                        continue

                    # (A) Response to a client request (Toad line 534)
                    if "result" in agent_data or "error" in agent_data:
                        rid = agent_data.get("id")
                        if rid in response_futures and not response_futures[rid].done():
                            response_futures[rid].set_result(agent_data)

                        # Check if this is the session/prompt response with stopReason
                        result = agent_data.get("result", {})
                        if isinstance(result, dict) and "stopReason" in result:
                            prompt_done.set()
                        elif (
                            "error" in agent_data
                            and prompt_id_ref
                            and rid == prompt_id_ref[0]
                        ):
                            # session/prompt returned an error (e.g. quota exhausted).
                            # The agent process may stay alive, so the EOF sentinel
                            # would never arrive. Surface it immediately.
                            prompt_error_ref.append(agent_data["error"])
                            await chunk_queue.put(None)
                        continue

                    method = agent_data.get("method", "")
                    rpc_id = agent_data.get("id")
                    params = agent_data.get("params", {})

                    # (B) Server-to-client RPC — agent is calling us, expects response
                    if rpc_id is not None and method:
                        await _handle_server_rpc(method, rpc_id, params)
                        continue

                    # (C) Notification — no id, no response needed
                    if method == "session/update":
                        await _handle_session_update(params)
            finally:
                # Subprocess exited or reader cancelled. Avoid hanging waiters.
                for fut in response_futures.values():
                    if not fut.done():
                        fut.set_exception(
                            RuntimeError("Subprocess stdout closed before response")
                        )

            # EOF — subprocess exited. If prompt_done was never set the streaming
            # loop would poll forever. Inject a None sentinel to break it.
            if not prompt_done.is_set():
                await chunk_queue.put(None)

        async def _handle_server_rpc(
            method: str, rpc_id: int | str, params: dict
        ) -> None:
            """Handle an inbound RPC from the agent that requires a response.

            Ref: Toad agent.py lines 302-468, acp-python-sdk client/router.py
            """
            if method == "session/request_permission":
                options = params.get("options", [])
                tool_call_info = params.get("toolCall", {})
                tool_name = tool_call_info.get("title", "unknown")
                tool_input = tool_call_info.get("input", {})

                if self.permission_callback is not None:
                    # Custom permission handling (e.g., LangGraph interrupt)
                    try:
                        option_id = await self.permission_callback(
                            tool_name, tool_input, options
                        )
                    except Exception:
                        logger.exception("Permission callback failed, auto-granting")
                        option_id = options[0]["optionId"] if options else "allow_once"
                else:
                    # Headless orchestrator: auto-grant the first option.
                    # ACP PermissionOption uses "optionId" (camelCase)
                    # Ref: toad/acp/protocol.py:338, acp-python-sdk/schema.py
                    option_id = options[0]["optionId"] if options else "allow_once"

                response = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "outcome": {
                            "optionId": option_id,
                            "outcome": "selected",
                        }
                    },
                }
            else:
                # Unknown server RPC — return method_not_found per JSON-RPC spec
                logger.debug("Unknown server RPC: %s", method)
                response = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}",
                    },
                }

            body = json.dumps(response).encode("utf-8")
            process.stdin.write(b"%s\n" % body)
            await process.stdin.drain()

        async def _handle_session_update(params: dict) -> None:
            """Handle session/update notification subtypes.

            Ref: Toad agent.py lines 215-300
            """
            update = params.get("update", {})
            update_type = update.get("sessionUpdate")

            # Text content chunks → AIMessageChunk
            if update_type in ("agent_message_chunk", "agent_thought_chunk"):
                content = update.get("content", {})
                text = content.get("text", "")
                if text:
                    chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
                    await chunk_queue.put(chunk)

            # Tool call start → track + emit ToolCallChunk (Toad line 253)
            elif update_type == "tool_call":
                tool_call_id = update.get("toolCallId", "")
                # Store in tracking dict (Toad line 257)
                self._tool_calls[tool_call_id] = dict(update)
                title = update.get("title", "")
                tool_input = update.get("input")
                args_str = json.dumps(tool_input) if tool_input else ""
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "id": tool_call_id,
                                "name": title,
                                "args": args_str,
                                "index": 0,
                            }
                        ],
                    )
                )
                await chunk_queue.put(chunk)

            # Tool call update — merge into tracked tool call (Toad line 263)
            elif update_type == "tool_call_update":
                tool_call_id = update.get("toolCallId", "")
                if tool_call_id in self._tool_calls:
                    # Merge non-None values into existing entry
                    for key, value in update.items():
                        if value is not None:
                            self._tool_calls[tool_call_id][key] = value
                else:
                    # Orphan update — agent sent update without tool_call
                    # (Toad line 277: "rolls eyes")
                    synthetic: dict[str, Any] = {
                        "sessionUpdate": "tool_call",
                        "toolCallId": tool_call_id,
                        "title": "Tool call",
                    }
                    for key, value in update.items():
                        if value is not None:
                            synthetic[key] = value
                    self._tool_calls[tool_call_id] = synthetic

                # Emit status for LangGraph observability
                status = update.get("status", "")
                if status:
                    logger.debug("Tool %s status: %s", tool_call_id, status)

            # Plan steps (Toad line 260: uses "entries")
            elif update_type == "plan":
                entries = update.get("entries", [])
                logger.info("Agent plan: %d entries", len(entries))

            # Available commands (Toad line 291: "availableCommands")
            elif update_type == "available_commands_update":
                commands = update.get("availableCommands", [])
                logger.debug("Available commands updated: %d commands", len(commands))

            # Mode change (Toad line 296: direct "currentModeId")
            elif update_type == "current_mode_update":
                mode_id = update.get("currentModeId", "unknown")
                self._agent_modes["currentModeId"] = mode_id
                logger.info("Agent mode changed to: %s", mode_id)

            # User message echo — silently ignore
            elif update_type == "user_message_chunk":
                pass

            # Rate limit event — log as warning
            elif update_type == "rate_limit_event":
                logger.warning("Rate limit event: %s", json.dumps(update))

        stdout_task = asyncio.create_task(process_stdout())

        try:
            # Step 1: Initialize (Toad acp_initialize, line 635)
            working_dir = self.cwd or str(Path.cwd())
            init_id = send_rpc(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                    "clientInfo": {"name": "vaultspec", "version": "1.0.0"},
                },
            )
            await process.stdin.drain()
            init_resp = await asyncio.wait_for(response_futures[init_id], timeout=60)

            # Store agent capabilities (Toad line 658)
            # Critical: Gemini/Claude advertise different capabilities
            if "error" in init_resp:
                raise RuntimeError(f"ACP initialize failed: {init_resp['error']}")
            init_result = init_resp.get("result", {})
            if agent_caps := init_result.get("agentCapabilities"):
                self._agent_capabilities = agent_caps
            if auth_methods := init_result.get("authMethods"):
                self._auth_methods = auth_methods
            logger.info(
                "Agent initialized: caps=%s, auth=%s",
                self._agent_capabilities,
                self._auth_methods,
            )

            # Step 2: Session setup — load existing or create new
            # Ref: acp-python-sdk ClientSideConnection.load_session / new_session
            if self.session_id:
                # Gate on loadSession capability (Toad line 593)
                if not self._agent_capabilities.get("loadSession", False):
                    logger.warning(
                        "Agent does not advertise loadSession capability; "
                        "falling back to session/new"
                    )
                    session_rpc_id = send_rpc(
                        "session/new",
                        {"cwd": working_dir, "mcpServers": self.mcp_servers},
                    )
                else:
                    # Resume existing session
                    session_rpc_id = send_rpc(
                        "session/load",
                        {
                            "cwd": working_dir,
                            "sessionId": self.session_id,
                            "mcpServers": self.mcp_servers,
                        },
                    )
            else:
                # Create new session
                session_rpc_id = send_rpc(
                    "session/new",
                    {
                        "cwd": working_dir,
                        "mcpServers": self.mcp_servers,
                    },
                )
            await process.stdin.drain()
            session_resp = await asyncio.wait_for(
                response_futures[session_rpc_id], timeout=60
            )
            if "error" in session_resp:
                raise RuntimeError(f"ACP session setup failed: {session_resp['error']}")
            _active_session_id = session_resp["result"]["sessionId"]

            # Extract modes from session response (Toad lines 689-698)
            session_result = session_resp.get("result", {})
            if modes := session_result.get("modes"):
                self._agent_modes = {
                    "currentModeId": modes.get("currentModeId"),
                    "availableModes": modes.get("availableModes", []),
                }
                logger.info(
                    "Agent modes: current=%s, available=%d",
                    self._agent_modes["currentModeId"],
                    len(self._agent_modes["availableModes"]),
                )

            # Reset tool call tracking
            self._tool_calls = {}

            # Expose runtime state to public session methods
            self._process = process
            self._send_rpc = send_rpc
            self._send_notification = send_notification
            self._response_futures = response_futures
            self._active_session_id = _active_session_id

            # Step 3: Send Prompt (Toad acp_session_prompt, line 728)
            prompt_id = send_rpc(
                "session/prompt",
                {
                    "sessionId": _active_session_id,
                    "prompt": prompt_blocks,
                },
            )
            await process.stdin.drain()

            prompt_future = response_futures[prompt_id]
            # Allow process_stdout to detect prompt errors
            prompt_id_ref.append(prompt_id)

            while not prompt_done.is_set():
                try:
                    chunk = await asyncio.wait_for(chunk_queue.get(), timeout=0.1)
                    if chunk is None:
                        # Sentinel: process exited before end_turn
                        # Maybe the prompt future has an error?
                        if prompt_future.done():
                            resp = prompt_future.result()
                            if "error" in resp:
                                err_msg = f"ACP prompt failed: {resp['error']}"
                                raise RuntimeError(err_msg)
                        raise RuntimeError(
                            "ACP subprocess exited before end_turn"
                        )
                    if run_manager:
                        await run_manager.on_llm_new_token(
                            chunk.message.content, chunk=chunk
                        )
                    yield chunk
                except TimeoutError:
                    if prompt_future.done():
                        resp = prompt_future.result()
                        if "error" in resp:
                            msg = f"ACP prompt failed: {resp['error']}"
                            raise RuntimeError(msg) from None
                    continue

            # Drain any remaining chunks in the queue
            while not chunk_queue.empty():
                chunk = chunk_queue.get_nowait()
                if chunk is not None:
                    if run_manager:
                        await run_manager.on_llm_new_token(
                            chunk.message.content, chunk=chunk
                        )
                    yield chunk

        finally:
            # Send session/cancel as a notification (no id, no response expected).
            # Ref: Toad api.py line 38 — @API.notification(name="session/cancel")
            if _active_session_id and not prompt_done.is_set():
                try:
                    send_notification(
                        "session/cancel",
                        {"sessionId": _active_session_id},
                    )
                    await process.stdin.drain()
                except Exception:
                    pass  # Best-effort; process may already be dead

            # Cancel reader tasks first so they release the streams
            stdout_task.cancel()
            stderr_task.cancel()

            with suppress(OSError):
                process.terminate()

            # Close the subprocess transport directly to prevent the
            # Windows ProactorEventLoop __del__ ValueError. The warning
            # fires when GC finds unclosed pipe transports.
            if process._transport is not None:
                process._transport.close()

            # Clear runtime state
            self._process = None
            self._send_rpc = None
            self._send_notification = None
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
        """Collect _astream chunks into a ChatResult for ainvoke/agenerate callers."""
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
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generate not supported; orchestration is fully async."""
        raise NotImplementedError(
            "AcpChatModel only supports async generation. Use ainvoke or astream."
        )

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """Get the identifying parameters."""
        return {"command": self.command}

    # ------------------------------------------------------------------
    # Outbound session management methods
    # Ref: acp-python-sdk/src/acp/client/connection.py
    # ------------------------------------------------------------------

    def _require_session(self) -> tuple[Any, str]:
        """Validate that a subprocess session is active."""
        if self._send_rpc is None or self._active_session_id is None:
            raise RuntimeError(
                "No active session. These methods require a running "
                "_astream context (persistent sessions not yet implemented)."
            )
        return self._send_rpc, self._active_session_id

    async def fork_session(self) -> str:
        """Fork the current session into a new independent session.

        Returns the new session_id. The original session remains unchanged.
        Ref: acp-python-sdk ClientSideConnection.fork_session
        """
        send_rpc, session_id = self._require_session()
        rpc_id = send_rpc(
            "session/fork",
            {"sessionId": session_id},
        )
        assert self._process is not None
        await self._process.stdin.drain()
        assert self._response_futures is not None
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=60)
        return resp["result"]["sessionId"]

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all available sessions.

        Ref: acp-python-sdk ClientSideConnection (session/list)
        """
        send_rpc, _ = self._require_session()
        rpc_id = send_rpc("session/list", {})
        assert self._process is not None
        await self._process.stdin.drain()
        assert self._response_futures is not None
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp["result"].get("sessions", [])

    async def set_mode(self, mode_id: str) -> dict[str, Any]:
        """Switch the agent's operating mode.

        Ref: acp-python-sdk (session/set_mode)
        """
        send_rpc, session_id = self._require_session()
        rpc_id = send_rpc(
            "session/set_mode",
            {"sessionId": session_id, "modeId": mode_id},
        )
        assert self._process is not None
        await self._process.stdin.drain()
        assert self._response_futures is not None
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})

    async def set_model(self, model_id: str) -> dict[str, Any]:
        """Switch the LLM model mid-session.

        Ref: acp-python-sdk (session/set_model)
        """
        send_rpc, session_id = self._require_session()
        rpc_id = send_rpc(
            "session/set_model",
            {"sessionId": session_id, "modelId": model_id},
        )
        assert self._process is not None
        await self._process.stdin.drain()
        assert self._response_futures is not None
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})

    async def set_config_option(self, key: str, value: Any) -> dict[str, Any]:
        """Set a session-level configuration option.

        Ref: acp-python-sdk (session/set_config_option)
        """
        send_rpc, session_id = self._require_session()
        rpc_id = send_rpc(
            "session/set_config_option",
            {"sessionId": session_id, "key": key, "value": value},
        )
        assert self._process is not None
        await self._process.stdin.drain()
        assert self._response_futures is not None
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})

    async def authenticate(self, token: str) -> dict[str, Any]:
        """Respond to an authentication challenge from the agent.

        Ref: acp-python-sdk (authenticate)
        """
        send_rpc, _ = self._require_session()
        rpc_id = send_rpc("authenticate", {"token": token})
        assert self._process is not None
        await self._process.stdin.drain()
        assert self._response_futures is not None
        resp = await asyncio.wait_for(self._response_futures[rpc_id], timeout=15)
        return resp.get("result", {})
