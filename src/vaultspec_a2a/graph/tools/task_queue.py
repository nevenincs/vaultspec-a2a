"""Persistent task queue management (ADR-021)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from vaultspec_a2a.control.config import settings

__all__ = ["create_mark_task_complete_tool"]

_QUEUE_PHASES = frozenset({"plan", "exec"})
_MIN_TABLE_COLUMNS = 2  # Minimum columns for a valid markdown table row


def _filter_queue_content(
    full_content: str,
    current_task_id: str | None,
) -> str:
    """Return filtered queue: header + current task row + next 2 pending rows.

    Prevents injecting the full queue into the context window for features
    with many tasks. Workers only need their current task and immediate horizon.

    Args:
        full_content:    Raw text of the queue file.
        current_task_id: The task ID the worker is currently executing, or None.

    Returns:
        A filtered markdown string containing the header section, the current
        task row (if found), and up to 2 subsequent pending rows.
    """
    lines = full_content.splitlines()

    # Collect header lines (everything up to and including the separator row)
    header_lines: list[str] = []
    data_lines: list[str] = []
    in_header = True
    for line in lines:
        stripped = line.strip()
        if in_header:
            header_lines.append(line)
            # The separator row looks like |---|---|---| -- signals end of header
            if (
                stripped.startswith("|")
                and set(stripped.replace("|", "").replace("-", "").replace(" ", ""))
                == set()
            ):
                in_header = False
        elif stripped.startswith("|"):
            data_lines.append(line)

    selected: list[str] = []

    # Include current task row first (regardless of status)
    if current_task_id:
        for line in data_lines:
            if f"| {current_task_id} |" in line:
                selected.append(line)
                break

    # Collect up to task_queue_pending_horizon next pending rows
    pending_count = 0
    for line in data_lines:
        if pending_count >= settings.task_queue_pending_horizon:
            break
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if (
            len(parts) >= _MIN_TABLE_COLUMNS
            and parts[1] == "pending"
            and not (current_task_id and f"| {current_task_id} |" in line)
        ):
            selected.append(line)
            pending_count += 1

    result_lines = header_lines + selected
    return "\n".join(result_lines)


def create_mark_task_complete_tool(
    workspace_root: Path,
    feature_tag: str,
) -> tuple[Callable, Callable]:
    """Factory returning (tool_fn, drain_fn).

    tool_fn: async tool passed to the LLM -- returns a string acknowledgement.
    drain_fn: called by worker_node after model.ainvoke() -- returns accumulated
              TeamState patch dict and clears the pending list.
    """
    queue_path = workspace_root / ".vault" / "plan" / f"{feature_tag}-queue.md"
    pending_state_updates: list[dict[str, Any]] = []

    async def mark_task_complete(task_id: str) -> str:
        """Mark a task as completed in the queue file.

        Args:
            task_id: The task ID to mark complete (e.g. 'SBI-003').

        Returns:
            A string acknowledgement for the LLM confirming completion
            and stating the next pending task ID (or "no further tasks").
        """
        if not queue_path.exists():
            return (
                f"Queue file not found at {queue_path}. Cannot mark {task_id} complete."
            )

        def _update_queue() -> tuple[str, str | None]:
            """Read, update, and write queue file. Returns (message, next_task_id)."""
            content = queue_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            updated_lines: list[str] = []
            found = False
            next_task_id: str | None = None

            for raw_line in lines:
                updated = raw_line
                if f"| {task_id} |" in raw_line and "in_progress" in raw_line:
                    updated = raw_line.replace("in_progress", "completed", 1)
                    found = True
                updated_lines.append(updated)

            if not found:
                return f"Task {task_id} not found or not in_progress.", None

            # Find next pending task
            for line in updated_lines:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= _MIN_TABLE_COLUMNS and parts[1] == "pending":
                    next_task_id = parts[0]
                    break

            queue_path.write_text("\n".join(updated_lines), encoding="utf-8")
            return f"Task {task_id} marked complete.", next_task_id

        message, next_task_id = await asyncio.to_thread(_update_queue)

        if next_task_id:
            pending_state_updates.append({"current_task_id": next_task_id})
            return f"{message} Next task: {next_task_id}."
        pending_state_updates.append({"current_task_id": None})
        return f"{message} No further pending tasks."

    def drain_state_updates() -> dict[str, Any]:
        """Return accumulated state updates and clear the pending list."""
        merged: dict[str, Any] = {}
        for update in pending_state_updates:
            merged.update(update)
        pending_state_updates.clear()
        return merged

    return mark_task_complete, drain_state_updates
