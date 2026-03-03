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
    return new if new is not None else existing


def _merge_vault_index(
    existing: dict[str, list[str]],
    new: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Merge-and-deduplicate reducer for vault_index."""
    merged: dict[str, list[str]] = {k: list(v) for k, v in existing.items()}
    for doc_type, paths in new.items():
        seen = set(merged.get(doc_type, []))
        merged.setdefault(doc_type, [])
        for p in paths:
            if p not in seen:
                merged[doc_type].append(p)
                seen.add(p)
    return merged


def _append_validation_errors(
    existing: list[str],
    new: list[str],
) -> list[str]:
    """Append-only reducer. Empty new = clear signal."""
    if not new:
        return []
    return existing + new


# ---------------------------------------------------------------------------
# State TypedDict
# ---------------------------------------------------------------------------


class TeamState(TypedDict):
    """Core state for LangGraph orchestration.

    All values are plain JSON-serializable types (no Pydantic models, no
    datetime objects) to satisfy the SQLite checkpointer constraint.
    """

    # L5: keys sorted alphabetically for readability.
    # --- routing / identification ---
    active_agent: str

    # --- artifacts: append-only, deduplicated by id ---
    artifacts: Annotated[list[dict[str, str]], _append_artifacts]

    # --- plan: full-replacement on each supervisor cycle ---
    current_plan: Annotated[list[dict[str, str]], _replace_plan]

    # --- pipeline_loop iteration guard (ADR-013 §5) ---
    # Plain last-write-wins int, incremented by the _loop_node_with_counter wrapper
    # on each pass.  The _loop_router conditional edge enforces the max_loops cap:
    # when loop_count >= max_loops it returns "FINISH" regardless of state["next"].
    # Workers signal early loop exit by returning next="FINISH"; otherwise the loop
    # continues ("revise" is the default).
    # NotRequired because non-pipeline_loop teams never set this key.
    # M6: type is int (>= 0); negative values are prevented at write time by the
    # _loop_node_with_counter wrapper which only increments, never decrements.
    loop_count: NotRequired[int]

    # --- existing fields ---
    messages: Annotated[list[BaseMessage], add_messages]
    next: NotRequired[str]

    # --- SDD blackboard awareness (ADR-019) ---
    active_feature: NotRequired[str | None]
    pipeline_phase: NotRequired[str | None]
    vault_index: NotRequired[Annotated[dict[str, list[str]], _merge_vault_index]]
    validation_errors: NotRequired[Annotated[list[str], _append_validation_errors]]

    # --- transient: mounted .vault/ document content (ADR-020) ---
    # Populated by mount_node before worker invocation; cleared by worker_node after reading.
    # None when active_feature is unset, vault_index is empty, or workspace_root is None.
    mounted_context: NotRequired[str | None]

    # --- task queue pointer (ADR-021) ---
    # ID of the task currently assigned to the worker. None when no feature is active
    # or no task has been assigned. Updated via side-channel drain after mark_task_complete.
    current_task_id: NotRequired[str | None]

    # --- plan approval gate (ADR-024) ---
    # Set to True once the user approves the plan for execution.
    # NotRequired: absent on legacy threads — defaults to False (unapproved) at read time.
    plan_approved: NotRequired[bool]

    # --- routing error: set by supervisor on parse failure ---
    routing_error: NotRequired[str]

    # --- routing / identification ---
    thread_id: str

    # --- token accounting: additive merge per agent ---
    token_usage: Annotated[dict[str, dict[str, int]], _merge_token_usage]
