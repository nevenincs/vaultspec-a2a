---
adr_id: 021
title: Persistent Task Queue Schema
date: 2026-03-03
status: Proposed
related:
  - docs/adrs/019-teamstate-enrichment-sdd-blackboard.md
  - docs/adrs/020-blackboard-content-mounting.md
  - docs/adrs/022-contextual-anchoring-graph-lifecycle.md
---

# ADR-021: Persistent Task Queue Schema

**Date:** 2026-03-03
**Status:** Proposed

## 1. Context & Problem Statement

ADR-019 extended `TeamState` to carry an `active_feature` tag and `vault_index`.
ADR-020 introduced content mounting — workers receive the text of binding `.vault/`
documents on every invocation. Neither ADR addresses *task sequencing*: there is no
structured representation of the ordered steps a feature requires, no persistent
record of what has been completed, and no pointer to the worker's current task.

Without a persistent task queue, workers track progress implicitly through conversation
history. This causes three observable failure modes:

1. **Task loss on restart:** When a thread is interrupted and a new thread is created
   for the same feature, the conversation history (and any implicit task tracking
   within it) is gone. Workers restart from scratch.
2. **LLM drift:** Without an explicit "you are on task N of M" anchor, workers in long
   sessions lose track of their position and either repeat completed work or skip steps.
3. **No cross-agent coordination:** A supervisor routing to multiple workers has no
   shared, persistent representation of which tasks are assigned to whom and which are
   done.

### 1.1 Prior Art

**MetaGPT (arXiv 2308.00352 §3.3):** Role-scoped sequential task IDs. The orchestrator's
Python code owns all mutations; the LLM reads the queue and emits a task ID. Python
re-serializes on each status transition. This constraint — machine-writes, LLM-reads
only — is the primary lesson from MetaGPT's task management system.

**SWE-agent:** Injects only the current task plus the next 1–2 pending tasks. The agent
does not see the full queue, reducing hallucination risk around "which task am I on."

**LangChain Deep Agents `write_todos`:** `pending / in_progress / completed` schema
persisted in agent state. The todo list functions as a summarization anchor — it survives
compaction and provides continuity across long sessions.

## 2. Decision

### 2.1 Queue File Format

The task queue is stored at `.vault/plan/{feature_tag}-queue.md` as a markdown table:

```markdown
## Task Queue — {feature_tag}

| ID      | Status      | Title                                      |
|---------|-------------|--------------------------------------------|
| SBI-001 | completed   | Add 4 new fields to TeamState              |
| SBI-002 | in_progress | Implement build_anchoring_context          |
| SBI-003 | pending     | Implement mount step node                  |
```

**Rationale for markdown table:** LLM-readable without prompting, Python-parseable
with a simple `|`-split, more robust than YAML or JSON under LLM generation pressure
(models introduce trailing commas, unquoted keys, and comment syntax into JSON; YAML
suffers from hallucinated indentation and duplicate keys).

**Python-only writes:** The queue file is written exclusively by Python code. The LLM
never modifies the queue file directly. Its only queue interaction is:
1. Reading the current queue content (injected as a `SystemMessage` by the mount step).
2. Calling the `mark_task_complete` tool with a task ID when it finishes work.
3. Python code validates the ID, updates the file, and advances `current_task_id` in
   state via the side-channel drain pattern (§2.3).

### 2.2 Sequential Task IDs

Task IDs follow the pattern `{PREFIX}-{NNN}`:

- `{PREFIX}`: Initials of the hyphen-separated words in `feature_tag`, uppercased.
  Example: `sdd-blackboard-integration` → `SBI`.
- `{NNN}`: Zero-padded 3-digit counter, derived from the existing row count in the
  queue file at task creation time + 1.
  Example: `SBI-001`, `SBI-002`, ..., `SBI-099`.

IDs are assigned at queue creation time and never change. They provide a stable
reference across sessions, workers, and thread restarts.

### 2.3 TeamState Integration

A single new field is added to `TeamState` (`lib/core/state.py`):

```python
class TeamState(TypedDict):
    # ... existing fields ...

    # Pointer to the task the current worker is executing.
    # None when no feature is active or no task has been assigned.
    # Updated by the side-channel drain after mark_task_complete tool call.
    # Never stores queue content — content lives in the queue file on disk.
    current_task_id: NotRequired[str | None]
```

`current_task_id` uses last-write-wins (LangGraph default for plain typed fields).
Only the ID pointer lives in state; queue content lives on disk and is injected via
the mount step (ADR-020).

### 2.4 `mark_task_complete` Tool — Side-Channel Drain Pattern

ACP tools return strings to the LLM — they cannot return `TeamState` patch dicts.
To propagate state updates (advancing `current_task_id`) from tool execution back to
`worker_node`, a **side-channel drain pattern** is used.

`create_mark_task_complete_tool` (in `lib/core/task_queue.py`) is a factory that
returns a `(tool_fn, drain_fn)` tuple:

```python
# lib/core/task_queue.py
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

__all__ = ["create_mark_task_complete_tool"]


def create_mark_task_complete_tool(
    workspace_root: Path,
    feature_tag: str,
) -> tuple[Callable, Callable]:
    """Factory returning (tool_fn, drain_fn).

    tool_fn: async tool passed to the LLM — returns a string acknowledgement.
    drain_fn: called by worker_node after model.ainvoke() — returns accumulated
              TeamState patch dict and clears the pending list.

    The side-channel pattern is required because ACP tools return strings
    to the LLM, not TeamState dicts.
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
            return f"Queue file not found at {queue_path}. Cannot mark {task_id} complete."

        def _update_queue() -> tuple[str, str | None]:
            """Read, update, and write queue file. Returns (message, next_task_id)."""
            content = queue_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            updated_lines: list[str] = []
            found = False
            next_task_id: str | None = None

            for line in lines:
                if f"| {task_id} |" in line and "in_progress" in line:
                    line = line.replace("in_progress", "completed", 1)
                    found = True
                updated_lines.append(line)

            if not found:
                return f"Task {task_id} not found or not in_progress.", None

            # Find next pending task
            for line in updated_lines:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2 and parts[1] == "pending":
                    next_task_id = parts[0]
                    break

            queue_path.write_text("\n".join(updated_lines), encoding="utf-8")
            return f"Task {task_id} marked complete.", next_task_id

        message, next_task_id = await asyncio.to_thread(_update_queue)

        if next_task_id:
            pending_state_updates.append({"current_task_id": next_task_id})
            return f"{message} Next task: {next_task_id}."
        else:
            pending_state_updates.append({"current_task_id": None})
            return f"{message} No further pending tasks."

    def drain_state_updates() -> dict[str, Any]:
        """Return accumulated state updates and clear the pending list.

        Called by worker_node after model.ainvoke() completes.
        """
        merged: dict[str, Any] = {}
        for update in pending_state_updates:
            merged.update(update)
        pending_state_updates.clear()
        return merged

    return mark_task_complete, drain_state_updates
```

**Worker integration** in `create_worker_node()` (`lib/core/nodes/worker.py`):

```python
tool_fn, drain_fn = create_mark_task_complete_tool(workspace_root, feature_tag)
# ... wire tool_fn into model tool binding ...

async def worker_node(state: TeamState) -> dict[str, Any]:
    # ... message construction (ADR-022, ADR-020) ...
    response = await model.ainvoke(messages, config)
    state_updates = drain_fn()
    return {
        "messages": [response],
        "mounted_context": None,
        **state_updates,
    }
```

### 2.5 Filtered Queue Injection

`_filter_queue_content` (in `lib/core/task_queue.py`) is called by `mount_node`
(ADR-020) when processing a `{feature}-queue.md` path. It returns a filtered view:
the current task (from `state.get("current_task_id")`) plus the next 2 pending tasks.

```python
def _filter_queue_content(
    full_content: str,
    current_task_id: str | None,
) -> str:
    """Return filtered queue: header + current task row + next 2 pending rows.

    Prevents injecting the full queue into the context window for features
    with many tasks. Workers only need their current task and immediate horizon.
    """
    ...
```

Queue content is injected only when `pipeline_phase` is `"plan"` or `"exec"`.
Other phases (research, adr, reference, audit) do not inject queue content:
- Research, adr, reference: task queue does not exist yet at these phases.
- Audit: audit workers verify artifacts by reading vault documents directly;
  they do not execute or complete tasks from the task queue.

### 2.6 Queue Bootstrap

Queue files are created manually by the human operator or by a planner worker using
its filesystem write tools (e.g., the existing `write_file` tool). A first-class
`create_task_queue` tool is deferred to v2 — in v1, queue creation is out-of-scope
for the orchestration engine and requires no new tool implementation.

## 3. Consequences

### Positive

- Workers have a persistent, machine-verified record of which tasks are done and which
  are next, surviving thread restarts and context compaction.
- Sequential task IDs provide a stable cross-session reference that neither conversation
  history nor `TeamState` alone can offer.
- The side-channel drain pattern cleanly separates tool string output (for the LLM) from
  state updates (for LangGraph), without requiring any changes to the ACP tool protocol.
- Filtered queue injection (current + next 2) limits token overhead while giving workers
  enough horizon to plan their next step.
- Queue file is ground truth — `TeamState` carries only a lightweight pointer.

### Negative / Trade-offs

- The `pending_state_updates` side channel is implicit coupling between `mark_task_complete`
  and `worker_node`. The factory must be called once per graph compilation and the returned
  `drain_fn` must be called after every `model.ainvoke()`. If a caller forgets `drain_fn()`,
  state updates are silently dropped.
- Queue file format changes require a migration — existing queue files using a different
  column layout will fail `_filter_queue_content` parsing.
- `mark_task_complete` validates by substring match (`f"| {task_id} |"`). Task IDs
  containing `|` characters would produce false matches; the sequential ID scheme
  (`SBI-NNN`) makes this practically impossible, but the constraint should be documented.

## 4. Rejected Alternatives

### Store queue content in TeamState

Queue content stored as a `TeamState` field is checkpointed on every step, writing 5–50 KB
of markdown to SQLite repeatedly. It is also lost when a new thread is created for the
same feature. Rejected: disk persistence is the correct layer for cross-session data.

### LLM writes to queue file directly

LLMs reliably corrupt structured formats when asked to edit them in-place (trailing commas
in JSON, hallucinated YAML indentation, duplicate keys). Machine-writes, LLM-reads is the
MetaGPT-validated pattern. Rejected.

### Return TeamState dict from tool function

ACP tool functions return strings to the LLM. Returning a dict would violate the ACP
tool protocol and cause a runtime error. The side-channel drain pattern is required.
Rejected.

### Inject full queue on every invocation

Injecting all rows of a 20-task queue on every worker invocation wastes ~500–2,000 tokens
per call with no benefit — workers only need their current task and the next 1–2 steps.
The SWE-agent pattern (filtered view) is more efficient. Rejected.

## 5. Implementation Constraints

- `lib/core/task_queue.py` must declare `__all__ = ["create_mark_task_complete_tool"]`.
  `_filter_queue_content` is private (not exported).
- `mark_task_complete` must be `async def`. File reads and writes use `asyncio.to_thread`.
- `drain_fn()` must be called by `worker_node` after every `model.ainvoke()`, including
  in exception handlers, to avoid state update leaks between invocations.
- Queue file writes are append-safe: `_update_queue` reads the full file, patches the
  relevant row, and writes the complete updated content atomically (no partial writes).
- `current_task_id` uses last-write-wins. It is `NotRequired` in `TeamState` — direct
  access via `state.get("current_task_id")` is correct (field may be absent in legacy state).
- Queue injection (§2.5) applies only for `pipeline_phase in {"plan", "exec"}`. `mount_node`
  checks this before calling `_filter_queue_content`.
- A first-class `create_task_queue` tool is deferred to v2. Queue file creation is
  out-of-scope for v1.

## 6. Module Hierarchy Impact

```text
lib/core/
├── state.py            AMENDED: current_task_id: NotRequired[str | None] added
├── task_queue.py       NEW: create_mark_task_complete_tool() factory, drain_fn,
│                       _filter_queue_content; __all__ = ["create_mark_task_complete_tool"]
├── nodes/
│   ├── mount.py        AMENDED: calls _filter_queue_content for queue files
│   │                   when pipeline_phase in {"plan", "exec"}
│   └── worker.py       AMENDED: calls create_mark_task_complete_tool(),
│                       calls drain_fn() after model.ainvoke()
├── tests/
│   ├── test_task_queue.py  NEW: tool factory, drain pattern, filtered injection,
│   │                       phase gate, async file I/O
│   └── test_mount.py       AMENDED: queue filtering integration
```

## 7. References

- `lib/core/task_queue.py` — NEW (create_mark_task_complete_tool factory)
- `lib/core/state.py` — TeamState (current_task_id field added)
- `lib/core/nodes/mount.py` — queue content filtering integration
- `lib/core/nodes/worker.py` — drain_fn integration, mark_task_complete tool binding
- [ADR-019](019-teamstate-enrichment-sdd-blackboard.md) — vault_index, TeamState fields
- [ADR-020](020-blackboard-content-mounting.md) — mount_node, content injection pattern
- [docs/research/2026-03-03-task-queue-schema-derisking.md](../research/2026-03-03-task-queue-schema-derisking.md) — MetaGPT pattern, markdown table format, session persistence
- [MetaGPT arXiv 2308.00352 §3.3](https://arxiv.org/abs/2308.00352) — machine-writes, LLM-reads, sequential IDs
- [SWE-agent](https://swe-agent.com) — filtered task injection pattern
