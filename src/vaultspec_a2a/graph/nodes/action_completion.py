"""The graph's single durable producer of successful action completion."""

from __future__ import annotations

from ...thread.action_receipts import GraphActionReceipt, GraphCompletionReceipt
from ...thread.state import TeamState  # noqa: TC001 - LangGraph inspects node input

GRAPH_COMPLETION_NODE = "_record_graph_completion"


def record_graph_completion(state: TeamState) -> dict[str, object]:
    """Commit completion only for the explicitly active incorporated action."""
    active = GraphActionReceipt.model_validate(state.get("active_graph_action_receipt"))
    incorporated = state.get("graph_action_receipts", {}).get(active.dispatch_id)
    if incorporated != active.model_dump(mode="json"):
        raise ValueError("active graph action has no matching incorporation receipt")
    completion = GraphCompletionReceipt(
        schema_version="graph-completion-v1", action=active, outcome="completed"
    )
    return {
        "graph_completion_receipts": {
            active.dispatch_id: completion.model_dump(mode="json")
        }
    }
