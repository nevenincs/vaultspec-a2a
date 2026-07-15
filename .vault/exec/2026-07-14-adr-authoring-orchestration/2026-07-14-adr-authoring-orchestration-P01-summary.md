---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# `adr-authoring-orchestration` `P01` summary

P01 fixed the two graph-layer prerequisites the phase machine depends on: mid-run vault index staleness (S01) and the ADR-021-rejected drain side-channel (S02). Both defects were audited before this feature and had to land before any downstream gate or mount node could observe its own phase's outputs.

- Modified: `src/vaultspec_a2a/graph/nodes/vault_reader.py`
- Modified: `src/vaultspec_a2a/graph/compiler.py`
- Modified: `src/vaultspec_a2a/graph/nodes/worker.py`
- Modified: `src/vaultspec_a2a/graph/tools/task_queue.py`
- Modified: `src/vaultspec_a2a/graph/tests/nodes/test_vault_reader.py`
- Modified: `src/vaultspec_a2a/graph/tests/nodes/test_vault_write_isolation.py`
- Modified: `src/vaultspec_a2a/graph/tests/test_task_queue.py`
- Created: `src/vaultspec_a2a/graph/tests/nodes/test_worker_integration.py`

## Description

S01 relocated the vault-index build routine from compile time into the mount node so every mount pass re-derives the active feature's documents from disk and merges the result back into the thread state with an add-only reducer. Before this fix, documents written mid-run were invisible to subsequent gate and mount nodes because the index was populated once at graph compilation and never refreshed. After the fix, the path selector receives the freshly scanned view on each pass, and the `vault_index` state field propagates newly produced files downstream. Regression tests cover mid-run discovery and add-only preservation of prior state entries.

S02 replaced the ADR-021-rejected drain side-channel in the worker node with a `Command(update=...)`-returning `@tool`-decorated coroutine. The drain approach silently dropped queue-state advances on interrupt because it bypassed the reducer pipeline; the corrected tool surfaces the `current_task_id` advance and a `ToolMessage` through the graph's own return path so the reducer applies them regardless of whether the node completes or interrupts. The worker now runs manual queue-tool dispatch, threads each `ToolMessage` back for a follow-up model turn, and surfaces the `Command`'s non-message update through the node return. A real-graph integration test over an `InMemorySaver` checkpointer proves a `mark_task_complete` call advances `current_task_id` through the reducer.

Both steps land clean on `ruff check`, `ruff format`, and `ty check`. The full graph test suite (90 tests) passes after S02.
