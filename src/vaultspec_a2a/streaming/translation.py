"""Shared projections from model and tool activity onto wire events.

Two surfaces produce this material and both project it the same way: the
graph's ``messages`` stream mode carries the model's own tokens, and LangChain's
callback surface carries a tool's lifecycle. Keeping the projection here is
what stops the two lanes from drifting into two descriptions of one tool call.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, cast

from ..domain_config import domain_config
from ..graph.enums import ToolCallStatus
from .types import (
    action_detail_projection,
    classify_tool_kind,
    map_action_item_status,
    parse_action_detail,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .buffering import BufferingManager
    from .emitters import EventEmitters

__all__ = [
    "ModelStreamProjection",
    "ToolEmission",
    "emit_additional_reasoning",
    "emit_tool_artifact",
    "text_field",
    "translate_content_blocks",
    "translate_tool_call_chunks",
]


def text_field(mapping: Mapping[str, object], key: str) -> str:
    """Read a string field from an untrusted mapping, defaulting to ``""``."""
    value = mapping.get(key, "")
    return value if isinstance(value, str) else ""


def artifact_label_from_tool_input(file_path: str) -> str:
    """Collapse a raw tool path to a display-safe filename label."""
    normalized = file_path.replace("\\", "/").rstrip("/")
    if not normalized:
        return "artifact"
    return PurePath(normalized).name or "artifact"


@dataclass(frozen=True, slots=True)
class ToolEmission:
    """One tool call's identity on the wire, and where to send its events."""

    thread_id: str
    agent_id: str
    tool_call_id: str
    emitters: EventEmitters


async def emit_completed_action(
    emission: ToolEmission,
    item_type: str,
    detail: dict[str, Any],
) -> None:
    """Register and immediately resolve a Codex one-shot completed-action item.

    Codex reports these only on ``item/completed`` (see
    ``codex_chat_model._completed_action_chunk`` - "a started command has no
    exit code"), so there is no separate live start phase to observe: this
    site sees the whole lifecycle at once. It still emits a start-then-update
    pair, matching the genuine-``BaseTool`` path, so both lanes reach the wire
    through the same two-event shape a consumer already expects.
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


async def translate_tool_call_chunks(
    chunk: Any,
    thread_id: str,
    effective_agent_id: str,
    emitters: EventEmitters,
) -> None:
    """Translate a streamed chunk's ``tool_call_chunks`` into tool-call events.

    Provider-internal tool activity (an ACP CLI's own built-in tools, a
    Codex ``commandExecution``/``fileChange``/``mcpToolCall`` action) never
    goes through a real LangChain ``BaseTool``/``ToolNode``, so the tool
    callbacks never fire for it - the only place this activity reaches the
    stream at all is as ``tool_call_chunks`` on an ``AIMessageChunk``. Without
    reading them here, every one of these calls stays unregistered for the
    run's entire live stream and can only be reconstructed - incorrectly,
    permanently PENDING - from checkpoint state after the run ended.
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
            await emit_completed_action(
                ToolEmission(thread_id, effective_agent_id, tc_id, emitters),
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
class ModelStreamProjection:
    """One model turn's wire identity, and where its text is sent."""

    thread_id: str
    agent_id: str
    message_id: str
    emitters: EventEmitters
    buffering: BufferingManager


async def translate_content_blocks(
    content_blocks: list[object], projection: ModelStreamProjection
) -> None:
    """Split a structured content chunk into reasoning and message text."""
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_map = cast("dict[str, object]", block)
        if block_map.get("type") == "reasoning":
            reasoning_text = text_field(block_map, "content") or text_field(
                block_map, "text"
            )
            if reasoning_text:
                await projection.emitters.emit_thought_chunk(
                    thread_id=projection.thread_id,
                    agent_id=projection.agent_id,
                    content=reasoning_text,
                    message_id=projection.message_id,
                )
        elif block_map.get("type") in ("text", "text_delta"):
            text = text_field(block_map, "text") or text_field(block_map, "content")
            if text:
                await projection.buffering.buffer_message_chunk(
                    thread_id=projection.thread_id,
                    agent_id=projection.agent_id,
                    content=text,
                    message_id=projection.message_id,
                )


async def emit_additional_reasoning(
    chunk: object, projection: ModelStreamProjection
) -> None:
    """Relay a provider's out-of-band reasoning field as a thought."""
    additional_kwargs_raw = getattr(chunk, "additional_kwargs", {}) or {}
    additional_kwargs = cast(
        "dict[str, object]",
        additional_kwargs_raw if isinstance(additional_kwargs_raw, dict) else {},
    )
    reasoning = text_field(additional_kwargs, "reasoning") or text_field(
        additional_kwargs, "reasoning_content"
    )
    if reasoning:
        await projection.emitters.emit_thought_chunk(
            thread_id=projection.thread_id,
            agent_id=projection.agent_id,
            content=reasoning,
            message_id=projection.message_id,
        )


def tool_output_text(output: object) -> str:
    """Render a tool's return value as the text a client is shown."""
    content_attr = getattr(output, "content", None)
    if content_attr is not None:
        return str(content_attr)
    if isinstance(output, str):
        return output
    return str(output)


async def emit_tool_artifact(
    emission: ToolEmission,
    tool_name: str,
    tool_input: object,
    output: object,
) -> None:
    """Project a completed file tool's path into its artifact update."""
    file_tool_keywords = {"write", "edit", "create", "save", "move", "rename", "delete"}
    if not any(keyword in tool_name.lower() for keyword in file_tool_keywords):
        return
    output_str = tool_output_text(output) if output is not None else ""
    file_path = ""
    if isinstance(tool_input, dict):
        tool_input_map = cast("dict[str, object]", tool_input)
        file_path = (
            text_field(tool_input_map, "file_path")
            or text_field(tool_input_map, "path")
            or text_field(tool_input_map, "filename")
        )
    if not file_path:
        return
    filename = artifact_label_from_tool_input(file_path)
    await emission.emitters.emit_artifact_update(
        thread_id=emission.thread_id,
        artifact_id=f"{emission.tool_call_id}:{filename}",
        filename=filename,
        content=output_str[:500] if output_str else f"[{tool_name}] {filename}",
    )


def truncated_tool_content(text: str) -> list[dict[str, str | None]] | None:
    """Bound a tool's own output to the length a wire frame carries."""
    if not text:
        return None
    max_len = domain_config.tool_arg_truncate_len
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return [{"content_type": "text", "text": text}]


async def emit_tool_completion(
    emission: ToolEmission,
    tool_name: str,
    tool_input: object,
    output: object,
) -> None:
    """Resolve one tool call and publish any artifact it produced."""
    output_str = tool_output_text(output) if output is not None else ""
    await emission.emitters.emit_tool_call_update(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        tool_call_id=emission.tool_call_id,
        status=ToolCallStatus.COMPLETED,
        content=truncated_tool_content(output_str),
    )
    await emit_tool_artifact(emission, tool_name, tool_input, output)
