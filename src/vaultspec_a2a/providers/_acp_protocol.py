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

from langchain_core.messages import (
    AIMessageChunk,
    InputTokenDetails,
    OutputTokenDetails,
    UsageMetadata,
)
from langchain_core.outputs import ChatGenerationChunk
from pydantic import TypeAdapter, ValidationError

from ._acp_auth import runtime_log_extra
from ._acp_request import jsonrpc_error, write_frame
from ._acp_types import (
    AcpModelConfig,
    AcpRpcId,
    AcpSessionContext,
    AcpUsageMetadata,
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
_OBSERVED_ONLY_SESSION_UPDATES = frozenset(
    {
        "async_task_progress",
        "async_task_spawned",
        "async_task_state_update",
        "available_commands_update",
        "compaction_summary_chunk",
        "compaction_update",
        "notice",
        "subagent_spawned",
        "subagent_state_update",
    }
)


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


def _resolve_response_future(data: JsonObject, ctx: AcpSessionContext) -> int | None:
    """Settle the matching JSON-RPC future and return its numeric request id."""
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
    return rid


async def handle_client_response(
    data: JsonObject,
    ctx: AcpSessionContext,
) -> None:
    """Resolve response futures, detect end_turn, enqueue error sentinels."""
    rid = _resolve_response_future(data, ctx)

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
    _finish_prompt_response(data, ctx)


def _finish_prompt_response(data: JsonObject, ctx: AcpSessionContext) -> None:
    """Validate a terminal prompt result and settle its stop reason."""
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
    try:
        ctx.prompt_usage = _prompt_usage_metadata(result)
    except ValueError as exc:
        ctx.interrupt_exc.append(
            AcpPromptError(
                f"ACP session/prompt returned invalid usage: {exc}",
                code=AcpErrorCode.INVALID_PARAMS,
            )
        )
        ctx.prompt_done.set()
        return
    ctx.prompt_stop_reason = stop_reason
    ctx.prompt_done.set()


def _token_count(source: JsonObject, key: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _usage_metadata(counts: JsonObject, *, quota: bool) -> UsageMetadata:
    input_count = _token_count(counts, "inputTokens")
    output_count = _token_count(counts, "outputTokens")
    read_count = _token_count(
        counts, "cachedInputTokens" if quota else "cachedReadTokens"
    )
    write_count = _token_count(counts, "cachedWriteTokens")
    total_count = _token_count(counts, "totalTokens")
    if total_count != input_count + output_count + read_count + write_count:
        raise ValueError("totalTokens disagrees with its token breakdown")
    return UsageMetadata(
        input_tokens=input_count + read_count + write_count,
        output_tokens=output_count,
        total_tokens=total_count,
        input_token_details=InputTokenDetails(
            cache_read=read_count, cache_creation=write_count
        ),
        output_token_details=OutputTokenDetails(
            reasoning=_token_count(counts, "reasoningOutputTokens") if quota else 0
        ),
    )


def _prompt_usage_metadata(result: JsonObject) -> AcpUsageMetadata | None:
    """Prefer accounting-grade model rows over the main-loop usage summary."""
    raw_meta = result.get("_meta")
    if raw_meta is not None and not isinstance(raw_meta, dict):
        raise ValueError("_meta must be an object")
    raw_quota = raw_meta.get("quota") if isinstance(raw_meta, dict) else None
    if raw_quota is not None and not isinstance(raw_quota, dict):
        raise ValueError("_meta.quota must be an object")
    raw_models = raw_quota.get("model_usage") if isinstance(raw_quota, dict) else None
    if raw_models is not None and not isinstance(raw_models, list):
        raise ValueError("_meta.quota.model_usage must be an array")
    model_usage: dict[str, UsageMetadata] = {}
    reasoning_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    for raw_model in raw_models or []:
        if not isinstance(raw_model, dict):
            raise ValueError("model_usage entries must be objects")
        model = raw_model.get("model")
        counts = raw_model.get("token_count")
        if not isinstance(model, str) or not model or model in model_usage:
            raise ValueError("model_usage model must be unique non-empty text")
        if not isinstance(counts, dict):
            raise ValueError("model_usage token_count must be an object")
        model_usage[model] = _usage_metadata(counts, quota=True)
        reasoning_tokens += _token_count(counts, "reasoningOutputTokens")
        cache_read_tokens += _token_count(counts, "cachedInputTokens")
        cache_write_tokens += _token_count(counts, "cachedWriteTokens")

    if model_usage:
        return AcpUsageMetadata(
            input_tokens=sum(row["input_tokens"] for row in model_usage.values()),
            output_tokens=sum(row["output_tokens"] for row in model_usage.values()),
            total_tokens=sum(row["total_tokens"] for row in model_usage.values()),
            input_token_details=InputTokenDetails(
                cache_read=cache_read_tokens,
                cache_creation=cache_write_tokens,
            ),
            output_token_details=OutputTokenDetails(reasoning=reasoning_tokens),
            model_usage=model_usage,
        )

    raw_usage = result.get("usage")
    if raw_usage is None:
        return None
    if not isinstance(raw_usage, dict):
        raise ValueError("usage must be an object")
    return AcpUsageMetadata(**_usage_metadata(raw_usage, quota=False))


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
            await write_frame(
                ctx.stdin,
                ctx.stdin_lock,
                jsonrpc_error(
                    rpc_id,
                    AcpErrorCode.METHOD_NOT_FOUND,
                    f"Capability not enabled: {method}",
                ),
            )
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
            resp = jsonrpc_error(
                rpc_id,
                AcpErrorCode.INTERNAL_ERROR,
                f"Internal error handling {method}",
            )
    else:
        resp = jsonrpc_error(
            rpc_id, AcpErrorCode.METHOD_NOT_FOUND, f"Method not found: {method}"
        )

    await write_frame(ctx.stdin, ctx.stdin_lock, resp)


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


def _enqueue_message_chunk(update: JsonObject, ctx: AcpSessionContext) -> None:
    text = _json_string(lenient_json_object(update.get("content")).get("text"))
    if not text:
        return
    try:
        ctx.chunk_queue.put_nowait(
            ChatGenerationChunk(message=AIMessageChunk(content=text))
        )
    except asyncio.QueueFull:
        logger.warning("Chunk queue full — dropping chunk to prevent deadlock")


async def handle_session_update(
    params: JsonObject,
    ctx: AcpSessionContext,
) -> None:
    """Dispatch all session update notification types."""
    update = lenient_json_object(params.get("update"))
    u_type = _json_string(update.get("sessionUpdate"))

    if u_type in ("agent_message_chunk", "agent_thought_chunk"):
        _enqueue_message_chunk(update, ctx)
        return
    if u_type == "tool_call_chunk":
        # M20: handle incremental tool call argument streaming.
        # ACP agents stream partial JSON args via tool_call_chunk before the
        # final tool_call event.  Forwarded as a streaming ToolCallChunk so
        # LangGraph can accumulate args progressively.
        _enqueue_tool_call_chunk(update, ctx)
        return
    if u_type == "tool_call":
        ctx.effects_may_have_occurred = True
        await on_tool_call(update, ctx)
        return
    if u_type == "tool_call_update":
        ctx.effects_may_have_occurred = True
        await on_tool_call_update(update, ctx)
        return
    if u_type == "current_mode_update":
        ctx.agent_modes["currentModeId"] = update.get("currentModeId")
        return
    if u_type == "plan":
        # Plan updates are metadata; log receipt and let graph-level plan
        # handling in the supervisor/event-producer layer process them.
        plan_entries = update.get("entries")
        logger.debug(
            "ACP plan update: %d entries received",
            len(plan_entries) if isinstance(plan_entries, list) else 0,
        )
        return
    if u_type == "usage_update":
        # This is context-window occupancy, not the accounting-grade per-model
        # usage on the terminal prompt response. Logging it must not add tokens
        # to the turn's usage metadata a second time.
        used, size = update.get("used"), update.get("size")
        if (
            isinstance(used, int)
            and not isinstance(used, bool)
            and isinstance(size, int)
            and not isinstance(size, bool)
        ):
            logger.debug("ACP context usage update: used=%d size=%d", used, size)
        else:
            logger.debug("ACP context usage update received")
        return
    if u_type == "config_option_update":
        options = update.get("configOptions")
        if isinstance(options, list):
            logger.debug("ACP config option update: %d options received", len(options))
        else:
            logger.warning("ACP config option update omitted configOptions array")
        return
    if u_type == "session_info_update":
        # AIR goal and file-change metadata may contain workspace or user text.
        logger.debug("ACP session info update received")
        return
    if u_type in _OBSERVED_ONLY_SESSION_UPDATES:
        logger.debug("ACP session update observed: %s", u_type)
        return
    # Future adapter versions remain compatible without silently dropping a
    # newly introduced update. Never log the payload: it may contain prompts.
    kind = u_type if 0 < len(u_type) <= 64 and u_type.isprintable() else "<invalid>"
    logger.debug("ACP unrecognized session update: %s", kind)


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
