"""Worker node for LangGraph agent task execution."""

import logging

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt

from ..anchoring import build_anchoring_context
from ..config import settings
from ..context import compact_context, should_compact
from ..exceptions import WorkerExecutionError
from ..rules import RuleManager
from ..state import TeamState
from ..task_queue import create_mark_task_complete_tool


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
        compact_context(state, settings.context_limit_tokens)
        if should_compact(state, settings.context_limit_tokens)
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
        "worker[%s] model=%s raised during ainvoke"
        " — wrapping as WorkerExecutionError",
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

    The graph executor replays the node on resume; on each replay, every
    ``interrupt()`` call returns its stored resume value in order.  Multiple
    permission requests within a single node turn are therefore handled
    correctly — each gets its own stored reply.

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
    # resume_value is whatever the client passed in Command(resume=...).
    # Accept a plain string (raw optionId) or a dict with an "option_id" key.
    # Validate against the known options to prevent unknown ids from reaching
    # the ACP subprocess.
    if isinstance(resume_value, str):
        return _validate_option_id(resume_value, options)
    if isinstance(resume_value, dict):
        candidate = resume_value.get("option_id", _first_option_id(options))
        return _validate_option_id(candidate, options)
    return _first_option_id(options)


def create_worker_node(
    model: BaseChatModel,
    system_prompt: str,
    name: str,
    autonomous: bool = False,
    workspace_root: Path | None = None,
    feature_tag: str | None = None,
) -> WorkerNode:
    """Create a LangGraph worker node with a specific role and model.

    If the provided model supports ACP permission handling (exposes a
    ``permission_callback`` attribute) and ``autonomous`` is False, the
    callback is wired to :func:`_interrupt_permission_callback` so that
    tool-approval requests from the ACP subprocess suspend the graph and
    wait for a human decision.  The graph stores its state in the
    checkpointer; on resume the node re-executes and each ``interrupt()``
    call returns its stored approval in order.

    When ``autonomous=True``, the callback is intentionally not wired.
    AcpChatModel's else-branch auto-approves with the first option, enabling
    headless MCP-launched runs to complete without human intervention.

    For models that do not have a ``permission_callback`` attribute (e.g.
    standard :class:`~langchain_core.language_models.ChatOpenAI`), the wiring
    step is skipped and the node behaves as a plain async LLM call.

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
    # ADR-021: create task queue drain if workspace_root and feature_tag are both set.
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
        compacted = should_compact(state, settings.context_limit_tokens)
        # In supervised mode: wire interrupt-based approval for ACP-backed models.
        # Use model_copy() to avoid mutating the shared model instance — the same
        # AcpChatModel may be reused across concurrent graph invocations, and
        # in-place mutation would cause permission_callback cross-contamination
        # (H4 fix).  model_copy() is a shallow copy that shares subprocess state
        # but isolates the callback reference on this invocation's copy.
        # In autonomous mode: leave permission_callback unwired; AcpChatModel's
        # else-branch auto-approves with the first option.
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
        except GraphBubbleUp:
            if drain_fn is not None:
                drain_fn()  # Prevent state update leaks (ADR-021 §5)
            raise  # Let GraphInterrupt/Command pass through to LangGraph untouched
        except Exception as exc:
            if drain_fn is not None:
                drain_fn()  # Prevent state update leaks (ADR-021 §5)
            raise _wrap_worker_exception(
                exc=exc,
                worker=name,
                model_type=model_type,
                message_count=len(messages),
            ) from exc

        # ADR-021: drain side-channel state updates (current_task_id advance, etc.)
        state_updates = _drain_worker_state_updates(drain_fn)

        _logger.debug("worker[%s] response len=%d", name, len(str(response.content)))
        return _finalize_worker_response(
            response=response,
            worker_name=name,
            state_updates=state_updates,
        )

    return worker_node
