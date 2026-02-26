from collections.abc import Callable, Coroutine
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from ..state import TeamState


def create_supervisor_node(
    model: BaseChatModel,
    system_prompt: str,
    workers: list[str],
) -> Callable[[TeamState], Coroutine[Any, Any, dict[str, Any]]]:
    """Create a LangGraph supervisor node for routing.

    Args:
        model: The LangChain chat model to use for this node.
        system_prompt: The system prompt defining the supervisor's behavior.
        workers: A list of available worker names to route to.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """
    options = workers + ["FINISH"]

    # Append routing instructions to ensure structured text output
    routing_instructions = (
        f"\n\nBased on the conversation, who should act next? "
        f"If the request is complete, select FINISH. "
        f"Respond EXACTLY with one of the following words: {', '.join(options)}."
    )
    full_prompt = system_prompt + routing_instructions

    async def supervisor_node(state: TeamState) -> dict[str, Any]:
        """Execute the supervisor's routing task."""
        messages = [SystemMessage(content=full_prompt)] + list(state["messages"])
        response = await model.ainvoke(messages)

        # Parse text safely to derive next route
        text = str(response.content).strip()
        next_route = "FINISH"

        # Exact match preferred, fallback to substring
        if text in options:
            next_route = text
        else:
            for option in options:
                if option.lower() in text.lower():
                    next_route = option
                    break

        return {"next": next_route}

    return supervisor_node
