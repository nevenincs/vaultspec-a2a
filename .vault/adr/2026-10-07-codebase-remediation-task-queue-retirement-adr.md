---
tags:
  - "#adr"
  - "#codebase-remediation"
date: '2026-10-07'
related:
  - "[[2026-10-06-codebase-remediation-audit]]"
  - "[[2026-03-03-persistent-task-queue-schema-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-09-24-architecture-review-audit]]"
supersedes:
  - '2026-03-03-persistent-task-queue-schema-adr'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:e011fdd0680354b7e0f9ccbf30d9af3d99311394bb0fec2a2410a1a578226e52'
---
# `codebase-remediation` adr: `retire the agent task queue` | (**status:** `accepted`)

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

## Problem Statement

`2026-03-03-persistent-task-queue-schema-adr` defines a persistent agent task queue and a `mark_task_complete` tool. Its 2026-07-15 amendment moved storage into the `task_queue_entries` table and said rows "are populated run-locally (planner-emitted)". No producer exists. Production never writes a queue row, never starts a task, and never offers the tool to a real model (R3-F3 in `2026-10-06-codebase-remediation-audit`). The audit item `dead-task-queue-tool` in `2026-09-24-architecture-review-audit` records the same gap; it has been open with no owner since 2026-09-24. The subsystem has no behaviour, but it spans about 18 production modules plus their tests. Removing it drops a table and a checkpoint channel and reverses an accepted capability, so it needs a decision.

## Considerations

Code paths are under `src/vaultspec_a2a/`.

- **No writer.** `seed_task_queue` is the only writer of `task_queue_entries`. Outside tests it appears only at its definition and in the facade (`database/task_queue_repository.py:73`, `database/__init__.py:146`). Its own docstring calls it "used by tests and future gateway/planner internals" (`database/task_queue_repository.py:11-13`).
- **No state transition.** `mark_task_complete` completes only an `in_progress` row (`database/task_queue_repository.py:200`). Nothing in production sets `in_progress`.
- **Never bound.** No `bind_tools` call exists. The worker dispatches the tool only when a model emits a call named `mark_task_complete` (`graph/nodes/_worker_tool_calls.py:56-69`). Only the deterministic fixture emits one (`providers/deterministic_chat_model.py:249-268`), through the `deterministic-tool-call` presets.
- **False premise.** `2026-07-14-a2a-edge-conformance-adr` R5 chose planner emission as the population source. That emission path was never built.
- **Live cost of an empty capability.**
  - The production graph still wires the port (`worker/graph_lifecycle.py:279,746`).
  - The vault reader queries an always-empty queue view on every turn (`graph/nodes/vault_reader.py:128-156`).
  - The checkpointed `current_task_id` channel exists only for this tool (`thread/state.py:298-302`).

## Considered options

- **Wire a producer.** This would build planner-emitted rows and bind the tool to real lanes. Rejected: no current workflow needs it, and plan sequencing already belongs to vaultspec plans on the engine side. Building a producer is new scope with no requirement.
- **Leave the subsystem dormant.** Rejected: it keeps the plumbing and a fixture-only preset, which the remediation mandate drops.
- **Retire the capability and drop the table.** Chosen.

## Constraints

- The agent task queue is not a product capability. No graph, worker, provider, preset, setting or repository code builds, binds, dispatches or reads it.
- A new Alembic revision drops `task_queue_entries`. Revision 0006 stays unchanged as history.
- `current_task_id` leaves `TeamState`. A checkpoint written before the change that carries the key must still load. That checkpoint is never read as a queue.
- The deterministic lane loses its task-queue tool-call scenario, and both `deterministic-tool-call` presets are removed. The other deterministic scenarios are unaffected.
- The `task_queue_pending_horizon` setting (`domain_config.py:191-196`) and its `.env.example` entry are removed.
- A future task-sequencing capability needs a new decision that names a producer and a live test that drives it end to end. It does not revive this schema by default.

## Implementation

We will remove the agent task-queue subsystem end to end.

- **Persistence.** Delete `database/task_queue_repository.py`, `TaskQueueEntryModel` (`database/models.py:969-1020`), their facade exports and `TaskQueueStatus` (`thread/enums.py:251`).
- **Graph and worker.** Delete `graph/tools/task_queue.py`, `worker/task_queue_port.py`, and `QueueEntryView` and `TaskQueuePort` in `graph/protocols.py`. Remove the rest of the queue code:
  - the dispatch in `graph/nodes/_worker_tool_calls.py`;
  - the queue view in `graph/nodes/vault_reader.py`;
  - the port parameter in `graph/compiler.py`, `graph/_compiler_topologies.py`, `graph/nodes/worker.py` and `worker/graph_lifecycle.py`.
- **Fixtures.** Delete the fixture scenario in `providers/deterministic_chat_model.py` and both presets.
- **Schema.** Add the revision that drops the table. It may share a revision with other remediation schema drops; the grouping is left to implementation.
- **Inventory.** R3-F3's deletion inventory in `2026-10-06-codebase-remediation-audit` lists every file and symbol. Re-prove each one by zero-caller search when the work runs.
- **Proof.**
  - Every shipped preset compiles with no queue port.
  - A live deterministic run completes end to end.
  - A real checkpoint written before the change, with `current_task_id` set, loads and resumes after it.

## Rationale

A capability with no producer has no behaviour to preserve. The 2026-07-15 amendment kept the capability because the planner would emit rows. That premise is false, which invalidates the rationale for the schema: that calls for supersession, not amendment. The remediation mandate drops code the implementation does not require, and wiring a producer would be new scope without a requirement. Grounding: R3-F3 in `2026-10-06-codebase-remediation-audit`; `dead-task-queue-tool` in `2026-09-24-architecture-review-audit`.

## Consequences

- The subsystem's modules, one table, one checkpoint channel, one setting and two fixture presets are removed. Compiled graphs lose the queue port, and each turn loses an empty queue query.
- Prompts no longer receive a queue view. No shipped preset ever received rows, because no row ever existed.
- This record supersedes `2026-03-03-persistent-task-queue-schema-adr`. The R5 refinement in `2026-07-14-a2a-edge-conformance-adr` becomes historical, including its planner-emitted population, its migration 0006 schema and its preserved capability.
- Reconsider if a workflow needs durable per-run task sequencing. That needs a new decision with a producer.
- Acceptance does not mean the removal is done.
