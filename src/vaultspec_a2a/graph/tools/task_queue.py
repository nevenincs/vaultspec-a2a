"""Database-backed worker task queue (ADR R5, amends ADR-021).

The task queue is orchestration state and now lives in A2A's own database
rather than a ``.vault/plan`` markdown table.  This module owns the graph-side
surface: rendering the injectable queue view as stable table text and the
mark-task-complete tool.  All persistence is reached through the injected
:class:`~vaultspec_a2a.graph.protocols.TaskQueuePort`; this module never
imports the database layer.

The mark-complete tool follows the ADR-021 *revised* contract: a single
``@tool``-decorated coroutine returning ``Command(update=...)``.  The update
carries the ``current_task_id`` advance and a ``ToolMessage`` keyed by the
injected ``tool_call_id`` so the reducer pipeline applies it and message history
stays valid.  The rejected ``(tool_fn, drain_fn)`` side-channel is gone: state
now rides the graph's own return path rather than a closure-scoped list, so no
update is lost when a turn interrupts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.tools import BaseTool

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
) -> BaseTool:
    """Factory returning the ``@tool`` mark-complete coroutine for a thread.

    The returned tool is bound to ``thread_id`` and reaches persistence through
    the injected ``port``.  It returns ``Command(update=...)`` so LangGraph's
    tool dispatch (a ``ToolNode`` or the worker's manual dispatch) propagates the
    ``current_task_id`` advance through the reducer pipeline; the ``ToolMessage``
    in the update keeps the AI tool-call message paired with its result.

    The mark-complete transition is idempotent: completing an already-completed
    row is a no-op that reports the same next pending task, matching the engine's
    replay discipline.
    """

    @tool
    async def mark_task_complete(
        task_id: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Mark a task complete in the thread's database queue.

        Args:
            task_id: The stable task key to mark complete (e.g. 'SBI-003').

        Returns:
            A ``Command`` updating ``current_task_id`` in ``TeamState`` and
            appending a ``ToolMessage`` acknowledgement to the message history.
            When the row is absent or not ``in_progress`` the update carries only
            the acknowledgement ``ToolMessage`` and leaves ``current_task_id``
            untouched.
        """
        outcome = await port.mark_complete(thread_id, task_id)

        if not outcome.did_complete:
            ack = f"Task {task_id} not found or not in_progress."
            return Command(
                update={
                    "messages": [ToolMessage(content=ack, tool_call_id=tool_call_id)],
                }
            )

        if outcome.next_task_key:
            next_key = outcome.next_task_key
            ack = f"Task {task_id} marked complete. Next task: {next_key}."
            return Command(
                update={
                    "current_task_id": next_key,
                    "messages": [ToolMessage(content=ack, tool_call_id=tool_call_id)],
                }
            )

        ack = f"Task {task_id} marked complete. No further pending tasks."
        return Command(
            update={
                "current_task_id": None,
                "messages": [ToolMessage(content=ack, tool_call_id=tool_call_id)],
            }
        )

    return mark_task_complete
