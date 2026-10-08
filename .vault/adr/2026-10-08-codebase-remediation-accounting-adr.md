---
tags:
  - '#adr'
  - '#codebase-remediation'
date: '2026-10-08'
modified: '2026-10-08'
body_schema: 'body-v2'
body_hash: 'sha256:3c8b0ba3936497f361f54dfd299d4162cce00841fa4980d79157c71cabf8470a'
related:
  - "[[2026-10-06-codebase-remediation-audit]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-03-31-database-migration-framework-adr]]"
  - "[[2026-08-04-canonical-homes-adr]]"
---

# `codebase-remediation` adr: `one accounting home, disclosed on run-history` | (**status:** `accepted`)

Accepted 2026-10-08 under the owner's 2026-10-07 delegation of ADR work for `2026-10-06-codebase-remediation-plan` ("the orchestrator amends the ADRs"; "finish all steps of the plan"). This settles owner question O3 with option (a) below, the recommendation recorded in `2026-10-06-codebase-remediation-audit`; the owner may reverse it by amendment before the run-history disclosure ships.

## Problem Statement

Token accounting is written twice and read nowhere. One extraction in the worker node feeds two sinks, and the durable one has no production reader, so a measured provider-reported fact is persisted on every turn and appears on no served surface. Beside it sits `estimated_cost`, a column with a bespoke exact-decimal type that nothing writes: both served lanes are subscription-authenticated CLI agents, the project holds no rate table for any model, and the adapter that would write it documents the omission as deliberate. A decision is needed because the fix touches a persisted schema, because the column's custom type is imported by a historical migration and cannot simply be deleted, and because the serve half is a cross-repo contract event. Grounding: R3-F14 and R2-F24 in `2026-10-06-codebase-remediation-audit`.

## Considerations

Code paths are under `src/vaultspec_a2a/`.

- **One extraction, two sinks, by design.** `_turn_token_usage` is read once and feeds both the `token_usage` state channel and the `cost_tracking` row through `CostPort` (`graph/nodes/worker.py:943-962`; the channel delta at `graph/nodes/worker.py:604-616`). Neither sink runs its own extraction.
- **The channel is not a duplicate.** `token_usage` has a live consumer in the context path, which carries it across a handoff as cumulative bookkeeping (`context/token_budget.py:144-165`).
- **The table has no production reader.** `sum_cost_by_thread` and `sum_cost_by_agent` appear outside tests only at their definitions and in the facade (`database/cost_repository.py:62-73`; `database/__init__.py:122-123,428-429`).
- **The counts are real and recently extended.** The row carries provider-reported input, output, cache-read, cache-write and reasoning counts, the last three nullable so an unreported breakdown is not stored as a measured zero (`database/models.py:796-830`; revision `0022_cost_tracking_token_breakdown`).
- **The money column is unwritten on purpose.** `SqlCostPort.record_usage` omits it, and its module says so and says why (`worker/cost_port.py:9-15,43-72`).
- **The type is load-bearing in history.** Migration `0014` imports `MoneyAmount` and `MONEY_SCALE` from the models module rather than re-spelling them (`database/migrations/versions/0014_cost_tracking_exact_money.py:18-21`), so deleting them from `database/models.py:135` breaks a historical revision.
- **Run-history is already the wide read.** It exists to report the record rather than the authority fields, and it already discloses one settled durable artifact no other surface serves, the permission decisions (`api/routes/_gateway_read_endpoints.py:418-490`; `api/schemas/gateway.py:645-676`).

## Considered options

- **(c) Status quo, write-only.** Rejected: a measurement persisted on every turn and readable nowhere is weight every later schema change still pays, and it reads to the next author as a half-built feature to finish or delete, which is how it reached three homes.
- **(b) Drop accounting.** Drop `cost_tracking`, its repository and the port. Rejected on two grounds. The counts are real provider-reported measurements, not derived estimates, and a run reviewer has no other source for them: the `token_usage` channel lives in a checkpoint that can be gone or unreachable, while the table is in the application store beside the rest of the durable record. And the capability was deliberately extended with the cache and reasoning breakdown under an approved plan, which is evidence of intent to surface it rather than of abandonment; dropping it would reverse that work on no new evidence. The honest cost of rejecting (b) is that one table and one port stay.
- **(a) One accounting home, disclosed additively on run-history (chosen).** `cost_tracking` is the single accounting home, run-history gains a `usage` reading that gives it its first production reader, the compaction channel stays, and the unwritten money surface is removed.

## Constraints

- `cost_tracking` is the single accounting home. No second durable accounting sink, and no second extraction: both sinks continue to read the one the worker already performs.
- The `token_usage` channel stays for compaction and is not an accounting surface. It is not served, and nothing reconciles it against the table.
- No fabricated price. No column records a cost the system did not measure, and a structural zero is never served as a measured zero. This is the same rule the nullable breakdown columns already follow.
- `estimated_cost` and `MoneyAmount` are removed only after a frozen copy of the type and its scale lands inside migration `0014`. A revision describes the schema at one moment and may not re-describe it from whatever the package means later, per `2026-03-31-database-migration-framework-adr`.
- The run-history addition is additive and is a contract event under R6 of `2026-07-14-a2a-edge-conformance-adr`, announced to the dashboard in batch CE2 before release.
- One concept, one home, per `2026-08-04-canonical-homes-adr`: an aggregate query that only a test reaches is not a reader.

## Implementation

We will make `cost_tracking` the single accounting home and disclose it on run-history.

- **Disclosure.** `RunHistoryResponse` gains an additive `usage` field, read through `sum_cost_by_thread` beside the existing `permission_decisions` read, and `openapi.json` is regenerated. It reports the counts the provider reported and nothing derived from them. `sum_cost_by_agent` gains a reader in the same field (per-role counts) or is deleted.
- **Money surface removed.** Drop `estimated_cost` from `CostTrackingModel`, from the aggregate projection and from the returned totals, and drop `MoneyAmount` and `MONEY_SCALE` from `database/models.py`.
- **Migration.** Freeze a copy of the type and its scale inside `0014_cost_tracking_exact_money.py` in place of the import, then drop the column in a new revision after the latest one. Migration `0026_remediation_schema_retirement` has already landed and does not touch this column, so the drop takes its own revision.
- **Channel unchanged.** `token_usage` keeps its additive reducer and its handoff reader.
- **Proof.** A live run completes and run-history reports the counts the provider reported for it; `0014` upgrades and downgrades round-trip with no import from `database.models`; and the schema-integrity check agrees with `Base.metadata` after the drop.

## Rationale

The knockout is placement, not capability. The project already measures the right quantity, already stores it in the right shape, and already has the surface whose stated job is reporting the record. What is missing is one reader, which is why three sites each look like an unfinished feature. Giving the aggregate functions a production reader is cheaper than any of the alternatives and is the only one that keeps a measurement the system genuinely takes.

Dropping the price column follows from the same standard that made the breakdown columns nullable. A column that records a measurement nobody takes is worse than an absent one, because it invites a reader to treat a structural zero as a measured zero, and a summed structural zero as a measured total. Removing it costs nothing that was ever true.

Keeping the `token_usage` channel is not an exception to the single-home rule. The channel and the table answer different questions - what this run's prompt budget has spent, and what this run cost in provider-reported tokens - and they already share one extraction, so there is no second derivation to collapse.

## Consequences

- A run reviewer can read a run's token accounting for the first time, and the aggregate functions gain their first production reader. The dashboard gains an additive field.
- A persisted column and a custom column type leave `database/models.py`, and migration `0014` becomes self-contained.
- Accepted cost: one more revision in the chain, and a frozen type copy that duplicates a deleted symbol on purpose. The duplication is the migration framework's rule, not a defect the duplication guard should flag.
- Accepted residual: accounting is disclosed on the wide read only. Run-status stays the bounded recovery snapshot and gains nothing, so a caller that wants counts pays for the wide read.
- Reconsider if a metered per-token lane is ever served. Pricing then needs a new decision naming the rate source, the currency and the rounding rule; it does not revive this column by default.
- Acceptance establishes the accounting home, not the rollout.
