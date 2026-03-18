# `#84` Execution-State Projection Plan

## Summary

This plan closes the remaining `#68` repair-truth gap by adding a worker-owned,
durable execution-state projection for truthful `StateSnapshot.next` and
`StateSnapshot.tasks` reconstruction.

The design is locked:

- LangGraph runtime state remains authoritative for execution truth.
- The worker remains the only process that inspects compiled graph state.
- The gateway persists a latest-row normalized execution-state read model.
- The reconnect API exposes a normalized frontend-safe execution-state surface.
- Raw gateway-side `CheckpointTuple` parsing must not be extended to invent
  `tasks` or `next`.

The first implementation action, once out of Plan Mode, is to persist this plan
into `docs/plans/`.

## Implementation Changes

### 1. Durable latest execution-state read model

Add one dedicated app-owned table for the latest normalized execution state per
thread.

Required table shape:

- `thread_id` as primary key and foreign key to `threads.id`
- `checkpoint_id`
- `parent_checkpoint_id`
- `snapshot_created_at`
- `recorded_at`
- `recovery_epoch`
- `task_count`
- `interrupt_count`
- `next_nodes_json`
- `interrupt_types_json`
- `tasks_json`
- `degraded_reasons_json`

Required storage rules:

- use JSON-encoded `Text` columns, not backend-native `JSON`
- store only normalized serializable summaries, not raw LangGraph objects
- keep one latest row per thread, updated in place
- do not duplicate LangGraph historical state in the app DB

Required persistence helpers:

- `record_thread_execution_state(...)`
- `get_thread_execution_state(...)`
- optional `delete_thread_execution_state(...)`

### 2. Worker-owned runtime projection

Extend the worker so it publishes normalized execution-state truth derived from
LangGraph runtime state.

Required behavior:

- inspect runtime state from the worker using `graph.aget_state(config)`
- normalize `StateSnapshot.next`, `StateSnapshot.tasks`, and
  `StateSnapshot.interrupts`
- emit a new internal event payload type such as `execution_state_projection`
- send that event through the existing `/internal/events/batch` path
- do not overload heartbeat for this data
- do not compile graphs in the gateway

Required normalized task shape:

- `task_id`
- `name`
- `path`
- `has_error`
- `error_type`
- `interrupt_ids`
- `interrupt_types`
- `has_nested_state`
- `has_result`

Emission points:

- after graph runs where the worker already inspects interrupts
- after resume flows as well as initial ingest flows
- on any state read failure, emit an explicit degraded projection event instead
  of silently skipping

### 3. Gateway persistence and snapshot enrichment

Teach the gateway internal event handler to persist execution-state projections
and use them during reconnect snapshot assembly.

Required gateway behavior:

- validate and persist `execution_state_projection` events in `api/internal.py`
- enrich `ThreadStateSnapshot` from the durable latest execution-state row
- add normalized execution-state fields to the public snapshot contract:
  - `next_nodes`
  - `task_count`
  - `pending_interrupt_count`
  - `execution_tasks`
- keep these normalized and frontend-safe; do not expose raw LangGraph
  `PregelTask` or `StateSnapshot`

Freshness rules are locked:

- if checkpoint exists and no execution-state row exists: degrade with
  `execution_state_projection_missing`
- if execution-state `checkpoint_id` differs from latest checkpoint: degrade
  with `execution_state_projection_stale`
- if execution-state `recovery_epoch` differs from current thread
  `recovery_epoch`: degrade with `execution_state_projection_stale`
- if checkpoint truth is unavailable, checkpoint degradation remains primary;
  execution-state rows do not override missing checkpoint truth

Replay/snapshot semantics:

- `snapshot_complete` must become `false` when execution-state truth is missing
  or stale while checkpoint truth exists
- `degraded_reasons` must include execution-state-specific reasons explicitly
- `replay_status` behavior should remain consistent with current checkpoint
  durability rules

### 4. Projection boundaries and authority rules

These constraints are mandatory and should be treated as implementation
invariants:

- do not infer `tasks` or `next` from raw `CheckpointTuple`
- do not move graph compilation or graph ownership into the gateway
- do not use worker pull-only state reads as the sole source of reconnect truth
- do not store raw `PregelTask.result`, raw nested task state, or arbitrary
  exception objects as durable frontend truth
- do not duplicate LangGraph checkpoint history in the app DB

A supplemental worker read endpoint may be added later, but only as an optional
freshness aid, not as the primary or only authority.

## Public API / Interface Changes

### `ThreadStateSnapshot`

Add:

- `next_nodes: list[str]`
- `task_count: int`
- `pending_interrupt_count: int`
- `execution_tasks: list[ExecutionTaskSnapshot]`

Add normalized component type:

- `ExecutionTaskSnapshot`
  - `task_id: str`
  - `name: str`
  - `path: list[str]`
  - `has_error: bool`
  - `error_type: str | None`
  - `interrupt_ids: list[str]`
  - `interrupt_types: list[str]`
  - `has_nested_state: bool`
  - `has_result: bool`

Degradation additions:

- `execution_state_projection_missing`
- `execution_state_projection_stale`

### Internal worker event contract

Add a new worker-emitted event type:

- `type: "execution_state_projection"`

Payload fields:

- `checkpoint_id`
- `parent_checkpoint_id`
- `snapshot_created_at`
- `next_nodes`
- `interrupt_types`
- `interrupt_count`
- `task_count`
- `tasks`
- `degraded_reasons`
- `recovery_epoch`

This remains an internal transport shape, not a frontend-facing event.

## Test Plan

### Unit / integration

Add tests for:

- runtime `StateSnapshot` normalization into execution-state payloads
- persistence of latest-row execution-state updates
- snapshot enrichment from persisted execution-state truth
- freshness classification by checkpoint mismatch
- freshness classification by recovery-epoch mismatch
- degraded snapshot behavior when execution-state projection is missing
- migration creation and downgrade for the new table on both SQLite and
  Postgres

### Live verification

Add live Postgres scenarios for:

- paused thread restart where reconnect snapshot exposes durable `next_nodes`
  and normalized pending task truth
- running thread restart where stale execution-state rows are detected
  explicitly
- cancelling thread restart where snapshot remains truthful and degradation is
  explicit if execution-state projection lags
- worker restart after projection emission, proving the gateway can still serve
  the latest durable execution-state row
- checkpoint available but execution-state projection absent, proving degraded
  reconnect semantics rather than false completeness

### Review requirements

After implementation:

- run targeted tests for migrations, internal event handling, snapshot
  enrichment, and live recovery
- run a code review pass focused on authority drift
- update:
  - `docs/research/2026-03-09-postgres-persistence-grounding.md`
  - `docs/audits/2026-03-08-continuous-backend-readiness-audit.md`
  - `docs/audits/2026-03-08-prod-readiness-consolidated-audit.md`

## Assumptions and Defaults

- Postgres remains the certifying backend; SQLite compatibility is preserved
  but not treated as production proof.
- The first slice stores only the latest execution-state projection row per
  thread.
- LangGraph checkpoint history remains the only historical execution authority.
- The worker already has the correct authority boundary for runtime state
  inspection.
- The first execution step, once implementation mode resumes, is to persist
  this plan into `docs/plans/` verbatim before code changes begin.
