"""Resolving the tool calls one worker turn makes that the node itself owns.

One lane reaches here: the mock provider's permission call, which has to be
gated from a runnable context the graph owns.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from ._worker_permissions import permission_callback_for

if TYPE_CHECKING:
    from collections.abc import Mapping

    # Annotation-only: langchain_core.language_models is seconds-expensive at
    # import (it eagerly probes for transformers); this module receives already
    # constructed models and never instantiates one.
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import ToolCall
    from langchain_core.runnables import RunnableConfig

__all__ = [
    "resolve_worker_tool_calls",
]


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
    :func:`resolve_effective_worker_model`), so the callback raises the
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
        selected_option = await permission_callback_for(answers)(
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
    model: BaseChatModel
    autonomous: bool
    config: RunnableConfig | None
    permission_answers: Mapping[str, str]


async def resolve_worker_tool_calls(
    **options: Unpack[_WorkerToolCallOptions],
) -> BaseMessage:
    """Resolve the node-owned tool call in one response, in one follow-up turn.

    Returns the follow-up turn's response, or the response untouched when the
    mock permission lane produced no result.
    """
    messages = options["messages"]
    response = options["response"]
    model = options["model"]
    permission_results = await _collect_mock_permission_result(
        response=response,
        model=model,
        autonomous=options["autonomous"],
        answers=options["permission_answers"],
    )
    if not permission_results:
        return response

    follow_up_messages = [
        *messages,
        SystemMessage(
            content=(
                "Human approval has been resolved. "
                "Continue the task using the tool result(s) below."
            )
        ),
        response,
        *permission_results,
    ]
    return await model.ainvoke(follow_up_messages, config=options["config"])
