"""Resolving the tool calls one worker turn makes that the node itself owns.

Two lanes reach here: the queue tool, whose ``Command`` carries a state patch
the node must return, and the mock provider's permission call, which has to be
gated from a runnable context the graph owns. Both are collected against the
same response before any follow-up turn, which is the invariant this module
exists to hold.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from ._worker_permissions import _permission_callback_for

if TYPE_CHECKING:
    from collections.abc import Mapping

    # Annotation-only: langchain_core.language_models is seconds-expensive at
    # import (it eagerly probes for transformers); this module receives already
    # constructed models and never instantiates one.
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import ToolCall
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import BaseTool

__all__: list[str] = []


async def _collect_queue_tool_results(
    *,
    response: BaseMessage,
    queue_tool: BaseTool | None,
) -> tuple[list[ToolMessage], dict[str, Any]]:
    """Dispatch mark_task_complete tool calls, collecting their Command update.

    The revised contract replaces the side-channel drain with a ``Command``-
    returning tool. This worker uses direct ``model.ainvoke`` rather than a
    ``ToolNode``, so it dispatches the bound queue tool itself: it inspects the
    model's emitted tool calls, runs the tool (which returns a ``Command``, and is
    required to -- a non-Command result is a contract violation and raises), and
    splits the Command's update into the ``ToolMessage`` results the model needs
    and the non-message state patch (``current_task_id``). ``worker_node`` returns
    that patch so it flows through the reducer pipeline -- never a closure-scoped
    list -- so no advance is silently lost when a turn interrupts.

    Every matching call in the response is dispatched and their patches merged.
    Returns empty results when no queue tool is bound or none were called.
    """
    if queue_tool is None or not isinstance(response, AIMessage):
        return [], {}
    queue_calls = [
        tool_call
        for tool_call in response.tool_calls
        if tool_call.get("name") == queue_tool.name
    ]
    if not queue_calls:
        return [], {}

    state_patch: dict[str, Any] = {}
    tool_messages: list[ToolMessage] = []
    for tool_call in queue_calls:
        command = await queue_tool.ainvoke(tool_call)
        _merge_queue_command(command, tool_messages, state_patch)

    return tool_messages, state_patch


def _merge_queue_command(
    command: object,
    tool_messages: list[ToolMessage],
    state_patch: dict[str, Any],
) -> None:
    """Validate and merge one queue tool Command into worker results."""
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


async def _collect_mock_permission_result(
    *,
    response: BaseMessage,
    model: BaseChatModel,
    autonomous: bool,
    answers: Mapping[str, str],
) -> list[ToolMessage]:
    """Resolve a mock-provider permission tool call inside the node context.

    This lane exists only for the mock chat model. A real ACP provider never
    reaches here: its permission callback is wired onto the model itself (see
    :func:`_resolve_effective_worker_model`), so the callback raises the
    interrupt from *inside* ``model.ainvoke`` and no response is produced at
    all. VidaiMock instead surfaces ``session_request_permission`` as an
    ordinary tool call, but the LangGraph interrupt must still be raised from a
    runnable context the graph owns -- so the gate is performed here, over the
    same answers the wired lane is bound to.

    Only the first permission call in a response is resolved; the interrupt
    suspends the turn, and the resumed turn re-presents any further calls.
    """
    if autonomous or getattr(model, "_llm_type", "") != "mock-chat-model":
        return []
    if not isinstance(response, AIMessage):
        return []

    for tool_call in response.tool_calls:
        if tool_call.get("name") != "session_request_permission":
            continue
        tool_input, options = _parse_mock_permission_call(tool_call)
        selected_option = await _permission_callback_for(answers)(
            "session_request_permission",
            tool_input,
            options,
        )
        tool_call_id = tool_call.get("id")
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise RuntimeError(
                "Mock permission gate requires a stable tool call id to resume"
            )
        return [
            ToolMessage(
                content=json.dumps({"approved_option_id": selected_option}),
                tool_call_id=tool_call_id,
            )
        ]

    return []


def _parse_mock_permission_call(
    tool_call: ToolCall,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extract the permissive input and option shape used by mock tool calls."""
    raw_tool_input = cast("object", tool_call.get("args", {}))
    tool_input = (
        cast("dict[str, Any]", raw_tool_input)
        if isinstance(raw_tool_input, dict)
        else {}
    )
    raw_options = cast("object", tool_input.get("options", []))
    options: list[dict[str, Any]] = (
        [
            cast("dict[str, Any]", option)
            for option in cast("list[object]", raw_options)
            if isinstance(option, dict)
        ]
        if isinstance(raw_options, list)
        else []
    )
    return tool_input, options


class _WorkerToolCallOptions(TypedDict):
    messages: list[BaseMessage]
    response: BaseMessage
    queue_tool: BaseTool | None
    model: BaseChatModel
    autonomous: bool
    config: RunnableConfig | None
    permission_answers: Mapping[str, str]


async def _resolve_worker_tool_calls(
    **options: Unpack[_WorkerToolCallOptions],
) -> tuple[BaseMessage, dict[str, Any]]:
    """Resolve every node-owned tool call in one response, in one follow-up turn.

    Both node-owned lanes -- the mock permission gate and the queue tool -- are
    collected against the *same* response before any follow-up invocation. That
    ordering is the point: resolving them in sequence meant whichever ran first
    replaced the response with a fresh model turn, and the other lane then
    inspected that replacement and never saw the original's calls. A turn emitting
    both a permission request and a queue-tool call therefore dropped one of them
    silently. Collecting first makes that loss unrepresentable.

    Returns ``(final_response, state_patch)``, passing the response through
    untouched with an empty patch when neither lane produced a result.
    """
    messages = options["messages"]
    response = options["response"]
    queue_tool = options["queue_tool"]
    model = options["model"]
    autonomous = options["autonomous"]
    config = options["config"]
    permission_results = await _collect_mock_permission_result(
        response=response,
        model=model,
        autonomous=autonomous,
        answers=options["permission_answers"],
    )
    queue_results, state_patch = await _collect_queue_tool_results(
        response=response, queue_tool=queue_tool
    )
    tool_messages = [*permission_results, *queue_results]
    if not tool_messages:
        return response, state_patch

    notes: list[str] = []
    if permission_results:
        notes.append("Human approval has been resolved.")
    if queue_results:
        notes.append("The task-queue update has been recorded.")
    follow_up_messages = [
        *messages,
        SystemMessage(
            content=(
                f"{' '.join(notes)} Continue the task using the tool result(s) below."
            )
        ),
        response,
        *tool_messages,
    ]
    # A queue mutation (mark_complete) is already durable at this point, but the
    # returned state_patch (the current_task_id advance) only reaches the reducer
    # if this node returns. If the follow-up ainvoke raises, worker_node wraps it
    # as WorkerExecutionError and the patch is dropped with the failed turn -- not
    # a durability bug: mark_complete is idempotent, so the retried turn replays it
    # to the same next task and re-derives the same patch. Ordering is intentional:
    # the model still needs the ToolMessages to produce its final response.
    final_response = await model.ainvoke(follow_up_messages, config=config)
    return final_response, state_patch
