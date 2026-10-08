"""The graph's single durable producer of successful action completion."""

from __future__ import annotations

from ...thread.action_receipts import (
    ACTIVE_RECEIPT_CHANNEL,
    COMPLETION_RECEIPTS_CHANNEL,
    INCORPORATED_RECEIPTS_CHANNEL,
    GraphActionReceipt,
    GraphCompletionReceipt,
)
from ...thread.state import TeamState

GRAPH_COMPLETION_NODE = "_record_graph_completion"


async def record_graph_completion(state: TeamState) -> dict[str, object]:
    """Commit completion only for the explicitly active incorporated action.

    Async although it does no I/O: LangGraph enforces a node run budget only on
    async nodes, and the compiler gives every node one.
    """
    active = GraphActionReceipt.model_validate(state.get(ACTIVE_RECEIPT_CHANNEL))
    incorporated = state.get(INCORPORATED_RECEIPTS_CHANNEL, {}).get(active.dispatch_id)
    if incorporated != active.model_dump(mode="json"):
        raise ValueError("active graph action has no matching incorporation receipt")
    completion = GraphCompletionReceipt(
        schema_version="graph-completion-v1", action=active, outcome="completed"
    )
    return {
        COMPLETION_RECEIPTS_CHANNEL: {
            active.dispatch_id: completion.model_dump(mode="json")
        }
    }
