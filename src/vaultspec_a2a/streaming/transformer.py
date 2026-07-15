"""LangGraph event transformation — maps raw astream_events to domain events.

Contains the ``process_langgraph_event`` function and the interrupt detection
logic.  Extracted from the monolithic ``aggregator.py`` during Phase 6
decomposition (ADR D-01).

These functions are *logically* stateless — they receive emitter/buffering
references to perform side effects but hold no state of their own.
"""

import asyncio
import logging
from pathlib import PurePath
from typing import Any
from uuid import uuid4

from ..domain_config import domain_config
from ..graph.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    PermissionType,
    ToolCallStatus,
)
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from .buffering import BufferingManager
from .emitters import EventEmitters
from .types import (
    NODE_BOUNDARY_EVENTS,
    PASSTHROUGH_EVENTS,
    StreamableGraph,
    classify_tool_kind,
    map_acp_option_kind,
)

# M6: import GraphInterrupt for isinstance check vs string comparison.
try:
    from langgraph.errors import GraphInterrupt as _GraphInterrupt_cls

    _GraphInterrupt: type[Exception] | None = _GraphInterrupt_cls
except ImportError:
    _GraphInterrupt = None

try:
    from langgraph.errors import GraphRecursionError as _GraphRecursionError_cls

    _GraphRecursionError: type[Exception] | None = _GraphRecursionError_cls
except ImportError:
    _GraphRecursionError = None

logger = logging.getLogger(__name__)


def _artifact_label_from_tool_input(file_path: str) -> str:
    """Collapse a raw tool path to a display-safe filename label."""
    normalized = file_path.replace("\\", "/").rstrip("/")
    if not normalized:
        return "artifact"
    return PurePath(normalized).name or "artifact"


async def process_langgraph_event(
    event_data: dict[str, Any],
    thread_id: str,
    agent_id: str,
    emitters: EventEmitters,
    buffering: BufferingManager,
    telemetry: TelemetryHook | NullTelemetryHook,
) -> None:
    """Transform a LangGraph astream_events callback into wire events.

    Filters events using ``langgraph_node`` metadata to eliminate
    ~60% of noisy sub-runnable events (research §1.2).
    """
    event_kind = event_data.get("event", "")
    run_id = event_data.get("run_id", str(uuid4()))
    metadata = event_data.get("metadata", {})
    node = metadata.get("langgraph_node")

    effective_agent_id = node or agent_id

    # --- Passthrough events (no node filter needed for LLM/tool) ---
    if event_kind == "on_chat_model_stream":
        chunk = event_data.get("data", {}).get("chunk")
        if chunk is not None:
            content = getattr(chunk, "content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "reasoning":
                            reasoning_text = block.get("content", "") or block.get(
                                "text", ""
                            )
                            if reasoning_text:
                                await emitters.emit_thought_chunk(
                                    thread_id=thread_id,
                                    agent_id=effective_agent_id,
                                    content=reasoning_text,
                                    message_id=run_id,
                                )
                        elif block.get("type") in ("text", "text_delta"):
                            text = block.get("text", "") or block.get("content", "")
                            if text:
                                await buffering.buffer_message_chunk(
                                    thread_id=thread_id,
                                    agent_id=effective_agent_id,
                                    content=text,
                                    message_id=run_id,
                                )
            elif isinstance(content, str) and content:
                await buffering.buffer_message_chunk(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    content=content,
                    message_id=run_id,
                )
            if not isinstance(content, list):
                additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
                reasoning = (
                    additional_kwargs.get("reasoning")
                    or additional_kwargs.get("reasoning_content")
                    or ""
                )
                if reasoning:
                    await emitters.emit_thought_chunk(
                        thread_id=thread_id,
                        agent_id=effective_agent_id,
                        content=reasoning,
                        message_id=run_id,
                    )
        return

    if event_kind == "on_chat_model_end":
        await buffering.flush_chunk_buffer(thread_id)
        output = event_data.get("data", {}).get("output")
        finish_reason: str | None = None
        if output is not None:
            resp_meta = getattr(output, "response_metadata", None) or {}
            finish_reason = resp_meta.get("finish_reason") or resp_meta.get(
                "stop_reason"
            )
        if finish_reason:
            await emitters.emit_message_chunk(
                thread_id=thread_id,
                agent_id=effective_agent_id,
                content="",
                message_id=run_id,
                finish_reason=finish_reason,
            )
        return

    if event_kind == "on_tool_start":
        if node:
            tool_name = event_data.get("name", "unknown_tool")
            tool_input = event_data.get("data", {}).get("input")
            input_args = tool_input if isinstance(tool_input, dict) else None
            await emitters.emit_tool_call_start(
                thread_id=thread_id,
                agent_id=effective_agent_id,
                tool_call_id=run_id,
                title=tool_name,
                kind=classify_tool_kind(tool_name),
                input_args=input_args,
            )
        return

    if event_kind == "on_tool_end":
        if node:
            tool_name = event_data.get("name", "")
            output = event_data.get("data", {}).get("output")
            output_content: list[dict[str, str | None]] | None = None
            if output is not None:
                output_str = ""
                if hasattr(output, "content"):
                    output_str = str(output.content)
                elif isinstance(output, str):
                    output_str = output
                else:
                    output_str = str(output)
                if output_str:
                    max_len = domain_config.tool_arg_truncate_len
                    if len(output_str) > max_len:
                        output_str = output_str[:max_len] + "..."
                    output_content = [{"content_type": "text", "text": output_str}]
            await emitters.emit_tool_call_update(
                thread_id=thread_id,
                agent_id=effective_agent_id,
                tool_call_id=run_id,
                status=ToolCallStatus.COMPLETED,
                content=output_content,
            )
            _file_tool_keywords = {
                "write",
                "edit",
                "create",
                "save",
                "move",
                "rename",
                "delete",
            }
            if any(kw in tool_name.lower() for kw in _file_tool_keywords):
                output_str = ""
                file_path = ""
                if hasattr(output, "content"):
                    output_str = str(output.content)
                elif isinstance(output, str):
                    output_str = output
                tool_input = event_data.get("data", {}).get("input", {})
                if isinstance(tool_input, dict):
                    file_path = (
                        tool_input.get("file_path", "")
                        or tool_input.get("path", "")
                        or tool_input.get("filename", "")
                    )
                if file_path:
                    filename = _artifact_label_from_tool_input(file_path)
                    await emitters.emit_artifact_update(
                        thread_id=thread_id,
                        artifact_id=f"{run_id}:{filename}",
                        filename=filename,
                        content=output_str[:500]
                        if output_str
                        else f"[{tool_name}] {filename}",
                    )
        return

    if event_kind == "on_tool_error":
        if node:
            error_data = event_data.get("data", {})
            error_msg = str(error_data.get("error", "Tool call failed"))
            logger.warning(
                "Tool error in thread %s node %s: %s",
                thread_id,
                node,
                error_msg,
            )
            error_content: list[dict[str, str | None]] | None = (
                [{"content_type": "text", "text": error_msg}] if error_msg else None
            )
            await emitters.emit_tool_call_update(
                thread_id=thread_id,
                agent_id=effective_agent_id,
                tool_call_id=run_id,
                status=ToolCallStatus.FAILED,
                content=error_content,
            )
        return

    if event_kind == "on_custom_event":
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
        return

    # --- Node boundary events (require langgraph_node metadata) ---
    if event_kind in NODE_BOUNDARY_EVENTS and node:
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
            output = event_data.get("data", {}).get("output")
            if isinstance(output, dict):
                raw_plan = output.get("current_plan")
                if raw_plan and isinstance(raw_plan, list):
                    entries = [
                        {
                            "content": str(entry.get("content", "")),
                            "status": entry.get("status", "pending"),
                            "priority": entry.get("priority", "medium"),
                        }
                        for entry in raw_plan
                        if isinstance(entry, dict) and entry.get("content")
                    ]
                    if entries:
                        await emitters.emit_plan_update(thread_id, entries)
                raw_artifacts = output.get("artifacts")
                if raw_artifacts and isinstance(raw_artifacts, list):
                    for artifact in raw_artifacts:
                        if isinstance(artifact, dict) and artifact.get("id"):
                            await emitters.emit_artifact_update(
                                thread_id=thread_id,
                                artifact_id=str(artifact["id"]),
                                filename=str(
                                    artifact.get("filename", artifact.get("path", ""))
                                ),
                                content=str(artifact.get("content", "")),
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
        return

    # --- Everything else is filtered out (research §1.2) ---
    if event_kind not in PASSTHROUGH_EVENTS | NODE_BOUNDARY_EVENTS:
        telemetry.increment_counter(
            "aggregator.events_filtered", 1, **{"event.kind": event_kind}
        )
        logger.debug(
            "Filtered LangGraph event: %s (run_id=%s)",
            event_kind,
            run_id,
        )


async def emit_interrupt_events(
    thread_id: str,
    _agent_id: str,
    graph: StreamableGraph,
    config: dict[str, Any],
    emitters: EventEmitters,
) -> bool:
    """Inspect graph state after astream_events ends; emit PermissionRequestEvents.

    Returns True if interrupts were detected and emitted.
    """
    timeout = domain_config.aget_state_timeout_seconds

    try:
        state = await asyncio.wait_for(graph.aget_state(config), timeout=timeout)
    except TimeoutError:
        logger.warning(
            "Timed out inspecting state for interrupt detection on thread %s",
            thread_id,
        )
        return False
    except Exception:
        logger.exception(
            "Failed to inspect state for interrupt detection on thread %s",
            thread_id,
        )
        return False

    tasks = getattr(state, "tasks", None)
    if not state or not tasks or not any(t.interrupts for t in tasks):
        return False

    interrupt_detected = True
    for task in tasks:
        if not task.interrupts:
            continue

        for interrupt_obj in task.interrupts:
            payload = getattr(interrupt_obj, "value", interrupt_obj)
            if not isinstance(payload, dict):
                continue
            interrupt_type = payload.get("type")
            if interrupt_type not in (
                "permission_request",
                "plan_approval_request",
                "document_approval_request",
            ):
                continue

            task_idx = tasks.index(task)
            interrupt_idx = task.interrupts.index(interrupt_obj)
            request_id = str(
                payload.get("request_id")
                or getattr(interrupt_obj, "id", None)
                or f"{thread_id}:task{task_idx}:int{interrupt_idx}"
            )

            if request_id in emitters._pending_permissions:
                continue

            if interrupt_type == "plan_approval_request":
                feature: str = payload.get("feature") or "unknown"
                plan_paths: list[str] = payload.get("plan_paths") or []
                exec_worker: str = payload.get("exec_worker") or "unknown"
                plan_summary = (
                    f"{len(plan_paths)} plan document(s)"
                    if plan_paths
                    else "no plan documents"
                )
                description = (
                    f"Approve plan for feature '{feature}' before "
                    f"routing to {exec_worker} ({plan_summary})"
                )
                options: list[dict[str, Any]] = [
                    {
                        "option_id": "approve",
                        "name": "Approve Plan",
                        "kind": PermissionOptionKind.ALLOW_ONCE,
                    },
                    {
                        "option_id": "reject",
                        "name": "Reject — Revise Plan",
                        "kind": PermissionOptionKind.REJECT_ONCE,
                    },
                ]
                await emitters.emit_permission_request(
                    thread_id=thread_id,
                    agent_id=task.name,
                    request_id=request_id,
                    description=description,
                    options=options,
                    tool_call=PermissionType.PLAN_APPROVAL,
                )
                await emitters.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=task.name,
                    node_name=task.name,
                    state=AgentLifecycleState.INPUT_REQUIRED,
                    detail=f"Awaiting plan approval for feature '{feature}'",
                )
            elif interrupt_type == "document_approval_request":
                doc_phase: str = payload.get("phase") or "document"
                doc_feature: str = payload.get("feature") or "unknown"
                description = (
                    f"Approve the {doc_phase} document for feature "
                    f"'{doc_feature}' before the run proceeds"
                )
                options = [
                    {
                        "option_id": "approve",
                        "name": "Approve Document",
                        "kind": PermissionOptionKind.ALLOW_ONCE,
                    },
                    {
                        "option_id": "reject",
                        "name": "Reject — Revise Document",
                        "kind": PermissionOptionKind.REJECT_ONCE,
                    },
                ]
                await emitters.emit_permission_request(
                    thread_id=thread_id,
                    agent_id=task.name,
                    request_id=request_id,
                    description=description,
                    options=options,
                    tool_call=PermissionType.PLAN_APPROVAL,
                )
                await emitters.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=task.name,
                    node_name=task.name,
                    state=AgentLifecycleState.INPUT_REQUIRED,
                    detail=(
                        f"Awaiting {doc_phase} document approval for feature "
                        f"'{doc_feature}'"
                    ),
                )
            else:
                tool_name: str = payload.get("tool_name", "unknown")
                acp_options: list[dict[str, Any]] = payload.get("options", [])

                options = [
                    {
                        "option_id": opt.get(
                            "optionId", opt.get("option_id", "allow_once")
                        ),
                        "name": opt.get(
                            "label",
                            opt.get("name", opt.get("optionId", "Allow")),
                        ),
                        "kind": map_acp_option_kind(
                            opt.get("optionId", opt.get("option_id", ""))
                        ),
                    }
                    for opt in acp_options
                ]
                if not options:
                    options = [
                        {
                            "option_id": "allow_once",
                            "name": "Allow",
                            "kind": PermissionOptionKind.ALLOW_ONCE,
                        },
                        {
                            "option_id": "deny_once",
                            "name": "Deny",
                            "kind": PermissionOptionKind.REJECT_ONCE,
                        },
                    ]

                await emitters.emit_permission_request(
                    thread_id=thread_id,
                    agent_id=task.name,
                    request_id=request_id,
                    description=f"Permission required: {tool_name}",
                    options=options,
                    tool_call=tool_name,
                )
                await emitters.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=task.name,
                    node_name=task.name,
                    state=AgentLifecycleState.INPUT_REQUIRED,
                    detail=f"Awaiting approval for {tool_name}",
                )
    return interrupt_detected
