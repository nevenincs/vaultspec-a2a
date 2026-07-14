---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S02'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Replace the ADR-021-rejected drain side-channel in the worker node with Command-returning tool wiring per the ADR's accepted revision

## Scope

- `src/vaultspec_a2a/graph/nodes/worker.py`
- `src/vaultspec_a2a/graph/tools/task_queue.py`

## Description

- Converted the mark-complete factory from the rejected `(tool_fn, drain_fn)`
  tuple into a single `@tool`-decorated coroutine returning
  `Command(update=...)` per the ADR-021 revised contract: the update carries the
  `current_task_id` advance and a `ToolMessage` keyed by the injected
  `tool_call_id`, so message history stays valid and the reducer pipeline applies
  the state change.
- Preserved the idempotent transition semantics and the acknowledgement strings;
  a not-found or not-in-progress row returns a Command whose update carries only
  the acknowledgement `ToolMessage` and leaves `current_task_id` untouched.
- Removed the drain side-channel from the worker node: dropped the closure-scoped
  drain helper, the drain calls in the interrupt and exception handlers, and the
  flat merge of drained updates into the node return.
- Added a manual queue-tool dispatch to the worker mirroring the existing
  permission gate: it inspects the model's emitted `mark_task_complete` calls,
  runs the tool, threads each `ToolMessage` back for a follow-up model turn, and
  surfaces the Command's non-message update through the node return so it flows
  through the reducer pipeline.
- Retained the `GraphBubbleUp` re-raise so interrupts continue to bubble without
  being wrapped as a worker execution error.
- Rewrote the tool tests to exercise the tool via a real ToolCall dispatch and
  assert the Command update shape; updated the vault-write-isolation test to the
  Command surface; added a real-graph integration test proving a
  `mark_task_complete` call advances `current_task_id` through the reducer.

## Outcome

- The rejected drain side-channel is gone; queue-state advances now ride the
  graph's own return path and the reducer pipeline, eliminating the silent-loss-
  on-interrupt failure the ADR revision called out.
- Scoped tests pass: `graph/tests/test_task_queue.py` (8),
  `graph/tests/nodes/test_vault_write_isolation.py` (1),
  `graph/tests/nodes/test_worker_integration.py` (5, including the new dispatch
  case), and the full graph suite (90).
- `ruff check`, `ruff format`, and project-wide `ty check` are clean.

## Notes

- Advertising the queue tool so a model chooses to call it is out of this Step's
  two-file scope. Hosted-model tool binding and the ACP MCP bridge (ACP models
  surface tools through the loopback MCP server, not `bind_tools`) remain
  follow-up, matching the trade-off the ADR records for the direct-`ainvoke`
  worker. This Step delivers the correct Command primitive and the worker-side
  dispatch that propagates it; the real-graph test drives the call directly.
- A single dispatch round is performed per worker turn: a follow-up turn that
  emits further queue calls advances them on the next worker invocation, matching
  the one-task-per-turn cadence the queue design assumes.
- Commit was gated for a period by an intermittent project-wide `ty` pre-commit
  hook failing on a concurrent session's in-flight files; the failures were
  foreign to this Step's scope.
