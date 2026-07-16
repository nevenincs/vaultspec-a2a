"""Worker node for LangGraph agent task execution."""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command, interrupt

from vaultspec_a2a.authoring.contract import is_document_authoring_role
from vaultspec_a2a.context.anchoring import build_anchoring_context
from vaultspec_a2a.context.rules import DEFAULT_BUNDLED_RULES_DIR, RuleManager
from vaultspec_a2a.context.token_budget import compact_context, should_compact
from vaultspec_a2a.domain_config import domain_config
from vaultspec_a2a.thread.errors import WorkerExecutionError
from vaultspec_a2a.thread.state import TeamState

from ..protocols import TaskQueuePort
from ..tools.task_queue import create_mark_task_complete_tool

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from vaultspec_a2a.providers._acp_authoring import AuthoringToolBinding

_logger = logging.getLogger(__name__)


__all__ = ["create_worker_node"]

# The research_adr document-authoring roles are role-SCOPED: they receive only the
# document-authoring conventions opted in to their role (via the authoring
# contract), not the whole corpus (graph-agent-framework-harness P02). Every other
# role (coders, etc.) passes role=None and keeps the unchanged whole-corpus-plus-
# bundled behavior, so scoping never strips a coder's rules.


class WorkerNode(Protocol):
    """Protocol for the worker node callable with __name__ attribute."""

    __name__: str

    async def __call__(self, state: TeamState) -> dict[str, Any]:
        """Execute the worker's task."""
        ...


def _build_worker_messages(
    *,
    state: TeamState,
    system_prompt: str,
    workspace_root: Path | None,
    role: str | None = None,
) -> list[BaseMessage]:
    """Build the worker prompt/message list before model invocation.

    A document-authoring *role* is scoped to its own bundled conventions; every
    other role (coders, etc.) compiles the whole WORKSPACE corpus (role=None) and
    does NOT receive the bundled defaults - the bundled dir is gated on document
    roles, so the ``roles:``-tagged conventions never leak into a coder turn
    (compile(None) disables the role filter, which would otherwise re-admit them -
    reviewer HIGH-1). A coder's own workspace rules are never stripped (P02/P04).
    """
    working_state = (
        compact_context(state, domain_config.context_limit_tokens)
        if should_compact(state, domain_config.context_limit_tokens)
        else state
    )
    anchoring = build_anchoring_context(state)
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    effective_workspace_root = workspace_root or state.get("workspace_root")
    if effective_workspace_root:
        is_document_role = is_document_authoring_role(role)
        compile_role = role if is_document_role else None
        bundled_dir = DEFAULT_BUNDLED_RULES_DIR if is_document_role else None
        rules = RuleManager(
            Path(effective_workspace_root),
            bundled_rules_dir=bundled_dir,
        ).compile(compile_role)
        if rules:
            messages.append(
                SystemMessage(
                    content=f"## Project Coding Rules & Guidelines\n\n{rules}"
                )
            )
    if anchoring:
        messages.append(SystemMessage(content=anchoring))
    mounted = state.get("mounted_context")
    if mounted:
        messages.append(SystemMessage(content=mounted))
    messages.extend(working_state["messages"])
    routing_error = state.get("routing_error")
    if (
        state.get("approval_status") == "rejected"
        and isinstance(routing_error, str)
        and "Plan rejected by user" in routing_error
    ):
        messages.append(
            SystemMessage(
                content=(
                    "Plan rejected by user — revise the implementation plan "
                    "before requesting privileged execution again."
                )
            )
        )
    return messages


def _resolve_effective_worker_model(
    *,
    model: BaseChatModel,
    autonomous: bool,
) -> BaseChatModel:
    """Return the invocation model after supervised permission wiring logic."""
    if autonomous or not hasattr(model, "permission_callback"):
        return model
    return model.model_copy(
        update={"permission_callback": _interrupt_permission_callback}
    )


def _attach_authoring_tools(
    model: BaseChatModel,
    binding: "AuthoringToolBinding | None",
    *,
    autonomous: bool,
) -> BaseChatModel:
    """Surface the run's bridged authoring tools to an ACP session model (R4).

    When a binding is present and the model exposes an ACP ``mcp_servers``
    surface, return a copy whose ``session/new`` advertises the run's authoring
    MCP server so the spawned CLI sees the propose/read tools. The transport is
    chosen from the binding: the stdio bridge (spawned subprocess) is preferred
    because the pinned CLI surfaces stdio MCP tools reliably while it connects to
    but does not surface loopback HTTP MCP tools; the HTTP bridge is used when
    the binding carries only that transport (ADR R4 amendment). Models without an
    MCP surface (mock, hosted APIs) are returned unchanged. The binding lives
    only in this worker closure — never in graph state or a checkpoint (R7).

    In autonomous (headless) mode ONLY, the exact bridged tool names are
    auto-permitted so the CLI can invoke them without a local prompt — a
    recorded approval policy, never a wildcard, and never for human-in-loop
    runs, which keep their prompts. The real human gate stays the engine review
    lane; the .vault deny policy still blocks fs writes.
    """
    if binding is None:
        return model
    attach = getattr(model, "with_mcp_servers", None)
    if attach is None:
        return model
    from vaultspec_a2a.providers._acp_authoring import (
        authoring_allowed_tool_names,
        build_authoring_mcp_servers,
        build_authoring_stdio_mcp_servers,
    )

    allowed_tools = authoring_allowed_tool_names(binding) if autonomous else None
    if binding.engine_base_url is not None and binding.run_id is not None:
        mcp_servers = build_authoring_stdio_mcp_servers(binding)
    else:
        mcp_servers = build_authoring_mcp_servers(binding)
    return attach(mcp_servers, allowed_tools)


def _wrap_worker_exception(
    *,
    exc: Exception,
    worker: str,
    model_type: str,
    message_count: int,
) -> WorkerExecutionError:
    """Convert a non-interrupt worker failure into WorkerExecutionError."""
    _logger.exception(
        "worker[%s] model=%s raised during ainvoke — wrapping as WorkerExecutionError",
        worker,
        model_type,
        exc_info=exc,
    )
    return WorkerExecutionError(
        worker=worker,
        model=model_type,
        message_count=message_count,
    )


async def _apply_queue_tool_calls(
    *,
    messages: list[BaseMessage],
    response: BaseMessage,
    queue_tool: "BaseTool | None",
    model: BaseChatModel,
) -> tuple[BaseMessage, dict[str, Any]]:
    """Dispatch mark_task_complete tool calls, propagating their Command update.

    ADR-021 (revised) replaces the side-channel drain with a ``Command``-
    returning tool. This worker uses direct ``model.ainvoke`` rather than a
    ``ToolNode``, so it dispatches the queue tool the same way the permission
    gate handles ``session_request_permission``: it inspects the model's emitted
    tool calls, runs the tool (which returns a ``Command``), threads each
    ``ToolMessage`` back for a follow-up model turn, and surfaces the Command's
    non-message update (``current_task_id``). ``worker_node`` returns that patch
    so it flows through the reducer pipeline -- never a closure-scoped list -- so
    no advance is silently lost when a turn interrupts.

    Returns ``(final_response, state_patch)``. When no queue tool is bound or the
    model emitted no queue calls, the response passes through with an empty patch.
    A single dispatch round is performed; a follow-up turn that emits further
    queue calls advances them on the next worker invocation.
    """
    if queue_tool is None or not isinstance(response, AIMessage):
        return response, {}
    queue_calls = [
        tool_call
        for tool_call in response.tool_calls
        if tool_call.get("name") == queue_tool.name
    ]
    if not queue_calls:
        return response, {}

    state_patch: dict[str, Any] = {}
    tool_messages: list[ToolMessage] = []
    for tool_call in queue_calls:
        command = await queue_tool.ainvoke(tool_call)
        if not isinstance(command, Command):
            raise RuntimeError(
                "mark_task_complete must return a Command(update=...); got "
                f"{type(command).__name__}"
            )
        update = cast("dict[str, Any]", command.update or {})
        for message in update.get("messages", []):
            if isinstance(message, ToolMessage):
                tool_messages.append(message)
        for key, value in update.items():
            if key != "messages":
                state_patch[key] = value

    follow_up_messages = [
        *messages,
        SystemMessage(
            content=(
                "The task-queue update has been recorded. Continue the task using "
                "the tool result below."
            )
        ),
        response,
        *tool_messages,
    ]
    # The queue mutation (mark_complete) is already durable at this point, but the
    # returned state_patch (the current_task_id advance) only reaches the reducer
    # if this node returns. If the follow-up ainvoke raises, worker_node wraps it
    # as WorkerExecutionError and the patch is dropped with the failed turn -- not
    # a durability bug: mark_complete is idempotent, so the retried turn replays it
    # to the same next task and re-derives the same patch. Ordering is intentional:
    # the model still needs the ToolMessage to produce its final response.
    final_response = await model.ainvoke(follow_up_messages)
    return final_response, state_patch


async def _apply_mock_permission_gate(
    *,
    messages: list[BaseMessage],
    response: BaseMessage,
    model: BaseChatModel,
    autonomous: bool,
) -> BaseMessage:
    """Gate mock-provider permission tool calls inside the graph node context.

    VidaiMock can deterministically replay permission tool calls, but the
    LangGraph interrupt must still be raised from a runnable context the graph
    owns. The mock provider therefore surfaces the tool call normally and the
    worker node performs the actual interrupt/resume gate here.
    """
    if autonomous or getattr(model, "_llm_type", "") != "mock-chat-model":
        return response
    if not isinstance(response, AIMessage):
        return response

    for tool_call in response.tool_calls:
        if tool_call.get("name") != "session_request_permission":
            continue
        tool_input = tool_call.get("args", {})
        if not isinstance(tool_input, dict):
            tool_input = {}
        options = tool_input.get("options", [])
        if not isinstance(options, list):
            options = []
        selected_option = await _interrupt_permission_callback(
            "session_request_permission",
            tool_input,
            options,
        )
        tool_call_id = tool_call.get("id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise RuntimeError(
                "Mock permission gate requires a stable tool call id to resume"
            )

        follow_up_messages = [
            *messages,
            SystemMessage(
                content=(
                    "Human approval has been resolved. Continue the task using "
                    "the tool result below."
                )
            ),
            response,
            ToolMessage(
                content=json.dumps({"approved_option_id": selected_option}),
                tool_call_id=tool_call_id,
            ),
        ]
        return await model.ainvoke(follow_up_messages)

    return response


def _finalize_worker_response(
    *,
    response: BaseMessage,
    worker_name: str,
    state_updates: dict[str, Any],
) -> dict[str, Any]:
    """Attach worker attribution and merge the queue tool's Command update.

    ``state_updates`` carries the non-message keys (e.g. ``current_task_id``)
    from any ``mark_task_complete`` Command dispatched this turn; they flow
    through the reducer pipeline via this node return.
    """
    response.name = worker_name
    return {
        "messages": [response],
        "mounted_context": None,
        # Approval outcomes are consumed by the worker turn they routed.
        "approval_status": None,
        "approval_request_id": None,
        **state_updates,
    }


def _valid_option_ids(options: list[dict[str, Any]]) -> set[str]:
    """Return the valid ACP permission option ids for resume validation."""
    return {
        option_id
        for option in options
        if isinstance(option, dict)
        and isinstance((option_id := option.get("optionId")), str)
        and option_id
    }


def _require_valid_option_id(candidate: object, options: list[dict[str, Any]]) -> str:
    """Validate a resumed option id and fail closed on malformed input."""
    valid_ids = _valid_option_ids(options)
    if not valid_ids:
        raise RuntimeError("Permission resume received no valid option ids")
    if not isinstance(candidate, str) or not candidate:
        raise RuntimeError(
            "Permission resume payload must include a non-empty option_id string"
        )
    if candidate not in valid_ids:
        raise RuntimeError(
            f"Permission resume payload specified unknown option_id {candidate!r}"
        )
    return candidate


def _resolve_resume_option_id(
    resume_value: object,
    options: list[dict[str, Any]],
) -> str:
    """Resolve the resumed option id from a LangGraph interrupt payload."""
    if isinstance(resume_value, str):
        return _require_valid_option_id(resume_value, options)
    if isinstance(resume_value, dict):
        payload = cast("dict[str, object]", resume_value)
        candidate = payload.get("option_id")
        if candidate is None:
            candidate = payload.get("optionId")
        return _require_valid_option_id(
            candidate,
            options,
        )
    raise RuntimeError(
        "LangGraph interrupt returned an unsupported resume payload type: "
        f"{type(resume_value).__name__}"
    )


async def _interrupt_permission_callback(
    tool_name: str,
    tool_input: dict[str, Any],
    options: list[dict[str, Any]],
) -> str:
    """Request human approval for an ACP tool call via LangGraph interrupt.

    On first invocation within a node: raises ``GraphInterrupt``, suspending
    the graph to the checkpointer and surfacing the permission request to the
    client.  On resume (via ``Command(resume=...)``): returns the human's
    chosen ``option_id`` without raising.

    Args:
        tool_name:  Human-readable name of the tool requesting permission.
        tool_input: Input parameters the tool was called with.
        options:    Available permission options from the ACP agent.  Each
                    dict contains at least ``optionId`` and a label.

    Returns:
        The chosen ``optionId`` string to send back to the ACP agent.
    """
    resume_value = interrupt(
        {
            "type": "permission_request",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "options": options,
        }
    )
    try:
        return _resolve_resume_option_id(resume_value, options)
    except RuntimeError as exc:
        raise RuntimeError(
            "LangGraph interrupt returned an invalid resume payload for "
            f"{tool_name!r}: {exc}"
        ) from exc


def create_worker_node(
    model: BaseChatModel,
    system_prompt: str,
    name: str,
    autonomous: bool = False,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
    authoring_binding: "AuthoringToolBinding | None" = None,
    role: str | None = None,
) -> WorkerNode:
    """Create a LangGraph worker node with a specific role and model.

    Args:
        model:             The LangChain chat model to use for this node.
        system_prompt:     The system prompt defining the worker's behaviour.
        name:              The name of the worker, added to the generated message.
        autonomous:        When True, skip permission_callback wiring (headless).
        workspace_root:    Optional workspace root for RuleManager scoping.
        feature_tag:       Optional feature tag gating task-queue wiring (ADR R5).
        task_queue_port:   Optional database-backed queue port; when present the
                           mark-task-complete tool is bound per invocation to the
                           running thread (ADR R5).
        authoring_binding: Optional per-run binding of the engine's bridged
                           authoring tools; when present and the model exposes an
                           ACP MCP surface, the spawned CLI session advertises the
                           loopback authoring MCP server so the agent sees the
                           propose/read tools and no vault-write path (ADR R4).

    Returns:
        An async function that conforms to the LangGraph node signature.
    """

    async def worker_node(state: TeamState) -> dict[str, Any]:
        """Execute the worker's task and return the generated message."""
        # ADR R5: the task queue is thread-scoped, so build the mark-complete
        # tool per invocation using the thread_id carried in graph state — the
        # compiled graph is shared across threads and cannot close over it. The
        # tool returns a Command (ADR-021 revised); its update is propagated
        # through this node's return, not a side-channel drain.
        queue_tool: BaseTool | None = None
        if task_queue_port is not None and feature_tag is not None:
            thread_id = state.get("thread_id")
            if thread_id:
                queue_tool = create_mark_task_complete_tool(task_queue_port, thread_id)

        messages = _build_worker_messages(
            state=state,
            system_prompt=system_prompt,
            workspace_root=workspace_root,
            role=role,
        )
        compacted = should_compact(state, domain_config.context_limit_tokens)
        effective_model = _resolve_effective_worker_model(
            model=model,
            autonomous=autonomous,
        )
        effective_model = _attach_authoring_tools(
            effective_model, authoring_binding, autonomous=autonomous
        )

        model_type = type(effective_model).__name__
        _logger.debug(
            "worker[%s] invoking model=%s messages=%d compacted=%s autonomous=%s",
            name,
            model_type,
            len(messages),
            compacted,
            autonomous,
        )
        try:
            response = await effective_model.ainvoke(messages)
            response = await _apply_mock_permission_gate(
                messages=messages,
                response=response,
                model=effective_model,
                autonomous=autonomous,
            )
            response, state_updates = await _apply_queue_tool_calls(
                messages=messages,
                response=response,
                queue_tool=queue_tool,
                model=effective_model,
            )
        except GraphBubbleUp:
            raise
        except Exception as exc:
            raise _wrap_worker_exception(
                exc=exc,
                worker=name,
                model_type=model_type,
                message_count=len(messages),
            ) from exc

        _logger.debug("worker[%s] response len=%d", name, len(str(response.content)))
        return _finalize_worker_response(
            response=response,
            worker_name=name,
            state_updates=state_updates,
        )

    return worker_node
