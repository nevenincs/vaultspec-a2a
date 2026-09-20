"""LangGraph event transformation — maps raw astream_events to domain events.

Contains the ``process_langgraph_event`` function and the interrupt detection
logic.  Extracted from the monolithic ``aggregator.py`` during the aggregator
decomposition.

These functions are *logically* stateless — they receive emitter/buffering
references to perform side effects but hold no state of their own.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, cast
from uuid import uuid4

from ..domain_config import domain_config
from ..graph.enums import (
    AgentLifecycleState,
    ToolCallStatus,
)
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ._interrupt_projection import emit_interrupt_events as emit_interrupt_events
from .buffering import BufferingManager
from .emitters import EventEmitters
from .sse_frames import enforce_progress_allowlist
from .types import (
    NODE_BOUNDARY_EVENTS,
    PASSTHROUGH_EVENTS,
    action_detail_projection,
    classify_tool_kind,
    map_action_item_status,
    parse_action_detail,
)

# Import GraphInterrupt for isinstance check vs string comparison.
try:
    from langgraph.errors import GraphInterrupt as _GraphInterrupt_cls

    GraphInterrupt: type[Exception] | None = _GraphInterrupt_cls
except ImportError:
    GraphInterrupt = None

try:
    from langgraph.errors import GraphRecursionError as _GraphRecursionError_cls

    GraphRecursionError: type[Exception] | None = _GraphRecursionError_cls
except ImportError:
    GraphRecursionError = None

logger = logging.getLogger(__name__)


def project_run_progress(payload: object) -> object:
    """Transform a relayed gateway run event through the positive progress DTO.

    The gateway relays each worker run event onto the public progress edge; this
    is the producer-side projection that drops prompts, document and artifact
    bodies, edit diffs, and raw provider payloads before the event ever reaches a
    subscriber queue, keeping only the identifiers, lifecycle state, tool and
    artifact identity, and bounded text its frame type enumerates in the closed
    progress catalog. A non-mapping payload is returned unchanged. The encode
    boundary re-applies the catalog, so the exclusion still holds if this call
    site is bypassed; both layers call the one shared catalog deliberately, so
    they cannot drift apart.
    """
    if isinstance(payload, Mapping):
        return enforce_progress_allowlist(cast("Mapping[str, object]", payload))
    return payload


def _data_field(event_data: dict[str, Any]) -> dict[str, Any]:
    """Return the event's ``data`` mapping, or an empty mapping when absent."""
    data = event_data.get("data")
    return cast("dict[str, Any]", data) if isinstance(data, dict) else {}


def _text_field(mapping: Mapping[str, object], key: str) -> str:
    """Read a string field from an untrusted mapping, defaulting to ``""``."""
    value = mapping.get(key, "")
    return value if isinstance(value, str) else ""


def _artifact_label_from_tool_input(file_path: str) -> str:
    """Collapse a raw tool path to a display-safe filename label."""
    normalized = file_path.replace("\\", "/").rstrip("/")
    if not normalized:
        return "artifact"
    return PurePath(normalized).name or "artifact"


@dataclass(frozen=True, slots=True)
class _ToolEmission:
    thread_id: str
    agent_id: str
    tool_call_id: str
    node: str | None
    emitters: EventEmitters


async def _emit_completed_action(
    emission: _ToolEmission,
    item_type: str,
    detail: dict[str, Any],
) -> None:
    """Register and immediately resolve a Codex one-shot completed-action item.

    Codex reports these only on ``item/completed`` (see
    ``codex_chat_model._completed_action_chunk`` - "a started command has no
    exit code"), so there is no separate live start phase to observe: this
    site sees the whole lifecycle at once. It still emits a start-then-update
    pair, matching ``_translate_tool_start``/``_translate_tool_end`` (the
    genuine-``BaseTool`` path) so both lanes reach the wire through the same
    two-event shape a consumer already expects.
    """
    status = map_action_item_status(detail.get("status"))
    content, locations = action_detail_projection(item_type, detail)
    await emission.emitters.emit_tool_call_start(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        tool_call_id=emission.tool_call_id,
        title=item_type,
        kind=classify_tool_kind(item_type),
    )
    await emission.emitters.emit_tool_call_update(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        tool_call_id=emission.tool_call_id,
        status=status,
        content=content,
        locations=locations,
    )


async def _translate_tool_call_chunks(
    chunk: Any,
    thread_id: str,
    effective_agent_id: str,
    emitters: EventEmitters,
) -> None:
    """Translate a streamed chunk's ``tool_call_chunks`` into tool-call events.

    Provider-internal tool activity (an ACP CLI's own built-in tools, a
    Codex ``commandExecution``/``fileChange``/``mcpToolCall`` action) never
    goes through a real LangChain ``BaseTool``/``ToolNode``, so
    ``on_tool_start``/``on_tool_end`` never fire for it - the only place this
    activity reaches ``astream_events`` at all is as ``tool_call_chunks`` on
    an ``AIMessageChunk`` flowing through ``on_chat_model_stream``. This was
    previously not read here (only ``chunk.content`` was), so every one of
    these calls stayed unregistered for the run's entire live stream and
    could only be reconstructed - incorrectly, permanently PENDING - from
    checkpoint state after the run ended (F17).
    """
    tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
    if not tool_call_chunks:
        return
    known = emitters.get_tool_call_states(thread_id)
    for tc in tool_call_chunks:
        tc_id = tc.get("id")
        if not isinstance(tc_id, str) or not tc_id:
            continue
        name = tc.get("name") or "unknown_tool"
        detail = parse_action_detail(tc.get("args"))
        if detail is not None and "status" in detail:
            # Codex's completed-action shape: a single self-contained
            # terminal report, not a plain registration.
            await _emit_completed_action(
                _ToolEmission(thread_id, effective_agent_id, tc_id, None, emitters),
                name,
                detail,
            )
            continue
        if tc_id in known:
            # Already registered (the initial chunk, or an earlier
            # partial-args delta for the same id) - do not re-register.
            continue
        await emitters.emit_tool_call_start(
            thread_id=thread_id,
            agent_id=effective_agent_id,
            tool_call_id=tc_id,
            title=name,
            kind=classify_tool_kind(name),
        )


@dataclass(frozen=True, slots=True)
class _ModelStreamProjection:
    thread_id: str
    agent_id: str
    run_id: str
    emitters: EventEmitters
    buffering: BufferingManager


async def _translate_chat_model_stream(
    event_data: dict[str, Any], projection: _ModelStreamProjection
) -> None:
    chunk: object = _data_field(event_data).get("chunk")
    if chunk is None:
        return
    await _translate_tool_call_chunks(
        chunk, projection.thread_id, projection.agent_id, projection.emitters
    )
    content: object = getattr(chunk, "content", "")
    if isinstance(content, list):
        await _translate_content_blocks(cast("list[object]", content), projection)
        return
    if isinstance(content, str) and content:
        await projection.buffering.buffer_message_chunk(
            thread_id=projection.thread_id,
            agent_id=projection.agent_id,
            content=content,
            message_id=projection.run_id,
        )
    await _emit_additional_reasoning(chunk, projection)


async def _translate_content_blocks(
    content_blocks: list[object], projection: _ModelStreamProjection
) -> None:
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_map = cast("dict[str, object]", block)
        if block_map.get("type") == "reasoning":
            reasoning_text = _text_field(block_map, "content") or _text_field(
                block_map, "text"
            )
            if reasoning_text:
                await projection.emitters.emit_thought_chunk(
                    thread_id=projection.thread_id,
                    agent_id=projection.agent_id,
                    content=reasoning_text,
                    message_id=projection.run_id,
                )
        elif block_map.get("type") in ("text", "text_delta"):
            text = _text_field(block_map, "text") or _text_field(block_map, "content")
            if text:
                await projection.buffering.buffer_message_chunk(
                    thread_id=projection.thread_id,
                    agent_id=projection.agent_id,
                    content=text,
                    message_id=projection.run_id,
                )


async def _emit_additional_reasoning(
    chunk: object, projection: _ModelStreamProjection
) -> None:
    additional_kwargs_raw = getattr(chunk, "additional_kwargs", {}) or {}
    additional_kwargs = cast(
        "dict[str, object]",
        additional_kwargs_raw if isinstance(additional_kwargs_raw, dict) else {},
    )
    reasoning = _text_field(additional_kwargs, "reasoning") or _text_field(
        additional_kwargs, "reasoning_content"
    )
    if reasoning:
        await projection.emitters.emit_thought_chunk(
            thread_id=projection.thread_id,
            agent_id=projection.agent_id,
            content=reasoning,
            message_id=projection.run_id,
        )


async def _translate_chat_model_end(
    event_data: dict[str, Any], projection: _ModelStreamProjection
) -> None:
    await projection.buffering.flush_chunk_buffer(projection.thread_id)
    output: object = _data_field(event_data).get("output")
    finish_reason: str | None = None
    if output is not None:
        resp_meta_raw: object = getattr(output, "response_metadata", None) or {}
        resp_meta = cast(
            "dict[str, object]",
            resp_meta_raw if isinstance(resp_meta_raw, dict) else {},
        )
        finish_reason = _text_field(resp_meta, "finish_reason") or _text_field(
            resp_meta, "stop_reason"
        )
    if finish_reason:
        await projection.emitters.emit_message_chunk(
            thread_id=projection.thread_id,
            agent_id=projection.agent_id,
            content="",
            message_id=projection.run_id,
            finish_reason=finish_reason,
        )


async def _translate_tool_start(
    event_data: dict[str, Any],
    emission: _ToolEmission,
) -> None:
    if emission.node:
        tool_name = event_data.get("name", "unknown_tool")
        tool_input: object = _data_field(event_data).get("input")
        input_args = (
            cast("dict[str, Any]", tool_input) if isinstance(tool_input, dict) else None
        )
        await emission.emitters.emit_tool_call_start(
            thread_id=emission.thread_id,
            agent_id=emission.agent_id,
            tool_call_id=emission.tool_call_id,
            title=tool_name,
            kind=classify_tool_kind(tool_name),
            input_args=input_args,
        )


async def _emit_tool_artifact(
    event_data: dict[str, Any],
    emission: _ToolEmission,
    tool_name: str,
    output: object,
) -> None:
    """Project a completed file tool's path into its artifact update."""
    file_tool_keywords = {"write", "edit", "create", "save", "move", "rename", "delete"}
    if not any(keyword in tool_name.lower() for keyword in file_tool_keywords):
        return
    output_str = ""
    output_content_attr = getattr(output, "content", None)
    if output_content_attr is not None:
        output_str = str(output_content_attr)
    elif isinstance(output, str):
        output_str = output
    tool_input_end: object = _data_field(event_data).get("input", {})
    file_path = ""
    if isinstance(tool_input_end, dict):
        tool_input_map = cast("dict[str, object]", tool_input_end)
        file_path = (
            _text_field(tool_input_map, "file_path")
            or _text_field(tool_input_map, "path")
            or _text_field(tool_input_map, "filename")
        )
    if not file_path:
        return
    filename = _artifact_label_from_tool_input(file_path)
    await emission.emitters.emit_artifact_update(
        thread_id=emission.thread_id,
        artifact_id=f"{emission.tool_call_id}:{filename}",
        filename=filename,
        content=output_str[:500] if output_str else f"[{tool_name}] {filename}",
    )


async def _translate_tool_end(
    event_data: dict[str, Any],
    emission: _ToolEmission,
) -> None:
    if emission.node:
        tool_name = event_data.get("name", "")
        output: object = _data_field(event_data).get("output")
        output_content: list[dict[str, str | None]] | None = None
        if output is not None:
            output_str = ""
            output_content_attr = getattr(output, "content", None)
            if output_content_attr is not None:
                output_str = str(output_content_attr)
            elif isinstance(output, str):
                output_str = output
            else:
                output_str = str(output)
            if output_str:
                max_len = domain_config.tool_arg_truncate_len
                if len(output_str) > max_len:
                    output_str = output_str[:max_len] + "..."
                output_content = [{"content_type": "text", "text": output_str}]
        await emission.emitters.emit_tool_call_update(
            thread_id=emission.thread_id,
            agent_id=emission.agent_id,
            tool_call_id=emission.tool_call_id,
            status=ToolCallStatus.COMPLETED,
            content=output_content,
        )
        await _emit_tool_artifact(event_data, emission, tool_name, output)


async def _translate_tool_error(
    event_data: dict[str, Any],
    emission: _ToolEmission,
) -> None:
    if emission.node:
        error_data = event_data.get("data", {})
        error_msg = str(error_data.get("error", "Tool call failed"))
        logger.warning(
            "Tool error in thread %s node %s: %s",
            emission.thread_id,
            emission.node,
            error_msg,
        )
        error_content: list[dict[str, str | None]] | None = (
            [{"content_type": "text", "text": error_msg}] if error_msg else None
        )
        await emission.emitters.emit_tool_call_update(
            thread_id=emission.thread_id,
            agent_id=emission.agent_id,
            tool_call_id=emission.tool_call_id,
            status=ToolCallStatus.FAILED,
            content=error_content,
        )


async def _translate_custom_event(
    event_data: dict[str, Any],
    thread_id: str,
    effective_agent_id: str,
    run_id: str,
    emitters: EventEmitters,
) -> None:
    data = event_data.get("data", {})
    content = data if isinstance(data, str) else str(data.get("content", ""))
    if content:
        max_len = domain_config.tool_arg_truncate_len
        if len(content) > max_len:
            content = content[:max_len] + "..."
        await emitters.emit_thought_chunk(
            thread_id=thread_id,
            agent_id=effective_agent_id,
            content=content,
            message_id=run_id,
        )


async def _translate_node_boundary(
    event_data: dict[str, Any],
    thread_id: str,
    effective_agent_id: str,
    node: str,
    emitters: EventEmitters,
) -> None:
    # The dispatcher only calls this under ``and node``, so node is never None
    # here - typed accordingly so the agent-status calls type-check.
    event_kind = event_data.get("event", "")
    if event_kind == "on_chain_start":
        await emitters.emit_agent_status(
            thread_id=thread_id,
            agent_id=effective_agent_id,
            node_name=node,
            state=AgentLifecycleState.WORKING,
        )
    elif event_kind == "on_chain_end":
        await emitters.emit_agent_status(
            thread_id=thread_id,
            agent_id=effective_agent_id,
            node_name=node,
            state=AgentLifecycleState.IDLE,
        )
        await _emit_chain_output(
            _data_field(event_data).get("output"), thread_id, emitters
        )
    elif event_kind == "on_chain_error":
        error_data = event_data.get("data", {})
        error_msg = str(error_data.get("error", "Node execution failed"))
        logger.warning(
            "Chain error in thread %s node %s: %s",
            thread_id,
            node,
            error_msg,
        )
        await emitters.emit_agent_status(
            thread_id=thread_id,
            agent_id=effective_agent_id,
            node_name=node,
            state=AgentLifecycleState.FAILED,
            detail=error_msg[:200],
        )


async def _emit_chain_output(
    output: object, thread_id: str, emitters: EventEmitters
) -> None:
    if not isinstance(output, dict):
        return
    output_map = cast("dict[str, object]", output)
    await _emit_chain_plan(output_map.get("current_plan"), thread_id, emitters)
    await _emit_chain_artifacts(output_map.get("artifacts"), thread_id, emitters)


async def _emit_chain_plan(
    raw_plan: object, thread_id: str, emitters: EventEmitters
) -> None:
    if not isinstance(raw_plan, list) or not raw_plan:
        return
    entries: list[dict[str, str]] = [
        {
            "content": _text_field(entry_map, "content"),
            "status": _text_field(entry_map, "status") or "pending",
            "priority": _text_field(entry_map, "priority") or "medium",
        }
        for entry in cast("list[object]", raw_plan)
        if isinstance(entry, dict)
        for entry_map in (cast("dict[str, object]", entry),)
        if entry_map.get("content")
    ]
    if entries:
        await emitters.emit_plan_update(thread_id, entries)


async def _emit_chain_artifacts(
    raw_artifacts: object, thread_id: str, emitters: EventEmitters
) -> None:
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        return
    for artifact in cast("list[object]", raw_artifacts):
        if not isinstance(artifact, dict):
            continue
        artifact_map = cast("dict[str, object]", artifact)
        if artifact_map.get("id"):
            await emitters.emit_artifact_update(
                thread_id=thread_id,
                artifact_id=str(artifact_map["id"]),
                filename=str(
                    artifact_map.get("filename", artifact_map.get("path", ""))
                ),
                content=str(artifact_map.get("content", "")),
            )


@dataclass(frozen=True, slots=True)
class EventProjectionServices:
    """The stable emitter, buffer, and telemetry dependencies for one stream."""

    emitters: EventEmitters
    buffering: BufferingManager
    telemetry: TelemetryHook | NullTelemetryHook


async def process_langgraph_event(
    event_data: dict[str, Any],
    thread_id: str,
    agent_id: str,
    services: EventProjectionServices,
) -> None:
    """Transform a LangGraph astream_events callback into wire events.

    Filters events using ``langgraph_node`` metadata to eliminate
    ~60% of noisy sub-runnable events (research §1.2).
    """
    emitters = services.emitters
    buffering = services.buffering
    telemetry = services.telemetry
    event_kind = event_data.get("event", "")
    run_id = event_data.get("run_id", str(uuid4()))
    metadata = event_data.get("metadata", {})
    node = metadata.get("langgraph_node")

    effective_agent_id = node or agent_id

    if event_kind == "on_chat_model_stream":
        projection = _ModelStreamProjection(
            thread_id, effective_agent_id, run_id, emitters, buffering
        )
        await _translate_chat_model_stream(event_data, projection)
        return
    if event_kind == "on_chat_model_end":
        projection = _ModelStreamProjection(
            thread_id, effective_agent_id, run_id, emitters, buffering
        )
        await _translate_chat_model_end(event_data, projection)
        return
    if event_kind == "on_tool_start":
        emission = _ToolEmission(thread_id, effective_agent_id, run_id, node, emitters)
        await _translate_tool_start(event_data, emission)
        return
    if event_kind == "on_tool_end":
        emission = _ToolEmission(thread_id, effective_agent_id, run_id, node, emitters)
        await _translate_tool_end(event_data, emission)
        return
    if event_kind == "on_tool_error":
        emission = _ToolEmission(thread_id, effective_agent_id, run_id, node, emitters)
        await _translate_tool_error(event_data, emission)
        return
    if event_kind == "on_custom_event":
        await _translate_custom_event(
            event_data, thread_id, effective_agent_id, run_id, emitters
        )
        return
    if event_kind in NODE_BOUNDARY_EVENTS and node:
        await _translate_node_boundary(
            event_data, thread_id, effective_agent_id, node, emitters
        )

    _record_filtered_event(event_kind, run_id, telemetry)


def _record_filtered_event(
    event_kind: str,
    run_id: str,
    telemetry: TelemetryHook | NullTelemetryHook,
) -> None:
    # Everything else is filtered out (research §1.2).
    if event_kind not in PASSTHROUGH_EVENTS | NODE_BOUNDARY_EVENTS:
        telemetry.increment_counter(
            "aggregator.events_filtered", 1, **{"event.kind": event_kind}
        )
        logger.debug(
            "Filtered LangGraph event: %s (run_id=%s)",
            event_kind,
            run_id,
        )
