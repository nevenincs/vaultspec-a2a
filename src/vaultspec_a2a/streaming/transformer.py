"""LangGraph event transformation — maps raw astream_events to domain events.

Contains the ``process_langgraph_event`` function and the interrupt detection
logic.  Extracted from the monolithic ``aggregator.py`` during the aggregator
decomposition.

These functions are *logically* stateless — they receive emitter/buffering
references to perform side effects but hold no state of their own.
"""

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Protocol, TypeGuard, cast
from uuid import uuid4

from ..domain_config import domain_config
from ..graph.acp_options import option_id_of
from ..graph.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    PermissionType,
    ToolCallStatus,
)
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..thread.clarification import CLARIFICATION_INTERRUPT_TYPE
from .buffering import BufferingManager
from .emitters import EventEmitters
from .sse_frames import enforce_progress_allowlist
from .types import (
    NODE_BOUNDARY_EVENTS,
    PASSTHROUGH_EVENTS,
    StreamableGraph,
    classify_tool_kind,
    resolve_acp_option_kind,
)

# Import GraphInterrupt for isinstance check vs string comparison.
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


def _artifact_label_from_tool_input(file_path: str) -> str:
    """Collapse a raw tool path to a display-safe filename label."""
    normalized = file_path.replace("\\", "/").rstrip("/")
    if not normalized:
        return "artifact"
    return PurePath(normalized).name or "artifact"


#: Recognised terminal/near-terminal item statuses this repo's own
#: ``ToolCallStatus`` already names. A provider action item's status
#: vocabulary is owned by that provider's own schema (e.g. the Codex
#: app-server's generated protocol), not enumerated here.
_KNOWN_ACTION_ITEM_STATUSES = frozenset({status.value for status in ToolCallStatus})


def _map_action_item_status(raw_status: object) -> ToolCallStatus:
    """Map a provider action item's status onto the closed ``ToolCallStatus`` set.

    A value this repo already recognises (``completed``, ``failed``,
    ``in_progress``, ``pending``) is honoured directly. Anything else -- a
    policy rejection, an abort, a spelling this lane has not been observed
    using yet -- is treated as FAILED rather than risking a silent COMPLETED
    on a call that did not succeed. That silent-success risk is the exact
    shape of F17: one of the 15 stuck-pending tool calls in the reference
    incident was a policy-rejected command the model narrated but the record
    never showed as anything but pending.
    """
    if isinstance(raw_status, str) and raw_status in _KNOWN_ACTION_ITEM_STATUSES:
        return ToolCallStatus(raw_status)
    return ToolCallStatus.FAILED


def _parse_action_detail(raw_args: object) -> dict[str, Any] | None:
    """Parse a tool-call chunk's ``args`` as a JSON object, or return ``None``.

    Two shapes reach here through the same field: a plain tool's raw input
    (ACP's initial registration, or a partial ``tool_call_chunk`` arg-delta -
    just the tool's own arguments, no ``status`` key) and Codex's one-shot
    completed-action report (``{"command", "status", "exit_code", ...}`` -
    see ``codex_chat_model._completed_action_chunk``). Both are returned as a
    parsed dict when parseable; the caller distinguishes them by the presence
    of ``status``. A non-JSON or non-object payload returns ``None`` rather
    than raising, since malformed args must not stop live tool-call
    registration.
    """
    if not isinstance(raw_args, str) or not raw_args:
        return None
    try:
        parsed = json.loads(raw_args)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _action_detail_projection(
    item_type: str, detail: dict[str, Any]
) -> tuple[list[dict[str, str | None]], list[dict[str, str | int | None]]]:
    """Project a Codex completed-action detail onto (content, locations).

    Each action item type carries different REQUIRED fields (see
    ``codex_chat_model._completed_action_chunk``, which reads only the
    schema-required fields per variant); this mirrors that per-type shape
    rather than guessing at a common one. ``fileChange`` is the only variant
    that names a location a frontend could jump to, so it is the only one
    that returns non-empty locations.
    """
    if item_type == "commandExecution":
        command = detail.get("command")
        exit_code = detail.get("exit_code")
        parts = [f"$ {command}"] if command else []
        if exit_code is not None:
            parts.append(f"(exit {exit_code})")
        text = "\n".join(parts)
        return ([{"content_type": "text", "text": text}] if text else []), []
    if item_type == "fileChange":
        changes = detail.get("changes")
        locations: list[dict[str, str | int | None]] = []
        if isinstance(changes, list):
            for change in changes:
                if isinstance(change, dict):
                    path = change.get("path")
                    if isinstance(path, str) and path:
                        locations.append({"path": path, "line": None})
        text = f"{len(locations)} file(s) changed" if locations else ""
        return ([{"content_type": "text", "text": text}] if text else []), locations
    if item_type == "mcpToolCall":
        server = detail.get("server")
        tool = detail.get("tool")
        text = f"{server}:{tool}" if server and tool else str(tool or server or "")
        return ([{"content_type": "text", "text": text}] if text else []), []
    return [], []


async def _emit_completed_action(
    thread_id: str,
    agent_id: str,
    tool_call_id: str,
    item_type: str,
    detail: dict[str, Any],
    emitters: EventEmitters,
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
    status = _map_action_item_status(detail.get("status"))
    content, locations = _action_detail_projection(item_type, detail)
    await emitters.emit_tool_call_start(
        thread_id=thread_id,
        agent_id=agent_id,
        tool_call_id=tool_call_id,
        title=item_type,
        kind=classify_tool_kind(item_type),
    )
    await emitters.emit_tool_call_update(
        thread_id=thread_id,
        agent_id=agent_id,
        tool_call_id=tool_call_id,
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
        detail = _parse_action_detail(tc.get("args"))
        if detail is not None and "status" in detail:
            # Codex's completed-action shape: a single self-contained
            # terminal report, not a plain registration.
            await _emit_completed_action(
                thread_id, effective_agent_id, tc_id, name, detail, emitters
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


async def _translate_chat_model_stream(
    event_data: dict[str, Any],
    thread_id: str,
    effective_agent_id: str,
    run_id: str,
    emitters: EventEmitters,
    buffering: BufferingManager,
) -> None:
    chunk = event_data.get("data", {}).get("chunk")
    if chunk is not None:
        await _translate_tool_call_chunks(
            chunk, thread_id, effective_agent_id, emitters
        )
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


async def _translate_chat_model_end(
    event_data: dict[str, Any],
    thread_id: str,
    effective_agent_id: str,
    run_id: str,
    emitters: EventEmitters,
    buffering: BufferingManager,
) -> None:
    await buffering.flush_chunk_buffer(thread_id)
    output = event_data.get("data", {}).get("output")
    finish_reason: str | None = None
    if output is not None:
        resp_meta = getattr(output, "response_metadata", None) or {}
        finish_reason = resp_meta.get("finish_reason") or resp_meta.get("stop_reason")
    if finish_reason:
        await emitters.emit_message_chunk(
            thread_id=thread_id,
            agent_id=effective_agent_id,
            content="",
            message_id=run_id,
            finish_reason=finish_reason,
        )


async def _translate_tool_start(
    event_data: dict[str, Any],
    thread_id: str,
    effective_agent_id: str,
    run_id: str,
    node: str | None,
    emitters: EventEmitters,
) -> None:
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


async def _translate_tool_end(
    event_data: dict[str, Any],
    thread_id: str,
    effective_agent_id: str,
    run_id: str,
    node: str | None,
    emitters: EventEmitters,
) -> None:
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


async def _translate_tool_error(
    event_data: dict[str, Any],
    thread_id: str,
    effective_agent_id: str,
    run_id: str,
    node: str | None,
    emitters: EventEmitters,
) -> None:
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
    event_kind: str,
    thread_id: str,
    effective_agent_id: str,
    node: str,
    emitters: EventEmitters,
) -> None:
    # The dispatcher only calls this under ``and node``, so node is never None
    # here - typed accordingly so the agent-status calls type-check.
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

    if event_kind == "on_chat_model_stream":
        await _translate_chat_model_stream(
            event_data, thread_id, effective_agent_id, run_id, emitters, buffering
        )
        return
    if event_kind == "on_chat_model_end":
        await _translate_chat_model_end(
            event_data, thread_id, effective_agent_id, run_id, emitters, buffering
        )
        return
    if event_kind == "on_tool_start":
        await _translate_tool_start(
            event_data, thread_id, effective_agent_id, run_id, node, emitters
        )
        return
    if event_kind == "on_tool_end":
        await _translate_tool_end(
            event_data, thread_id, effective_agent_id, run_id, node, emitters
        )
        return
    if event_kind == "on_tool_error":
        await _translate_tool_error(
            event_data, thread_id, effective_agent_id, run_id, node, emitters
        )
        return
    if event_kind == "on_custom_event":
        await _translate_custom_event(
            event_data, thread_id, effective_agent_id, run_id, emitters
        )
        return
    if event_kind in NODE_BOUNDARY_EVENTS and node:
        await _translate_node_boundary(
            event_data, event_kind, thread_id, effective_agent_id, node, emitters
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


@dataclass(frozen=True)
class _InterruptEmission:
    """One recognized graph interrupt, ready for its wire projection."""

    thread_id: str
    agent_id: str
    request_id: str
    interrupt_type: str
    payload: dict[str, Any]


class _InterruptTask(Protocol):
    """The task fields exposed by LangGraph state snapshots."""

    name: str
    interrupts: Sequence[object]


_INTERRUPT_TYPES = frozenset(
    {
        "permission_request",
        "plan_approval_request",
        "document_approval_request",
        CLARIFICATION_INTERRUPT_TYPE,
    }
)


async def emit_interrupt_events(
    thread_id: str,
    _agent_id: str,
    graph: StreamableGraph,
    config: dict[str, Any],
    emitters: EventEmitters,
) -> bool:
    """Inspect graph state after streaming and project every known interrupt."""
    state = await _read_graph_state(thread_id, graph, config)
    if state is None:
        return False

    tasks = _interrupted_tasks(state)
    if not tasks or not any(task.interrupts for task in tasks):
        return False

    for emission in _interrupt_emissions(thread_id, tasks):
        if emission.request_id not in emitters._pending_permissions:
            await _emit_interrupt(emission, emitters)
    return True


async def _read_graph_state(
    thread_id: str, graph: StreamableGraph, config: dict[str, Any]
) -> object | None:
    """Read the final graph state without letting a failed read change the run."""
    try:
        return await asyncio.wait_for(
            graph.aget_state(config), timeout=domain_config.aget_state_timeout_seconds
        )
    except TimeoutError:
        logger.warning(
            "Timed out inspecting state for interrupt detection on thread %s",
            thread_id,
        )
    except Exception:
        logger.exception(
            "Failed to inspect state for interrupt detection on thread %s",
            thread_id,
        )
    return None


def _interrupt_emissions(
    thread_id: str, tasks: Sequence[_InterruptTask]
) -> list[_InterruptEmission]:
    """Normalize recognized task interrupts while retaining their graph position."""
    emissions: list[_InterruptEmission] = []
    for task_index, task in enumerate(tasks):
        for interrupt_index, interrupt in enumerate(task.interrupts):
            payload = _interrupt_payload(interrupt)
            if payload is None:
                continue
            interrupt_type = payload.get("type")
            if interrupt_type not in _INTERRUPT_TYPES:
                continue
            emissions.append(
                _InterruptEmission(
                    thread_id=thread_id,
                    agent_id=task.name,
                    request_id=_request_id(
                        thread_id, task_index, interrupt_index, interrupt, payload
                    ),
                    interrupt_type=interrupt_type,
                    payload=payload,
                )
            )
    return emissions


def _interrupt_payload(interrupt: object) -> dict[str, Any] | None:
    """Return a LangGraph interrupt payload when it has the expected mapping shape."""
    payload: object = getattr(interrupt, "value", interrupt)
    return payload if _is_payload(payload) else None


def _interrupted_tasks(state: object) -> Sequence[_InterruptTask]:
    """Return the sequence of pending LangGraph tasks, if a snapshot supplies one."""
    tasks: object = getattr(state, "tasks", None)
    return tasks if _is_task_sequence(tasks) else ()


def _is_task_sequence(value: object) -> TypeGuard[Sequence[_InterruptTask]]:
    """Recognize the list/tuple task collection used by graph state snapshots."""
    return isinstance(value, list | tuple)


def _is_payload(value: object) -> TypeGuard[dict[str, Any]]:
    """Narrow an untrusted graph payload to the mapping shape we project."""
    return isinstance(value, dict)


def _request_id(
    thread_id: str,
    task_index: int,
    interrupt_index: int,
    interrupt: object,
    payload: dict[str, Any],
) -> str:
    """Resolve the durable request identity in the established precedence order."""
    return str(
        payload.get("request_id")
        or getattr(interrupt, "id", None)
        or f"{thread_id}:task{task_index}:int{interrupt_index}"
    )


async def _emit_interrupt(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Route one recognized interrupt to its explicit projection branch."""
    if emission.interrupt_type == CLARIFICATION_INTERRUPT_TYPE:
        await _emit_clarification(emission, emitters)
    elif emission.interrupt_type == "plan_approval_request":
        await _emit_plan_approval(emission, emitters)
    elif emission.interrupt_type == "document_approval_request":
        await _emit_document_approval(emission, emitters)
    else:
        await _emit_tool_permission(emission, emitters)


async def _emit_clarification(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Emit only a nudge: question material belongs to the durable snapshot."""
    await emitters.emit_clarification_pending(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        request_id=emission.request_id,
    )
    await _emit_input_required(
        emission,
        emitters,
        "Awaiting an answer to a clarifying question",
    )


async def _emit_plan_approval(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Project a plan approval interrupt into its durable permission frame."""
    feature = _payload_text(emission.payload, "feature", "unknown")
    raw_plan_paths: object = emission.payload.get("plan_paths")
    plan_paths = raw_plan_paths if _is_object_list(raw_plan_paths) else []
    exec_worker = _payload_text(emission.payload, "exec_worker", "unknown")
    plan_summary = (
        f"{len(plan_paths)} plan document(s)" if plan_paths else "no plan documents"
    )
    await _emit_approval_request(
        emission,
        emitters,
        (
            f"Approve plan for feature '{feature}' before routing to {exec_worker} "
            f"({plan_summary})"
        ),
        _approval_options("Plan"),
        f"Awaiting plan approval for feature '{feature}'",
    )


async def _emit_document_approval(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Project a document approval interrupt into its durable permission frame."""
    phase = _payload_text(emission.payload, "phase", "document")
    feature = _payload_text(emission.payload, "feature", "unknown")
    await _emit_approval_request(
        emission,
        emitters,
        f"Approve the {phase} document for feature '{feature}' before the run proceeds",
        _approval_options("Document"),
        f"Awaiting {phase} document approval for feature '{feature}'",
    )


async def _emit_approval_request(
    emission: _InterruptEmission,
    emitters: EventEmitters,
    description: str,
    options: list[dict[str, Any]],
    status_detail: str,
) -> None:
    """Emit one approval request and its matching input-required status."""
    await emitters.emit_permission_request(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        request_id=emission.request_id,
        description=description,
        options=options,
        tool_call=PermissionType.PLAN_APPROVAL,
    )
    await _emit_input_required(emission, emitters, status_detail)


def _approval_options(subject: str) -> list[dict[str, Any]]:
    """Return the stable approve/reject pair for a plan or document decision."""
    return [
        {
            "option_id": "approve",
            "name": f"Approve {subject}",
            "kind": PermissionOptionKind.ALLOW_ONCE,
        },
        {
            "option_id": "reject",
            "name": f"Reject — Revise {subject}",
            "kind": PermissionOptionKind.REJECT_ONCE,
        },
    ]


async def _emit_tool_permission(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Project a provider tool permission while retaining its declared option kinds."""
    tool_name = _payload_text(emission.payload, "tool_name", "unknown")
    await emitters.emit_permission_request(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        request_id=emission.request_id,
        description=f"Permission required: {tool_name}",
        options=_permission_options(emission.payload.get("options", [])),
        tool_call=tool_name,
    )
    await _emit_input_required(emission, emitters, f"Awaiting approval for {tool_name}")


def _permission_options(raw_options: object) -> list[dict[str, Any]]:
    """Normalize ACP option identities and honor valid declared permission kinds."""
    options: list[dict[str, Any]] = []
    if _is_object_list(raw_options):
        for option in raw_options:
            options.append(_permission_option(option))
    return options or _default_permission_options()


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Narrow a provider option collection to an iterable list of raw entries."""
    return isinstance(value, list)


def _permission_option(option: object) -> dict[str, Any]:
    """Project one ACP option, deriving a kind only for an invalid declaration."""
    fields: dict[str, Any] = option if _is_payload(option) else {}
    option_id = option_id_of(option)
    declared_kind = fields.get("kind")
    kind = resolve_acp_option_kind(declared_kind, option_id or "")
    if declared_kind and kind != declared_kind:
        logger.warning(
            "Permission option %r declared unrecognised kind %r; "
            "derived %s from the option id instead",
            option_id,
            declared_kind,
            kind.value,
        )
    return {
        "option_id": option_id or "allow_once",
        "name": fields.get("label", fields.get("name", option_id or "Allow")),
        "kind": kind,
    }


def _default_permission_options() -> list[dict[str, Any]]:
    """Keep an omitted provider option list answerable."""
    return [
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


def _payload_text(payload: dict[str, Any], key: str, default: str) -> str:
    """Read a text payload field without forwarding a malformed value to emitters."""
    value: object = payload.get(key)
    return value if isinstance(value, str) and value else default


async def _emit_input_required(
    emission: _InterruptEmission, emitters: EventEmitters, detail: str
) -> None:
    """Record that the task is parked until a human provides an answer."""
    await emitters.emit_agent_status(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        node_name=emission.agent_id,
        state=AgentLifecycleState.INPUT_REQUIRED,
        detail=detail,
    )
