---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S13'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Move the worker task queue from the .vault/plan markdown table into the A2A database (new Alembic migration), preserve mark-task-complete semantics, and delete the markdown read-write path

## Scope

- `src/vaultspec_a2a/graph/tools/task_queue.py`
- `src/vaultspec_a2a/database/`
- `src/vaultspec_a2a/graph/nodes/worker.py`

## Description

SCOPED, HANDED OFF (not yet implemented). This step is a database schema migration; the executing session judged its context too saturated to author a hard-to-reverse migration safely, so per the checkpoint protocol it was scoped in full and handed to a fresh executor, with the originating executor staying resident as first reviewer.

Current state (post-merge, verified by reading): the worker task queue is a markdown table at `<workspace_root>/.vault/plan/<feature_tag>-queue.md` with rows `| task_id | status | ... |` (status is `pending`/`in_progress`/`completed`). Only two operations exist in code: a READ path (`graph/nodes/vault_reader.py` intercepts `*-queue.md` reads and calls `_filter_queue_content` to inject the current task row plus `domain_config.task_queue_pending_horizon` next pending rows) and a MARK-COMPLETE path (`graph/tools/task_queue.py` `create_mark_task_complete_tool(workspace_root, feature_tag)` returns `(mark_task_complete, drain_state_updates)`; mark_task_complete flips `in_progress`->`completed`, finds the next pending `task_id`, rewrites the markdown, and accumulates a `{current_task_id: ...}` TeamState patch). No code POPULATES the queue — task rows are authored externally.

Target: a `task_queue_entries` DB table (new Alembic revision `0006`, down_revision `0005`, FK to `threads.id`), a queue repository, a rewritten mark-complete tool that updates the DB row, queue injection read from the DB, and deletion of the markdown read-write path. The mark-complete acknowledgement strings and the `current_task_id` TeamState semantics must be preserved exactly.

## Outcome

Deferred. Full scoping brief delivered to the team lead for a fresh executor. The step is NOT complete and its plan checkbox is intentionally left open.

## Notes

Load-bearing OPEN DESIGN QUESTION for the architect, surfaced before any migration is written: nothing in code populates the queue today (it consumes an externally-authored markdown), and S11's deny policy now blocks agents from writing `.vault/plan/*-queue.md` anyway. The DB queue therefore needs a POPULATION path that does not exist yet — from the run-start payload, a planner node emitting entries, or an ingested engine plan proposal. Traps for the implementer: the node has no direct DB session (the queue tool currently takes `workspace_root`+`feature_tag`; the DB version needs a session factory + `thread_id`, which changes the `create_mark_task_complete_tool` and worker-node wiring); `vault_reader.py`'s `*-queue.md` interception must be removed cleanly; `domain_config.task_queue_pending_horizon` must still bound the injection; the tool path is async so the DB version uses the async session; `adr-17` is the amended schema decision R5 realizes.
