---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:f89c3c194c8dbd53808731d5f504f0dae262ce53b5a9a3a76318f8de1f1709b1'
related: []
---
# `repository-tooling-hardening` audit: `Control event relay type-boundary review`

## Scope

Independent read-only review of the uncommitted S24 event-relay type-boundary repair in `src/vaultspec_a2a/control/event_handlers.py`. Reviewed the four-handler relay order, execution-state early route, permission journal and finite-state transitions, terminal idempotency, desktop settlement, drain release, aggregator cleanup, JSON boundaries, and narrowed exception handling. Evidence: semantic code and Vault searches; direct call-site and public aggregator inspection; `basedpyright`, `ty`, Ruff check/format, and 19 focused real SQLite/live-gateway tests all passed.

Post-repair re-review is strictly limited to `src/vaultspec_a2a/control/event_handlers.py`, `src/vaultspec_a2a/api/tests/test_internal.py`, and `src/vaultspec_a2a/control/tests/test_event_handlers.py`, plus the direct production relay caller needed to establish execution-state routing. It rechecked the previously logged terminal cleanup, duplicate projection routing, and missing direct-proofs findings. The direct focused pytest invocation collected and passed 41 cases. The production `event_handlers.py` Basedpyright lane has zero diagnostics; Ty, Ruff check, Ruff formatting, and `git diff --check` passed. The two scoped legacy test files retain 267 Basedpyright diagnostics, all outside the repaired production source lane; that lane is recorded as a boundary, not a passing gate.

## Findings

### terminal-cleanup-on-db-failure | medium | A database error bypasses terminal aggregator cleanup

`_handle_terminal_event` now deliberately allows arbitrary database failures to propagate, but `clear_thread_state` remains after the `try`/`finally`. A database exception therefore releases the drain gate in `finally` and then exits before clearing stale subscriber, buffer, ingest, emitter, permission, and sequence state for the terminal run. The prior implementation reached the cleanup after logging such an error. Preserve the required error propagation, but guarantee terminal aggregator cleanup in a cleanup path that runs before the original exception leaves the handler.

### duplicated-execution-projection-route | low | The new relay early branch is unreachable in production

`_relay_single_event` is the only production caller of `relay_event`, and it already invokes `_handle_execution_state_event` then returns for an execution-state projection. The matching branch newly added to `relay_event` is therefore not reached through any current route. This duplicates the exceptional-order authority and can diverge later. Keep one authoritative early route, or route the caller through the orchestrator without admitting execution projections to aggregation.

### unproved-narrowed-exception-contract | low | Changed error boundaries have no direct regression proof

The focused suite proves normal permission handling, terminal idempotency, and drain release, but it does not drive an invalid `snapshot_created_at` through the relay nor a genuine terminal database failure through the cleanup-and-propagation path. Add real-behavior coverage establishing that an invalid timestamp persists as absent while unrelated database failures remain observable and still perform terminal cleanup.

### terminal-cleanup-on-db-failure-resolved | medium | Cleanup now runs after drain release while database faults propagate

Post-repair source inspection confirms `clear_thread_state(thread_id)` is inside `_handle_terminal_event`'s `finally`, immediately after the idempotent `DrainGate.release(thread_id)`. The terminal write body catches only `InvalidTransitionError`; an `OperationalError` is not swallowed and leaves only after that cleanup. The real schema-less SQLite regression admits a run, creates subscriber, subscription, and sequence state, invokes the terminal handler, observes the real missing-table `OperationalError`, then proves the gate is inactive and the public aggregator has no sequence, active thread, or subscription for that run. This resolves the finding without masking database failures.

### duplicated-execution-projection-route-resolved | low | One caller-owned projection bypass is authoritative

The production caller `_relay_single_event` normalizes the payload, routes `execution_state_projection` directly to `_handle_execution_state_event`, and returns before relay or aggregation. `relay_event` has no execution-projection early branch and documents that callers route projections first. The real ASGI internal-event regression posts an invalid projection timestamp, receives `200`, proves no subscriber, subscription, or sequence state was created, and reads the persisted execution-state row with `snapshot_created_at is None`. This resolves the duplicated routing authority and binds the timestamp boundary to observable behavior.

### unproved-narrowed-exception-contract-resolved | low | Real ASGI and SQLite regressions cover the tolerated and propagated paths

The new ASGI regression drives an invalid timestamp through the public internal endpoint and proves it is stored as absent without touching relay state. The schema-less SQLite regression drives an unrelated terminal database failure and proves cleanup followed drain release while the error remained visible to the caller. No broad database exception is caught by terminal or progress transition handling; only `InvalidTransitionError` is caught around the expected finite-state transition race, while input JSON validation and timestamp parsing intentionally narrow their own input-boundary failures.

### scoped-test-basedpyright-boundary | low | Existing legacy test diagnostics keep the broader test lane non-green

A direct Basedpyright invocation over `test_internal.py` and `test_event_handlers.py` reports 267 diagnostics from their pre-existing incomplete fixture and private-access typing debt. This re-review makes no claim that those test files pass Basedpyright. The production `event_handlers.py` lane is independently clean; the 267-diagnostic test-file lane remains outside this repaired source contract.

## Recommendations

- Repair the terminal cleanup path while retaining propagation of unexpected database failures; add the corresponding real database-failure regression proof.
- Remove the duplicate execution-projection early route or centralize it at one relay authority, then prove that it bypasses aggregation exactly once.
- Add a real invalid-timestamp relay case to bind the narrowed exception boundary to its intended tolerance.
- Keep the existing 267-diagnostic scoped legacy test-file Basedpyright debt explicitly bounded until a later strict-test remediation owns it.
