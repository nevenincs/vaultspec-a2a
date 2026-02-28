"""Core state schema for LangGraph agent orchestration.

Every field must be JSON-serializable (primitives + dicts + lists only)
so the SQLite checkpointer can persist state without pickle errors
(ADR-002, ADR-008).
"""

from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


__all__ = ["TeamState"]


# ---------------------------------------------------------------------------
# Custom reducers
# ---------------------------------------------------------------------------


def _append_artifacts(
    existing: list[dict[str, str]],
    new: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Append-only reducer for artifacts (deduplicated by ``id``)."""
    seen = {a["id"] for a in existing}
    merged = list(existing)
    for item in new:
        if item["id"] not in seen:
            merged.append(item)
            seen.add(item["id"])
    return merged


def _merge_token_usage(
    existing: dict[str, dict[str, int]],
    new: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    """Additive merge reducer for per-agent token counters.

    Each node update supplies its *delta*; the reducer accumulates totals.
    """
    merged = {k: dict(v) for k, v in existing.items()}
    for agent_id, counters in new.items():
        if agent_id in merged:
            for key in ("input", "output", "total"):
                merged[agent_id][key] = merged[agent_id].get(key, 0) + counters.get(
                    key, 0
                )
        else:
            merged[agent_id] = dict(counters)
    return merged


def _replace_plan(
    existing: list[dict[str, str]],
    new: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Full-replacement reducer for the execution plan.

    The supervisor overwrites the entire plan on each planning cycle.
    """
    return new if new else existing


# ---------------------------------------------------------------------------
# State TypedDict
# ---------------------------------------------------------------------------


class TeamState(TypedDict):
    """Core state for LangGraph orchestration.

    All values are plain JSON-serializable types (no Pydantic models, no
    datetime objects) to satisfy the SQLite checkpointer constraint.
    """

    # --- existing fields ---
    messages: Annotated[list[BaseMessage], add_messages]
    next: str

    # --- plan: full-replacement on each supervisor cycle ---
    current_plan: Annotated[list[dict[str, str]], _replace_plan]

    # --- artifacts: append-only, deduplicated by id ---
    artifacts: Annotated[list[dict[str, str]], _append_artifacts]

    # --- routing / identification ---
    active_agent: str
    thread_id: str

    # --- token accounting: additive merge per agent ---
    token_usage: Annotated[dict[str, dict[str, int]], _merge_token_usage]

    # --- pipeline_loop iteration guard (ADR-013 §5) ---
    # Plain last-write-wins int, incremented by the _loop_node_with_counter wrapper
    # on each pass.  The _loop_router conditional edge enforces the max_loops cap:
    # when loop_count >= max_loops it returns "FINISH" regardless of state["next"].
    # Workers signal early loop exit by returning next="FINISH"; otherwise the loop
    # continues ("revise" is the default).
    # NotRequired because non-pipeline_loop teams never set this key.
    loop_count: NotRequired[int]
