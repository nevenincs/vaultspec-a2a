"""ACP JSON-RPC protocol dispatch loop.

Extracted from ``acp_chat_model.py``.  Contains the stdout
readline loop, packet dispatcher, client response handler, server RPC
handler, and session update notification handler.

The handler map is passed as a parameter from the caller to avoid
circular imports — this module does NOT import from ``_acp_rpc_handlers``.
"""

import asyncio
import json
import logging
from dataclasses import dataclass

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from pydantic import TypeAdapter, ValidationError

from ._acp_auth import runtime_log_extra
from ._acp_types import (
    MAX_ACP_SESSION_ID_LENGTH,
    MAX_NATIVE_COMMAND_NAME_LENGTH,
    AcpModelConfig,
    AcpRpcId,
    AcpSessionContext,
    NativeCommandAvailability,
    NativeCommandDisposition,
    RpcHandlerMap,
)
from ._json_contract import JsonObject, JsonValue, lenient_json_object
from .acp_exceptions import AcpErrorCode, AcpPromptError

__all__: list[str] = []

logger = logging.getLogger(__name__)
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_TERMINAL_STOP_REASONS = frozenset(
    {"end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"}
)

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

_EFFECTFUL_SERVER_METHODS = frozenset(
    {"fs/write_text_file", "terminal/create", "terminal/kill"}
)
_MAX_COMMAND_DESCRIPTION_LENGTH = 1024
_MAX_COMMAND_INPUT_HINT_LENGTH = 512
_MAX_AVAILABLE_COMMANDS = 256


@dataclass(frozen=True, slots=True)
class ServerRpcRequest:
    method: str
    rpc_id: AcpRpcId
    params: JsonObject


def _json_string(value: JsonValue | None, *, default: str = "") -> str:
    """Return one protocol string, falling back for malformed fields."""
    return value if isinstance(value, str) else default


def _rpc_id(value: JsonValue | None) -> AcpRpcId | None:
    """Return a JSON-RPC request identifier, excluding JSON booleans."""
    if isinstance(value, str) or (
        isinstance(value, int) and not isinstance(value, bool)
    ):
        return value
    return None


def _bounded_command_text(value: JsonValue | None, *, field: str, maximum: int) -> str:
    """Return one required bounded command field or raise on a bad snapshot."""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.isprintable()
        or len(value) > maximum
    ):
        raise ValueError(f"available command {field} is invalid")
    return value


def _bounded_command_display_text(
    value: JsonValue | None, *, field: str, maximum: int
) -> str:
    """Return one protocol display string without applying identity rules."""
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"available command {field} is invalid")
    return value


def _native_command_snapshot(
    update: JsonObject,
) -> dict[str, NativeCommandAvailability]:
    """Validate one ACP command advertisement as an all-or-nothing snapshot."""
    raw_commands = update.get("availableCommands")
    if not isinstance(raw_commands, list):
        raise ValueError("availableCommands must be an array")
    if len(raw_commands) > _MAX_AVAILABLE_COMMANDS:
        raise ValueError("availableCommands exceeds the session limit")

    snapshot: dict[str, NativeCommandAvailability] = {}
    for raw_command in raw_commands:
        if not isinstance(raw_command, dict):
            raise ValueError("availableCommands entries must be objects")
        command = lenient_json_object(raw_command)
        name = _bounded_command_text(
            command.get("name"), field="name", maximum=MAX_NATIVE_COMMAND_NAME_LENGTH
        )
        if name in snapshot:
            raise ValueError("availableCommands contains a duplicate command name")
        description = _bounded_command_display_text(
            command.get("description"),
            field="description",
            maximum=_MAX_COMMAND_DESCRIPTION_LENGTH,
        )
        raw_input = command.get("input")
        input_hint: str | None = None
        if raw_input is not None:
            if not isinstance(raw_input, dict):
                raise ValueError("available command input must be an object")
            input_hint = _bounded_command_display_text(
                lenient_json_object(raw_input).get("hint"),
                field="input hint",
                maximum=_MAX_COMMAND_INPUT_HINT_LENGTH,
            )
        snapshot[name] = NativeCommandAvailability(
            name=name,
            disposition=NativeCommandDisposition.SUPPORTED,
            description=description,
            input_hint=input_hint,
        )
    return snapshot


def _log_task_exception(task: asyncio.Task[None]) -> None:
    """Log one unhandled background server-RPC task failure."""
    if not task.cancelled() and (exc := task.exception()):
        logger.error("ACP background RPC task failed: %s", exc, exc_info=exc)


async def process_stdout_loop(
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    rpc_handler_map: RpcHandlerMap,
) -> None:
    """Read JSON-RPC messages from stdout and dispatch them."""
    try:
        while line := await ctx.stdout.readline():
            # Stamp before parsing: a frame arriving at all proves the agent is
            # alive and working, which is exactly what the turn deadline asks.
            ctx.mark_activity()
            if not line.strip():
                continue
            await _dispatch_stdout_line(line, ctx, config, rpc_handler_map)
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


async def _dispatch_stdout_line(
    line: bytes,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    rpc_handler_map: RpcHandlerMap,
) -> None:
    try:
        parsed = _JSON_VALUE.validate_json(line)
    except (ValidationError, UnicodeDecodeError) as exc:
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
        return
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                await dispatch_packet(item, ctx, config, rpc_handler_map)
    elif isinstance(parsed, dict):
        await dispatch_packet(parsed, ctx, config, rpc_handler_map)


async def dispatch_packet(
    data: JsonObject,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    rpc_handler_map: RpcHandlerMap,
) -> None:
    """Route a single JSON-RPC message to the appropriate handler."""
    if "result" in data or "error" in data:
        await handle_client_response(data, ctx)
        return

    method = _json_string(data.get("method"))
    rpc_id = _rpc_id(data.get("id"))
    params = lenient_json_object(data.get("params"))

    if rpc_id is not None and method:
        t = asyncio.create_task(
            handle_server_rpc(
                ServerRpcRequest(method, rpc_id, params), ctx, config, rpc_handler_map
            )
        )
        ctx.background_tasks.add(t)
        t.add_done_callback(ctx.background_tasks.discard)
        t.add_done_callback(_log_task_exception)
        return

    if method == "session/update":
        await handle_session_update(params, ctx)


async def handle_client_response(
    data: JsonObject,
    ctx: AcpSessionContext,
) -> None:
    """Resolve response futures, detect end_turn, enqueue error sentinels."""
    raw_id = data.get("id")
    rid = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
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

    is_prompt_response = bool(ctx.prompt_id_ref) and rid == ctx.prompt_id_ref[0]
    if is_prompt_response and ctx.prompt_done.is_set():
        logger.warning("Duplicate ACP session/prompt terminal response ignored")
        return
    if "error" in data and is_prompt_response:
        try:
            ctx.chunk_queue.put_nowait(None)
        except asyncio.QueueFull:
            logger.warning("Chunk queue full — dropping error sentinel")
        return
    if not is_prompt_response or "result" not in data:
        return
    result = data.get("result")
    if not isinstance(result, dict):
        ctx.interrupt_exc.append(
            AcpPromptError(
                "ACP session/prompt succeeded without an object result",
                code=AcpErrorCode.INTERNAL_ERROR,
            )
        )
        ctx.prompt_done.set()
        return
    stop_reason = result.get("stopReason")
    if not isinstance(stop_reason, str) or stop_reason not in _TERMINAL_STOP_REASONS:
        ctx.interrupt_exc.append(
            AcpPromptError(
                f"ACP session/prompt returned unsupported stopReason {stop_reason!r}",
                code=AcpErrorCode.INVALID_PARAMS,
                data={"acp_stop_reason": stop_reason},
            )
        )
        ctx.prompt_done.set()
        return
    ctx.prompt_stop_reason = stop_reason
    ctx.prompt_done.set()


async def handle_server_rpc(
    request: ServerRpcRequest,
    ctx: AcpSessionContext,
    config: AcpModelConfig,
    rpc_handler_map: RpcHandlerMap,
) -> None:
    """Capability check + dispatch to handler function via the map."""
    method = request.method
    rpc_id = request.rpc_id
    params = request.params
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
            resp: JsonObject = {
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
        if method in _EFFECTFUL_SERVER_METHODS:
            ctx.effects_may_have_occurred = True
        try:
            resp = await handler(rpc_id, params, ctx, config)
        except asyncio.CancelledError:
            # Session teardown, not a handler fault: the agent is going away and
            # owes no reply. Re-raised so cancellation keeps propagating.
            raise
        except Exception as exc:
            # A handler raising is a request the agent is still waiting on. With
            # no reply it blocks until its own timeout, or worse proceeds as
            # though the operation succeeded - a failed file write read as
            # written. Report the failure as a protocol error so the agent learns
            # the outcome, and keep the exception in the log for the operator.
            logger.error(
                "ACP handler for %s failed; replying with a protocol error",
                method,
                exc_info=exc,
                extra=runtime_log_extra(config),
            )
            resp = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error handling {method}",
                },
            }
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


def _update_native_commands(
    params: JsonObject, update: JsonObject, ctx: AcpSessionContext
) -> None:
    session_id = params.get("sessionId")
    if (
        not isinstance(session_id, str)
        or not session_id
        or session_id != session_id.strip()
        or not session_id.isprintable()
        or len(session_id) > MAX_ACP_SESSION_ID_LENGTH
    ):
        logger.warning("ACP command advertisement omitted a valid sessionId")
        return
    try:
        catalog = ctx.native_commands_for(session_id)
    except ValueError as exc:
        logger.warning("ACP command advertisement blocked: %s", exc)
        return
    try:
        snapshot = _native_command_snapshot(update)
    except ValueError as exc:
        reason = str(exc)
        catalog.replace({}, blocked_reason=reason)
        logger.warning("ACP command advertisement blocked: %s", reason)
    else:
        catalog.replace(snapshot)


def _enqueue_tool_call_chunk(update: JsonObject, ctx: AcpSessionContext) -> None:
    """Relay one incremental tool argument chunk to the graph stream."""
    tid = _json_string(update.get("toolCallId"))
    args_delta = _json_string(update.get("inputDelta"))
    if tid and args_delta:
        try:
            ctx.chunk_queue.put_nowait(
                ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {"id": tid, "name": "", "args": args_delta, "index": 0}
                        ],
                    )
                )
            )
        except asyncio.QueueFull:
            logger.warning(
                "Chunk queue full — dropping tool_call_chunk to prevent deadlock"
            )


async def handle_session_update(
    params: JsonObject,
    ctx: AcpSessionContext,
) -> None:
    """Dispatch all session update notification types."""
    update = lenient_json_object(params.get("update"))
    u_type = _json_string(update.get("sessionUpdate"))

    if u_type in ("agent_message_chunk", "agent_thought_chunk"):
        text = _json_string(lenient_json_object(update.get("content")).get("text"))
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
        _enqueue_tool_call_chunk(update, ctx)
    elif u_type == "tool_call":
        ctx.effects_may_have_occurred = True
        await on_tool_call(update, ctx)
    elif u_type == "tool_call_update":
        ctx.effects_may_have_occurred = True
        await on_tool_call_update(update, ctx)
    elif u_type == "current_mode_update":
        ctx.agent_modes["currentModeId"] = update.get("currentModeId")
    elif u_type == "available_commands_update":
        _update_native_commands(params, update, ctx)
    elif u_type == "plan":
        # Plan updates are metadata; log receipt and let graph-level plan
        # handling in the supervisor/aggregator layer process them.
        plan_entries = update.get("entries")
        logger.debug(
            "ACP plan update: %d entries received",
            len(plan_entries) if isinstance(plan_entries, list) else 0,
        )


async def on_tool_call(update: JsonObject, ctx: AcpSessionContext) -> None:
    """Record a tool_call and enqueue a ToolCallChunk."""
    tid = _json_string(update.get("toolCallId"))
    ctx.tool_calls[tid] = dict(update)
    chunk = ChatGenerationChunk(
        message=AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "id": tid,
                    "name": _json_string(update.get("title")),
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


async def on_tool_call_update(update: JsonObject, ctx: AcpSessionContext) -> None:
    """Update an existing tool_call record and enqueue if new."""
    tid = _json_string(update.get("toolCallId"))
    if tid not in ctx.tool_calls:
        # Unknown toolCallId: synthesise a tool_call entry so the update
        # is not silently lost (TOAD reference pattern for late/out-of-order
        # tool_call_update notifications).
        ctx.tool_calls[tid] = {
            "toolCallId": tid,
            "title": _json_string(update.get("title"), default=tid),
        }
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {
                        "id": tid,
                        "name": _json_string(update.get("title"), default=tid),
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
    if status := _json_string(update.get("status")):
        logger.debug("Tool %s status: %s", tid, status)
