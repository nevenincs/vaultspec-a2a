---
tags:
  - '#research'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:959a0bbd1057ab56c05429884466e58349fe9c7b806062df895ee8e0b332099e'
related:
  - "[[2026-08-02-clarification-continuation-implementation-review-audit]]"
---

# `control-action-leases` research: `atomic dispatch ownership and recovery`

Five control paths reserve intent in durable state but dispatch before that
reservation is committed or use a non-atomic metadata claim. The evidence favors
one reusable database lease over per-feature locks: it can elect one dispatcher,
preserve accepted payload and dispatch identity across lost acknowledgements, and
reconcile application from checkpoint or worker progress without duplicating the
journal model.

## Findings

### A committed lease must precede every external dispatch

Clarification performs checkpoint-read then dispatch with no durable election.
Permission, message, and cancel first look up a journal key, create an uncommitted
row, and then call the worker. Separate sessions can therefore pass the lookup
together. Evidence: `src/vaultspec_a2a/api/routes/gateway.py:1952`,
`src/vaultspec_a2a/control/permission_service.py:403`,
`src/vaultspec_a2a/control/message_service.py:115`, and
`src/vaultspec_a2a/control/cancel_service.py:173`.

### The existing journal has atomic identity but lacks renewable ownership

`ControlActionModel` already enforces unique `(thread_id, idempotency_key)`, and
`get_or_create_control_action` resolves concurrent unique-key insertion with a
savepoint. It has no claim token, expiry, or stable persisted dispatch identity,
so it cannot elect a recovery attempt. Evidence:
`src/vaultspec_a2a/database/models.py:270` and
`src/vaultspec_a2a/database/permission_repository.py:247`.

### The verdict metadata lease is not a multi-writer election

The verdict subscriber reads a whole metadata blob and later writes a merged blob
without a conditional update. Its safety depends on one serialized writer; copying
it into HTTP request handling would preserve the race. Evidence:
`src/vaultspec_a2a/control/verdict_subscriber.py:678` and
`src/vaultspec_a2a/database/thread_repository.py:593`.

### Worker acceptance is not application evidence

The worker returns after scheduling a background task, before the executor acquires
the per-thread slot or LangGraph consumes the resume. A dispatch lease must remain
pending until checkpoint state or worker progress proves application. Evidence:
`src/vaultspec_a2a/worker/app.py:222` and
`src/vaultspec_a2a/worker/executor.py:598`.

### Clarification needs an unambiguous checkpoint receipt

Answer resolution leaves request-keyed answer state, but a prompt leaves only prose
in the transcript. A request-id and fingerprint receipt in graph state supplies
durable application proof without persisting a second copy of prompt text. Evidence:
`src/vaultspec_a2a/graph/nodes/clarification.py:359` and
`src/vaultspec_a2a/thread/state.py:170`.

### Restart recovery currently overlooks clarification interrupts

Startup reconciliation derives resumable pauses from durable permission rows, while
clarifications live only in the checkpoint projection. A restart can misclassify the
run and send an ingest the worker intentionally skips. Evidence:
`src/vaultspec_a2a/lifecycle/reconciliation.py:45`,
`src/vaultspec_a2a/control/projection.py:321`, and
`src/vaultspec_a2a/worker/executor.py:482`.

### A dedicated clarification table would duplicate shared machinery

A feature-specific row can model resolution lifecycle precisely, but permission,
message, cancel, and verdict still need the same atomic election. Extending the
generic control action with lease fields lets one primitive govern every caller;
clarification-specific application truth remains in its checkpoint receipt.

## Sources

- `src/vaultspec_a2a/api/routes/gateway.py:1952`
- `src/vaultspec_a2a/control/permission_service.py:403`
- `src/vaultspec_a2a/control/message_service.py:115`
- `src/vaultspec_a2a/control/cancel_service.py:173`
- `src/vaultspec_a2a/database/models.py:270`
- `src/vaultspec_a2a/database/permission_repository.py:247`
- `src/vaultspec_a2a/control/verdict_subscriber.py:678`
- `src/vaultspec_a2a/database/thread_repository.py:593`
- `src/vaultspec_a2a/worker/app.py:222`
- `src/vaultspec_a2a/worker/executor.py:598`
- `src/vaultspec_a2a/graph/nodes/clarification.py:359`
- `src/vaultspec_a2a/thread/state.py:170`
- `src/vaultspec_a2a/lifecycle/reconciliation.py:45`
- `src/vaultspec_a2a/control/projection.py:321`
- `src/vaultspec_a2a/worker/executor.py:482`
