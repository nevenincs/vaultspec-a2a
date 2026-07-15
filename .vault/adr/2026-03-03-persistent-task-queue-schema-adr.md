---
tags:
- '#adr'
- '#persistent-task-queue-schema'
date: 2026-03-03
modified: '2026-03-03'
related:
- '[[2026-03-03-teamstate-enrichment-sdd-blackboard-adr]]'
- '[[2026-03-03-blackboard-content-mounting-adr]]'
- '[[2026-03-03-contextual-anchoring-graph-lifecycle-adr]]'
- '[[2026-03-31-docs-vault-migration-research]]'
---

# `persistent-task-queue-schema` adr: `adr-17` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-17`
- Original title: `Persistent Task Queue Schema`
- Legacy status at migration time: `Revised`

## Original ADR

## ADR-021: Persistent Task Queue Schema

**Date:** 2026-03-03
**Status:** Revised (supersedes side-channel drain pattern — see §2.4 and §5)

## 1. Context & Problem Statement

ADR-019 extended `TeamState` to carry an `active_feature` tag and `vault_index`.
ADR-020 introduced content mounting — workers receive the text of binding `.vault/`
documents on every invocation. Neither ADR addresses _task sequencing_: there is no
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

| ID      | Status      | Title                             |
| ------- | ----------- | --------------------------------- |
| SBI-001 | completed   | Add 4 new fields to TeamState     |
| SBI-002 | in_progress | Implement build_anchoring_context |
| SBI-003 | pending     | Implement mount step node         |
```text

**Rationale for markdown table:** LLM-readable without prompting, Python-parseable
with a simple `|`-split, more robust than YAML or JSON under LLM generation pressure
(models introduce trailing commas, unquoted keys, and comment syntax into JSON; YAML
suffers from hallucinated indentation and duplicate keys).

**Python-only writes:** The queue file is written exclusively by Python code. The LLM
never modifies the queue file directly. Its only queue interaction is:

1. Reading the current queue content (injected as a `SystemMessage` by the mount step).
2. Calling the `mark_task_complete` tool with a task ID when it finishes work.
3. Python code validates the ID, updates the file, and returns a `Command(update={...})`
   that LangGraph propagates through the reducer pipeline automatically (§2.4).

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

A single new field is added to `TeamState` (`src/vaultspec_a2a/core/state.py`):

```python
class TeamState(TypedDict):
    # ... existing fields ...

    # Pointer to the task the current worker is executing.
    # None when no feature is active or no task has been assigned.
    # Updated via Command.update from mark_task_complete tool.
    # Never stores queue content — content lives in the queue file on disk.
    current_task_id: NotRequired[str | None]
```text

`current_task_id` uses last-write-wins (LangGraph default for plain typed fields).
Only the ID pointer lives in state; queue content lives on disk and is injected via
the mount step (ADR-020).

### 2.4 `mark_task_complete` Tool — `Command(update={...})` Pattern

The `mark_task_complete` tool returns a `Command(update={...})` object that LangGraph
propagates directly through the state reducer pipeline. This is the documented pattern
for tools that need to update graph state (LangGraph docs:
<https://docs.langchain.com/oss/python/langgraph/use-graph-api>).

**Key constraints from official docs:**

- The tool must be decorated with `@tool` (or equivalent) so `ToolNode` can handle it.
- `Command.update` **must** include a `messages` key containing a `ToolMessage` with
  the correct `tool_call_id`. This is required because LLM providers enforce that every
  AI tool-call message is followed by a corresponding tool result message.
- `InjectedToolCallId` (from `langchain_core.tools`) injects the `tool_call_id`
  automatically at call time — it is not visible to the LLM as a parameter.
- `ToolNode` automatically propagates `Command` objects returned by tools. No drain
  step or wrapper node is needed.

`create_mark_task_complete_tool` (in `src/vaultspec_a2a/core/task_queue.py`) is a factory that
returns a single `@tool`-decorated async function:

```python
# src/vaultspec_a2a/core/task_queue.py
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

__all__ = ["create_mark_task_complete_tool"]


def create_mark_task_complete_tool(
    workspace_root: Path,
    feature_tag: str,
):
    """Factory returning a single @tool-decorated async function.

    The returned tool updates TeamState via Command(update={...}), which
    ToolNode propagates through the reducer pipeline automatically.
    No drain step or side-channel is required.
    """
    queue_path = workspace_root / ".vault" / "plan" / f"{feature_tag}-queue.md"

    @tool
    async def mark_task_complete(
        task_id: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Mark a task as completed in the queue file.

        Args:
            task_id: The task ID to mark complete (e.g. 'SBI-003').

        Returns:
            A Command updating current_task_id in TeamState and adding a
            ToolMessage to the message history.
        """
        if not queue_path.exists():
            msg = f"Queue file not found at {queue_path}. Cannot mark {task_id} complete."
            return Command(
                update={
                    "messages": [ToolMessage(content=msg, tool_call_id=tool_call_id)],
                }
            )

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
            ack = f"{message} Next task: {next_task_id}."
        else:
            ack = f"{message} No further pending tasks."

        return Command(
            update={
                "current_task_id": next_task_id,
                "messages": [ToolMessage(content=ack, tool_call_id=tool_call_id)],
            }
        )

    return mark_task_complete
```text

**Worker integration** in `create_worker_node()` (`src/vaultspec_a2a/core/nodes/worker.py`):

```python
# worker_node no longer needs a drain step — ToolNode propagates Command automatically.
tool_fn = create_mark_task_complete_tool(workspace_root, feature_tag)
# Bind tool_fn to the model and add a ToolNode to the graph for tool dispatch.

async def worker_node(state: TeamState) -> dict[str, Any]:
    # ... message construction (ADR-022, ADR-020) ...
    response = await effective_model.ainvoke(messages)
    response.name = name
    return {"messages": [response], "mounted_context": None}
    # State updates (current_task_id) flow via Command.update in ToolNode — no drain.
```text

### 2.5 Filtered Queue Injection

`_filter_queue_content` (in `src/vaultspec_a2a/core/task_queue.py`) is called by `mount_node`
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
```text

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
- `Command(update={...})` is the documented LangGraph pattern for tools updating state.
  State updates flow through the reducer pipeline automatically — no side-channel, no
  drain step, no risk of silent update loss on interrupt.
- `ToolNode` propagates `Command` automatically: the worker node needs no awareness of
  whether a tool updated state. The graph topology handles it.
- The `ToolMessage` requirement (enforced by `InjectedToolCallId`) ensures message
  history validity — LLM providers require tool-call messages to be followed by tool
  results.
- Filtered queue injection (current + next 2) limits token overhead while giving workers
  enough horizon to plan their next step.
- Queue file is ground truth — `TeamState` carries only a lightweight pointer.

### Negative / Trade-offs

- Tools returning `Command` require `ToolNode` in the graph. The current ACP-backed
  worker pattern (direct `model.ainvoke`) does not use `ToolNode`; integrating
  `Command`-returning tools requires adding a `ToolNode` branch or a custom tool
  dispatch layer that manually propagates `Command` objects.
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

### Side-channel drain pattern (original §2.4)

The original implementation used a `(tool_fn, drain_fn)` tuple factory where the tool
accumulated state updates in a closure-scoped `pending_state_updates` list and `drain_fn`
was called by `worker_node` after `model.ainvoke()`. This pattern was rejected for the
revised design because:

1. **Incompatible with LangGraph's state model.** `drain_fn()` returns a plain dict that
   `worker_node` merges into its own return value. This bypasses the reducer pipeline —
   updates are applied as a last-write-wins flat merge, ignoring `_merge_vault_index`
   and other annotated reducers.
2. **Silent loss on interrupt.** When `GraphBubbleUp` is raised (ACP interrupt path),
   `worker_node` calls `drain_fn()` and discards the result (the `except GraphBubbleUp`
   block re-raises immediately). Any `current_task_id` advance accumulated during that
   invocation is silently dropped.
3. **Implicit coupling.** The factory must be called once per graph compilation and the
   `drain_fn` must be called after every `model.ainvoke()`, including in every exception
   handler. A missed call leaks accumulated state across invocations.
4. **Documented alternative exists.** `Command(update={...})` from a `@tool`-decorated
   function is the officially documented LangGraph pattern for tools that update state.
   `ToolNode` propagates it automatically. No drain step is required.

### Inject full queue on every invocation

Injecting all rows of a 20-task queue on every worker invocation wastes ~500–2,000 tokens
per call with no benefit — workers only need their current task and the next 1–2 steps.
The SWE-agent pattern (filtered view) is more efficient. Rejected.

## 5. Implementation Constraints

- `src/vaultspec_a2a/core/task_queue.py` must declare `__all__ = ["create_mark_task_complete_tool"]`.
  `_filter_queue_content` is private (not exported), but may be imported by `mount.py`
  as an internal sibling import pending a refactor to a shared utility (tracked as M-2
  in the LangGraph drift audit).
- `mark_task_complete` must be `async def`. File reads and writes use `asyncio.to_thread`.
- `mark_task_complete` must accept `tool_call_id: Annotated[str, InjectedToolCallId]`
  as a parameter. This is injected automatically by LangGraph at call time and is not
  exposed to the LLM in the tool schema.
- `Command.update` **must** include a `messages` key containing a `ToolMessage` with
  the injected `tool_call_id`. This ensures message history validity.
- The factory returns a single callable (no tuple). The `drain_fn` pattern is
  eliminated — callers receive only `mark_task_complete`.
- `worker_node` no longer calls a drain function. State updates from
  `mark_task_complete` flow via `Command.update` through `ToolNode` automatically.
- `current_task_id` uses last-write-wins. It is `NotRequired` in `TeamState` — direct
  access via `state.get("current_task_id")` is correct (field may be absent in legacy state).
- Queue injection (§2.5) applies only for `pipeline_phase in {"plan", "exec"}`. `mount_node`
  checks this before calling `_filter_queue_content`.
- A first-class `create_task_queue` tool is deferred to v2. Queue file creation is
  out-of-scope for v1.

## 6. Module Hierarchy Impact

```text
src/vaultspec_a2a/core/
├── state.py            AMENDED: current_task_id: NotRequired[str | None] added
├── task_queue.py       NEW: create_mark_task_complete_tool() factory (single callable,
│                       no drain_fn); _filter_queue_content (private);
│                       __all__ = ["create_mark_task_complete_tool"]
├── nodes/
│   ├── mount.py        AMENDED: calls _filter_queue_content for queue files
│   │                   when pipeline_phase in {"plan", "exec"}
│   └── worker.py       AMENDED: calls create_mark_task_complete_tool() (single
│                       callable); no drain_fn; ToolNode propagates Command.update
├── tests/
│   ├── test_task_queue.py  NEW: tool factory, Command.update pattern, ToolMessage
│   │                       validity, filtered injection, phase gate, async file I/O
│   └── test_mount.py       AMENDED: queue filtering integration
```text

## 7. References

- `src/vaultspec_a2a/core/task_queue.py` — NEW (create_mark_task_complete_tool factory)
- `src/vaultspec_a2a/core/state.py` — TeamState (current_task_id field added)
- `src/vaultspec_a2a/core/nodes/mount.py` — queue content filtering integration
- `src/vaultspec_a2a/core/nodes/worker.py` — mark_task_complete tool binding; no drain_fn
- LangGraph docs — Update state from tools
  — `Command(update={...})` pattern, `InjectedToolCallId`, `ToolNode` propagation
- LangGraph docs — Command reference
  — `Command.update`, `Command.goto`, tool return semantics
- ADR-019 — vault_index, TeamState fields
- ADR-020 — mount_node, content injection pattern
- legacy-research/2026-03-03-task-queue-schema-derisking.md — MetaGPT pattern, markdown table format, session persistence
- MetaGPT arXiv 2308.00352 §3.3 — machine-writes, LLM-reads, sequential IDs
- SWE-agent — filtered task injection pattern

## Amendment - a2a-edge-conformance (2026-07-15)

The queue's STORAGE moved out of the `.vault/plan/` markdown table into the
A2A database (`task_queue_entries`, Alembic 0006) - orchestration state is
this repo's own, never a vault artifact (dashboard D5). Rows are populated
run-locally (planner-emitted) and link to the engine plan proposal by
Vaultspec-id reference, never by content. The read-and-mark-complete
capability, filtered current-plus-horizon injection, and sequential
ordering this record defines are preserved; only the backing store changed
(file parse to repository query, format-stable). See
`2026-07-14-a2a-edge-conformance-adr` (R5) and
`2026-07-14-a2a-edge-conformance-reference`.
