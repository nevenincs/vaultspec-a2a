"""Supervisor node for LangGraph agent routing."""

import logging
from typing import Any, Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.constants import TAG_NOSTREAM

from ..anchoring import build_anchoring_context
from ..context import CONTEXT_LIMIT, compact_context, should_compact
from ..phase import infer_phase_from_vault_index
from ..state import TeamState

_logger = logging.getLogger(__name__)


__all__ = ["create_supervisor_node"]


class SupervisorNode(Protocol):
    """Protocol for the supervisor node callable with __name__ attribute."""

    __name__: str

    async def __call__(self, state: TeamState) -> dict[str, Any]:
        """Execute the supervisor's routing task."""
        ...


def create_supervisor_node(
    model: BaseChatModel,
    system_prompt: str,
    workers: list[str],
) -> SupervisorNode:
    """Create a LangGraph supervisor node for routing.

    Args:
        model: The LangChain chat model to use for this node.
        system_prompt: The system prompt defining the supervisor's behavior.
        workers: A list of available worker names to route to.

    Returns:
        An async function that conforms to the LangGraph node signature.
    """
    options = [*workers, "FINISH"]

    # Append routing instructions to ensure structured text output
    routing_instructions = (
        f"\n\nBased on the conversation, who should act next? "
        f"If the request is complete, select FINISH. "
        f"Respond EXACTLY with one of the following words: {', '.join(options)}."
    )
    full_prompt = system_prompt + routing_instructions

    async def supervisor_node(state: TeamState) -> dict[str, Any]:
        """Execute the supervisor's routing task."""
        vault_index: dict[str, list[str]] = state.get("vault_index") or {}
        inferred_phase = infer_phase_from_vault_index(vault_index)

        working_state = (
            compact_context(state, CONTEXT_LIMIT)
            if should_compact(state, CONTEXT_LIMIT)
            else state
        )
        anchoring = build_anchoring_context(state)
        messages: list[BaseMessage] = [SystemMessage(content=full_prompt)]
        if anchoring:
            messages.append(SystemMessage(content=anchoring))
        messages.extend(working_state.get("messages", []))
        model_type = type(model).__name__
        _logger.debug(
            "supervisor invoking model=%s messages=%d options=%s",
            model_type,
            len(messages),
            options,
        )
        routing_model = model.with_config({"tags": [TAG_NOSTREAM]})
        try:
            response = await routing_model.ainvoke(messages)
        except Exception:
            _logger.exception(
                "supervisor model=%s raised during ainvoke — propagating to LangGraph",
                model_type,
            )
            raise

        # Parse text safely to derive next route
        text = str(response.content).strip()
        next_route = "FINISH"

        # Exact match preferred, fallback to substring
        if text in options:
            next_route = text
        else:
            for option in sorted(options, key=len, reverse=True):
                if option.lower() in text.lower():
                    next_route = option
                    break

        unparseable = next_route == "FINISH" and text not in options and not any(
            opt.lower() in text.lower() for opt in options
        )
        if unparseable:
            _logger.warning(
                "supervisor could not parse route from response %r — defaulting to FINISH",
                text[:120],
            )
            return {
                "next": "FINISH",
                "pipeline_phase": inferred_phase,
                "routing_error": f"supervisor could not parse route from: {text!r}",
            }

        if next_route == "FINISH":
            errors: list[str] = state.get("validation_errors") or []
            if errors:
                _logger.warning(
                    "supervisor blocked FINISH: %d validation error(s) active — "
                    "rerouting to first available worker",
                    len(errors),
                )
                next_route = workers[0] if workers else "FINISH"
                return {
                    "next": next_route,
                    "pipeline_phase": inferred_phase,
                    "routing_error": (
                        f"FINISH blocked: {len(errors)} validation error(s) must be resolved first."
                    ),
                }

        _logger.debug("supervisor routed to %r (raw=%r)", next_route, text[:80])
        return {"next": next_route, "pipeline_phase": inferred_phase}

    # Ensure __name__ is available for type checkers
    supervisor_node.__name__ = "supervisor_node"
    return supervisor_node
