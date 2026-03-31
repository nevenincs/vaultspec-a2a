"""Worker node for LangGraph agent task execution."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt

from vaultspec_a2a.context.anchoring import build_anchoring_context
from vaultspec_a2a.context.rules import RuleManager
from vaultspec_a2a.context.token_budget import compact_context, should_compact
from vaultspec_a2a.domain_config import domain_config
from vaultspec_a2a.thread.errors import WorkerExecutionError
from vaultspec_a2a.thread.state import TeamState

from ..tools.task_queue import create_mark_task_complete_tool

_logger = logging.getLogger(__name__)


__all__ = ["create_worker_node"]


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
) -> list[BaseMessage]:
    """Build the worker prompt/message list before model invocation."""
    working_state = (
        compact_context(state, domain_config.context_limit_tokens)
        if should_compact(state, domain_config.context_limit_tokens)
        else state
    )
    anchoring = build_anchoring_context(state)
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    effective_workspace_root = workspace_root or state.get("workspace_root")
    if effective_workspace_root:
        rules = RuleManager(Path(effective_workspace_root)).compile()
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


def _drain_worker_state_updates(
    drain_fn: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    """Drain side-channel task updates if ADR-021 wiring is active."""
    return drain_fn() if drain_fn is not None else {}


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
    """Attach worker attribution and merge any side-channel state updates."""
    response.name = worker_name
    return {"messages": [response], "mounted_context": None, **state_updates}


def _first_option_id(options: list[dict[str, Any]]) -> str:
    """Extract the first optionId from ACP permission options list."""
    return options[0]["optionId"] if options else "allow_once"


def _validate_option_id(candidate: str, options: list[dict[str, Any]]) -> str:
    """Return *candidate* if it is a valid optionId, else the first option.

    Prevents a client sending an arbitrary string via ``Command(resume=...)``
    from bypassing permission options with an unrecognised id.
    """
    valid_ids = {opt["optionId"] for opt in options if "optionId" in opt}
    return candidate if candidate in valid_ids else _first_option_id(options)


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
    if isinstance(resume_value, str):
        return _validate_option_id(resume_value, options)
    if isinstance(resume_value, dict):
        candidate = resume_value.get("option_id", _first_option_id(options))
        return _validate_option_id(candidate, options)
    raise RuntimeError(
        "LangGraph interrupt returned an unsupported resume payload for "
        f"{tool_name!r}: {type(resume_value).__name__}"
    )


def create_worker_node(
    model: BaseChatModel,
    system_prompt: str,
    name: str,
    autonomous: bool = False,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
) -> WorkerNode:
    """Create a LangGraph worker node with a specific role and model.

    Args:
        model:          The LangChain chat model to use for this node.
        system_prompt:  The system prompt defining the worker's behaviour.
        name:           The name of the worker, added to the generated message.
        autonomous:     When True, skip permission_callback wiring (headless).
        workspace_root: Optional workspace root for task queue
                        file resolution (ADR-021).
        feature_tag:    Optional feature tag for task queue file resolution (ADR-021).

    Returns:
        An async function that conforms to the LangGraph node signature.
    """
    drain_fn: Any = None
    if workspace_root is not None and feature_tag is not None:
        _tool_fn, drain_fn = create_mark_task_complete_tool(workspace_root, feature_tag)

    async def worker_node(state: TeamState) -> dict[str, Any]:
        """Execute the worker's task and return the generated message."""
        messages = _build_worker_messages(
            state=state,
            system_prompt=system_prompt,
            workspace_root=workspace_root,
        )
        compacted = should_compact(state, domain_config.context_limit_tokens)
        effective_model = _resolve_effective_worker_model(
            model=model,
            autonomous=autonomous,
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
        except GraphBubbleUp:
            if drain_fn is not None:
                drain_fn()
            raise
        except Exception as exc:
            if drain_fn is not None:
                drain_fn()
            raise _wrap_worker_exception(
                exc=exc,
                worker=name,
                model_type=model_type,
                message_count=len(messages),
            ) from exc

        state_updates = _drain_worker_state_updates(drain_fn)

        _logger.debug("worker[%s] response len=%d", name, len(str(response.content)))
        return _finalize_worker_response(
            response=response,
            worker_name=name,
            state_updates=state_updates,
        )

    return worker_node
