"""Worker node for LangGraph agent task execution."""

from collections.abc import Callable, Coroutine
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.types import interrupt

from ..context import compact_context, should_compact
from ..state import TeamState


# Conservative context limit that fits all supported models
# (Claude 200k, GPT-4 Turbo 128k, Gemini 1M). Compaction triggers at 80%
# (100k tokens) to leave headroom for the generation cycle.
_CONTEXT_LIMIT = 120_000


__all__ = ["create_worker_node"]


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
) -> Callable[[TeamState], Coroutine[Any, Any, dict[str, Any]]]:
    """Create a LangGraph worker node with a specific role and model.

    If the provided model supports ACP permission handling (exposes a
    ``permission_callback`` attribute), the callback is wired to
    :func:`_interrupt_permission_callback` so that tool-approval requests
    from the ACP subprocess suspend the graph and wait for a human decision.
    The graph stores its state in the checkpointer; on resume the node
    re-executes and each ``interrupt()`` call returns its stored approval in
    order.

    For models that do not have a ``permission_callback`` attribute (e.g.
    standard :class:`~langchain_core.language_models.ChatOpenAI`), the wiring
    step is skipped and the node behaves as a plain async LLM call.

    Args:
        model:         The LangChain chat model to use for this node.
        system_prompt: The system prompt defining the worker's behaviour.
        name:          The name of the worker, added to the generated message.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """

    async def worker_node(state: TeamState) -> dict[str, Any]:
        """Execute the worker's task and return the generated message."""
        # Compact the conversation history for this LLM call if it is
        # approaching the model's context limit. The full history is
        # preserved in the LangGraph checkpointer — compaction only affects
        # the messages passed to the model, not what is stored.
        working_state = (
            compact_context(state, _CONTEXT_LIMIT)
            if should_compact(state, _CONTEXT_LIMIT)
            else state
        )
        messages = [SystemMessage(content=system_prompt), *working_state["messages"]]
        # Wire interrupt-based permission approval for ACP-backed models.
        # Duck-typed: any model exposing permission_callback is supported.
        if hasattr(model, "permission_callback"):
            model.permission_callback = _interrupt_permission_callback  # type: ignore[attr-defined]
        response = await model.ainvoke(messages)
        # Attribute the message to the worker so the supervisor can route correctly.
        response.name = name
        return {"messages": [response]}

    return worker_node
