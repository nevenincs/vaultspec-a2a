"""Database-backed worker task queue (ADR R5, amends ADR-021).

The task queue is orchestration state and now lives in A2A's own database
rather than a ``.vault/plan`` markdown table.  This module owns the graph-side
surface: rendering the injectable queue view as stable table text and the
mark-task-complete tool.  All persistence is reached through the injected
:class:`~vaultspec_a2a.graph.protocols.TaskQueuePort`; this module never
imports the database layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ..protocols import QueueEntryView, TaskQueuePort

__all__ = ["create_mark_task_complete_tool", "render_queue_view"]


def render_queue_view(
    feature_tag: str,
    entries: Sequence[QueueEntryView],
) -> str:
    """Render the injectable queue view as a stable markdown table.

    Produces the current task row plus the horizon of pending rows the port
    already selected, in the same table shape the markdown path injected so
    prompts and recorded tapes stay format-stable.  Returns an empty string
    when there are no entries to inject.
    """
    if not entries:
        return ""
    lines = [
        f"## Task Queue -- {feature_tag}",
        "",
        "| Task | Status | Description |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {entry.task_key} | {entry.status} | {entry.description} |"
        for entry in entries
    )
    return "\n".join(lines)


def create_mark_task_complete_tool(
    port: TaskQueuePort,
    thread_id: str,
) -> tuple[Callable, Callable]:
    """Factory returning (tool_fn, drain_fn) bound to a thread's queue.

    tool_fn: async tool passed to the LLM -- returns a string acknowledgement.
    drain_fn: called by worker_node after model.ainvoke() -- returns the
              accumulated ``TeamState`` patch dict and clears the pending list.

    The mark-complete transition is idempotent: completing an already-completed
    row is a no-op that reports the same next pending task, matching the
    engine's replay discipline.
    """
    pending_state_updates: list[dict[str, Any]] = []

    async def mark_task_complete(task_id: str) -> str:
        """Mark a task complete in the thread's database queue.

        Args:
            task_id: The stable task key to mark complete (e.g. 'SBI-003').

        Returns:
            A string acknowledgement for the LLM confirming completion and
            stating the next pending task key (or "no further tasks").
        """
        outcome = await port.mark_complete(thread_id, task_id)

        if not outcome.did_complete:
            return f"Task {task_id} not found or not in_progress."

        if outcome.next_task_key:
            next_key = outcome.next_task_key
            pending_state_updates.append({"current_task_id": next_key})
            return f"Task {task_id} marked complete. Next task: {next_key}."

        pending_state_updates.append({"current_task_id": None})
        return f"Task {task_id} marked complete. No further pending tasks."

    def drain_state_updates() -> dict[str, Any]:
        """Return accumulated state updates and clear the pending list."""
        merged: dict[str, Any] = {}
        for update in pending_state_updates:
            merged.update(update)
        pending_state_updates.clear()
        return merged

    return mark_task_complete, drain_state_updates
