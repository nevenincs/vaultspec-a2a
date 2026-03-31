"""ACP JSON-RPC protocol dispatch loop.

Extracted from ``acp_chat_model.py`` (ADR D-05).  Contains the stdout
readline loop, packet dispatcher, client response handler, server RPC
handler, and session update notification handler.

The handler map is passed as a parameter from the caller to avoid
circular imports — this module does NOT import from ``_acp_rpc_handlers``.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk

from ._acp_auth import _log_task_exception, runtime_log_extra
from ._acp_types import _AcpModelConfig, _AcpSessionContext

__all__: list[str] = []

logger = logging.getLogger(__name__)

# Map RPC method -> AgentCapabilities attribute name.
# Used for defense-in-depth capability checks at dispatch time
# (in addition to the clientCapabilities declared at initialize time).
_CAPABILITY_REQUIREMENTS: dict[str, str] = {
    "fs/read_text_file": "filesystem_read",
    "fs/write_text_file": "filesystem_write",
    "terminal/create": "terminal",
    "terminal/kill": "terminal",
    "terminal/output": "terminal",
    "terminal/wait_for_exit": "terminal",
    "terminal/release": "terminal",
    # M13: session/request_permission is intentionally excluded — it is a
    # server->client RPC initiated by the agent, not a capability-gated
    # client->server request.  No clientCapability flag governs it.
}

# Type alias for the RPC handler map passed by the caller.
RpcHandlerMap = dict[
    str,
    Callable[
        [int | str, dict, _AcpSessionContext, _AcpModelConfig],
        Awaitable[dict[str, object]],
    ],
]


async def process_stdout_loop(
    ctx: _AcpSessionContext,
    config: _AcpModelConfig,
    rpc_handler_map: RpcHandlerMap,
) -> None:
    """Read JSON-RPC messages from stdout and dispatch them."""
    try:
        while line := await ctx.stdout.readline():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning(
                    "ACP stdout: malformed line skipped: %s | raw=%r",
                    exc,
                    line[:200],
                    extra=runtime_log_extra(
                        config,
                        process=ctx.process,
                        stderr_event_count=ctx.stderr_event_count,
                    ),
                )
                continue
            # Handle batch JSON-RPC (array of messages)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        await dispatch_packet(item, ctx, config, rpc_handler_map)
            elif isinstance(parsed, dict):
                await dispatch_packet(parsed, ctx, config, rpc_handler_map)
    finally:
        for fut in ctx.response_futures.values():
            if not fut.done():
                fut.set_exception(RuntimeError("Subprocess closed"))
        if not ctx.prompt_done.is_set():
            try:
                ctx.chunk_queue.put_nowait(None)
            except asyncio.QueueFull:
                logger.warning(
                    "Chunk queue full — dropping EOF sentinel; consumer may hang"
                )


async def dispatch_packet(
    data: dict,
    ctx: _AcpSessionContext,
    config: _AcpModelConfig,
    rpc_handler_map: RpcHandlerMap,
) -> None:
    """Route a single JSON-RPC message to the appropriate handler."""
    if "result" in data or "error" in data:
        await handle_client_response(data, ctx)
        return

    method = data.get("method", "")
    rpc_id = data.get("id")
    params = data.get("params", {})

    if rpc_id is not None and method:
        t = asyncio.create_task(
            handle_server_rpc(method, rpc_id, params, ctx, config, rpc_handler_map)
        )
        ctx.background_tasks.add(t)
        t.add_done_callback(ctx.background_tasks.discard)
        t.add_done_callback(_log_task_exception)
        return

    if method == "session/update":
        await handle_session_update(params, ctx)


async def handle_client_response(
    data: dict,
    ctx: _AcpSessionContext,
) -> None:
    """Resolve response futures, detect end_turn, enqueue error sentinels."""
    rid = data.get("id")
    if rid in ctx.response_futures:
        fut = ctx.response_futures[rid]
        if not fut.done():
            try:
                fut.set_result(data)
            except asyncio.InvalidStateError:
                # wait_for() already cancelled the future (timeout fired between
                # the .done() check and set_result()). Discard the late response.
                logger.debug(
                    "Response for rpc_id=%r arrived after timeout; discarding", rid
                )

    result = data.get("result", {})
    if isinstance(result, dict) and result.get("stopReason") == "end_turn":
        ctx.prompt_done.set()
    elif "error" in data and ctx.prompt_id_ref and rid == ctx.prompt_id_ref[0]:
        try:
            ctx.chunk_queue.put_nowait(None)
        except asyncio.QueueFull:
            logger.warning("Chunk queue full — dropping error sentinel")


async def handle_server_rpc(
    method: str,
    rpc_id: int | str,
    params: dict,
    ctx: _AcpSessionContext,
    config: _AcpModelConfig,
    rpc_handler_map: RpcHandlerMap,
) -> None:
    """Capability check + dispatch to handler function via the map."""
    # Defense-in-depth capability check at dispatch time.
    # The ACP subprocess was told our capabilities at initialize time, but
    # this guard ensures a misbehaving or confused subprocess cannot invoke
    # methods the agent config does not permit.
    cap_attr = _CAPABILITY_REQUIREMENTS.get(method)
    if cap_attr is not None:
        allowed = (
            getattr(config.agent_config.capabilities, cap_attr, False)
            if config.agent_config is not None
            else False
        )
        if not allowed:
            resp: dict[str, object] = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": -32601,
                    "message": f"Capability not enabled: {method}",
                },
            }
            body = json.dumps(resp).encode("utf-8")
            async with ctx.stdin_lock:
                ctx.stdin.write(body + b"\n")
                await ctx.stdin.drain()
            return

    handler = rpc_handler_map.get(method)
    if handler is not None:
        resp = await handler(rpc_id, params, ctx, config)
    else:
        resp = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    body = json.dumps(resp).encode("utf-8")
    async with ctx.stdin_lock:
        ctx.stdin.write(body + b"\n")
        await ctx.stdin.drain()


async def handle_session_update(
    params: dict,
    ctx: _AcpSessionContext,
) -> None:
    """Dispatch all session update notification types."""
    update = params.get("update", {})
    u_type = update.get("sessionUpdate")

    if u_type in ("agent_message_chunk", "agent_thought_chunk"):
        text = update.get("content", {}).get("text", "")
        if text:
            try:
                ctx.chunk_queue.put_nowait(
                    ChatGenerationChunk(message=AIMessageChunk(content=text))
                )
            except asyncio.QueueFull:
                logger.warning("Chunk queue full — dropping chunk to prevent deadlock")
    elif u_type == "tool_call_chunk":
        # M20: handle incremental tool call argument streaming.
        # ACP agents stream partial JSON args via tool_call_chunk before the
        # final tool_call event.  Forwarded as a streaming ToolCallChunk so
        # LangGraph can accumulate args progressively.
        tid = update.get("toolCallId", "")
        args_delta = update.get("inputDelta", "")
        if tid and args_delta:
            try:
                ctx.chunk_queue.put_nowait(
                    ChatGenerationChunk(
                        message=AIMessageChunk(
                            content="",
                            tool_call_chunks=[
                                {
                                    "id": tid,
                                    "name": "",
                                    "args": args_delta,
                                    "index": 0,
                                }
                            ],
                        )
                    )
                )
            except asyncio.QueueFull:
                logger.warning(
                    "Chunk queue full — dropping tool_call_chunk to prevent deadlock"
                )
    elif u_type == "tool_call":
        await on_tool_call(update, ctx)
    elif u_type == "tool_call_update":
        await on_tool_call_update(update, ctx)
    elif u_type == "current_mode_update":
        ctx.agent_modes["currentModeId"] = update.get("currentModeId")
    elif u_type == "available_commands_update":
        ctx.agent_modes["availableCommands"] = update.get("commands", [])
    elif u_type == "plan":
        # Plan updates are metadata; log receipt and let graph-level plan
        # handling in the supervisor/aggregator layer process them.
        plan_entries = update.get("entries", [])
        logger.debug("ACP plan update: %d entries received", len(plan_entries))


async def on_tool_call(update: dict, ctx: _AcpSessionContext) -> None:
    """Record a tool_call and enqueue a ToolCallChunk."""
    tid = update.get("toolCallId", "")
    ctx.tool_calls[tid] = dict(update)
    chunk = ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "id": tid,
                    "name": update.get("title", ""),
                    "args": json.dumps(update.get("rawInput")),
                    "index": 0,
                }
            ],
        )
    )
    try:
        ctx.chunk_queue.put_nowait(chunk)
    except asyncio.QueueFull:
        logger.warning(
            "Chunk queue full — dropping tool_call chunk to prevent deadlock"
        )


async def on_tool_call_update(update: dict, ctx: _AcpSessionContext) -> None:
    """Update an existing tool_call record and enqueue if new."""
    tid = update.get("toolCallId", "")
    if tid not in ctx.tool_calls:
        # Unknown toolCallId: synthesise a tool_call entry so the update
        # is not silently lost (TOAD reference pattern for late/out-of-order
        # tool_call_update notifications).
        ctx.tool_calls[tid] = {
            "toolCallId": tid,
            "title": update.get("title", tid),
        }
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "id": tid,
                        "name": update.get("title", tid),
                        "args": "{}",
                        "index": 0,
                    }
                ],
            )
        )
        try:
            ctx.chunk_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            logger.warning(
                "Chunk queue full — dropping tool_call_update chunk to prevent deadlock"
            )
    for k, v in update.items():
        if v is not None:
            ctx.tool_calls[tid][k] = v
    if status := update.get("status"):
        logger.debug("Tool %s status: %s", tid, status)
