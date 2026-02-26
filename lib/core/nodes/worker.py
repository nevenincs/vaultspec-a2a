from collections.abc import Callable, Coroutine
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from ..state import TeamState


def create_worker_node(
    model: BaseChatModel,
    system_prompt: str,
    name: str,
) -> Callable[[TeamState], Coroutine[Any, Any, dict[str, Any]]]:
    """Create a LangGraph worker node with a specific role and model.

    Args:
        model: The LangChain chat model to use for this node.
        system_prompt: The system prompt defining the worker's behavior.
        name: The name of the worker, added to the generated message.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """

    async def worker_node(state: TeamState) -> dict[str, Any]:
        """Execute the worker's task and return the generated message."""
        messages = [SystemMessage(content=system_prompt)] + list(state["messages"])
        response = await model.ainvoke(messages)
        # Attribute the message to the worker so the supervisor doesn't get confused
        response.name = name
        return {"messages": [response]}

    return worker_node
