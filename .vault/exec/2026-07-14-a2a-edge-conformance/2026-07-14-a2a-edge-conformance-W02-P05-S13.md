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

Implemented. The worker task queue is relocated from the `.vault/plan/<feature_tag>-queue.md` markdown table into the A2A database per the R5 refinement.

New schema and migration. `TaskQueueEntryModel` (table `task_queue_entries`) is a thread-owned row: `id` (uuid hex pk), `thread_id` (FK to `threads.id`, ORM cascade delete via `cascade="all, delete-orphan"` mirroring the existing child tables), `feature_tag`, `position` (int, sole ordering authority), `task_key` (stable per-thread identity the mark-complete tool addresses), `description`, `status` (bounded by the new `TaskQueueStatus` enum: `pending | in_progress | completed | failed`), nullable `plan_changeset_id` and `plan_step_key` (D5 references, never content), and `created_at`/`updated_at`. Two unique constraints per thread — `(thread_id, position)` and `(thread_id, task_key)` — plus a `thread_id` index. Alembic revision `0006` (down_revision `0005`) creates and drops the table.

Repository. `database/task_queue_repository.py` holds pure persistence: `seed_task_queue` (the internal-only population path used by tests and future internals — validates `feature_tag` with the merged traversal guard, no agent-reachable path), `get_queue_view` (current row plus up to `horizon` next-pending rows by `position`, mirroring the old `_filter_queue_content` ordering exactly), and `mark_task_complete` (idempotent transition returning a `MarkCompleteResult` named tuple). Completing an `in_progress` row transitions it to `completed`; re-completing an already-`completed` row is a no-op that reports the same next pending row (engine replay discipline); a `pending`/`failed` or missing row is reported as not completable. The module never imports the graph layer.

Layer-clean injection. A `TaskQueuePort` Protocol plus `QueueEntryView`/`MarkCompleteOutcome` DTOs were added to `graph/protocols.py`, mirroring the existing `ProviderFactoryProtocol` decoupling. The graph tool and mount node depend only on the port. `SqlTaskQueuePort` (in the worker composition layer, `worker/task_queue_port.py`) adapts the repository to the port over a session factory, so the database layer never leaks into the domain graph. `graph/tools/task_queue.py` is rewritten to a pure `render_queue_view` (stable markdown table) and a port-backed `create_mark_task_complete_tool(port, thread_id)`; the acknowledgement strings ("Task X marked complete. Next task: Y.", "... No further pending tasks.", "Task X not found or not in_progress.") and the `current_task_id` TeamState drain semantics are preserved. `graph/nodes/vault_reader.py` drops the `*-queue.md` interception and instead renders the DB-sourced queue view as a mounted block during the plan/exec phases, bounded by `domain_config.task_queue_pending_horizon` and the mount token ceiling.

Thread-correct wiring. Because the compiled graph is cached per `(team_preset, workspace_root, autonomous)` and shared across threads, the mark-complete tool cannot close over `thread_id` at compile time. `create_worker_node` now takes an optional `task_queue_port` and builds the tool per invocation from `state["thread_id"]`. The port is threaded through `compile_team_graph` and the three topology compilers into both the worker and mount nodes; `GraphLifecycleManager` constructs the single `SqlTaskQueuePort(get_session_factory())` (the worker reaches the shared app database; migrations remain gateway-owned). The markdown read/write path is fully deleted.

- Modified: `src/vaultspec_a2a/thread/enums.py`, `src/vaultspec_a2a/database/models.py`, `src/vaultspec_a2a/database/_helpers.py`, `src/vaultspec_a2a/database/__init__.py`, `src/vaultspec_a2a/graph/protocols.py`, `src/vaultspec_a2a/graph/tools/task_queue.py`, `src/vaultspec_a2a/graph/nodes/vault_reader.py`, `src/vaultspec_a2a/graph/nodes/worker.py`, `src/vaultspec_a2a/graph/compiler.py`, `src/vaultspec_a2a/worker/graph_lifecycle.py`, `src/vaultspec_a2a/database/tests/test_migrations.py`, `src/vaultspec_a2a/graph/tests/test_task_queue.py`, `src/vaultspec_a2a/graph/tests/nodes/test_vault_reader.py`
- Created: `src/vaultspec_a2a/database/migrations/versions/0006_task_queue_entries.py`, `src/vaultspec_a2a/database/task_queue_repository.py`, `src/vaultspec_a2a/worker/task_queue_port.py`, `src/vaultspec_a2a/database/tests/test_task_queue_repository.py`

## Outcome

Complete pending cross-agent review. `ruff` and `ty` clean on all changed files; 235 tests pass across the graph, database, and worker suites (34 of them new/rewritten queue tests). The markdown read/write path is gone. The plan checkbox is held open until the executor-opus-w01 diff review passes, per the review-before-completion mandate.

## Tests

Real in-memory aiosqlite, no mocks. `test_task_queue_repository.py`: seed persistence and ordering, feature-tag traversal rejection, required-field validation, plan-reference storage, queue-view selection (current-first, horizon bound, excludes completed, no/unknown current, empty thread), mark-complete transitions (in_progress, drained, missing, wrong-status, idempotent re-complete), and cascade delete with the owning thread. `test_task_queue.py`: `render_queue_view` shape and ordering plus the mark-complete tool driven through the real `SqlTaskQueuePort` for every acknowledgement branch and drain semantics. `test_vault_reader.py`: DB queue injection during exec, phase gating, and empty-queue no-op. `test_migrations.py` updated so the head revision assertion and `_APP_TABLES` cover `task_queue_entries` upgrade/downgrade.

The open population question the scoping brief raised is resolved by the R5 refinement: population is planner-emitted run-locally (planner wiring owned by the full-team wave, out of this step), with `seed_task_queue` the interim internal-only path; the S14 live proof exercises the DB-backed queue end-to-end.

## Notes

Scope beyond the plan's file list was necessary and is layer-justified: `graph/protocols.py` (new port, mirrors the `ProviderFactoryProtocol` DI pattern), `graph/compiler.py` and `worker/graph_lifecycle.py` (port threading, same shape as the existing `checkpointer`/`provider_factory` injection), `thread/enums.py` (new `TaskQueueStatus`), and `worker/task_queue_port.py` (the adapter, placed at the composition root to keep `database/` free of graph imports). `adr-17` is the amended schema decision R5 realizes.
