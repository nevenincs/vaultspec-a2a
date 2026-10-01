---
tags:
  - '#audit'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:57c93df8011fbcecb10673356fd637402f292c31c3721d7a13e7277e039ac138'
related:
  - "[[2026-10-01-stream-resumption-plan]]"
---

# `stream-resumption` audit: `execution of the durable event log and sequence authority`

## Scope

Findings raised while executing Phase P01 of `2026-10-01-stream-resumption-plan` (P01.S01-S04) under `2026-10-01-stream-resumption-adr`, and by the orchestrator's integration of those commits. Rolling: later Phases append here.

## Findings

### postgres-incremental-migration-refused-past-0017 | high | a PostgreSQL store at revision 0017 or later could take no further migration

Fixed in P01.S01. The write-authority schema fingerprint folds `btrim(` but not `TRIM(BOTH FROM ...)`, which is how PostgreSQL 16 reflects a `trim()` in a CHECK predicate, so the migration environment's current-only-head guard refused every incremental upgrade and downgrade on PostgreSQL with "cannot migrate a store without complete current write authority". A fresh database still reached head in one invocation, which is why no test caught it: nothing had run an incremental Alembic step against PostgreSQL past 0017. One fold in `src/vaultspec_a2a/database/write_authority_schema.py` fixes it, and the dual-backend upgrade-and-downgrade proof of `0023_run_event_log` now holds it.

### streaming-tests-marked-unit-use-a-database | medium | the streaming test directory is marked unit although its tests do I/O

Open. `src/vaultspec_a2a/streaming/tests/conftest.py` marks every test in the directory `core` and `unit`, and `unit` is documented as no I/O, no database and no HTTP; `test_ingest_durability.py` already used a real SQLite saver and the new replay tests drive a real migrated SQLite file. Re-tiering moves tests other Steps depend on, so it needs its own Step.

### replay-reader-must-union-by-sequence | medium | the durable rows and the writer's ring overlap by one sequence during a flush

Open, owned by P02.S07. Between the store committing an append and the flush advancing the run's mark, one sequence is present in both the durable rows and `RunEventWriter.pending()`. The replay reader must union by sequence, not concatenate, or a resumed client sees that frame twice.

### mid-window-hole-on-ring-overflow | low | a ring overflow or eviction loses a durable row in the middle of a run's window

Open, for P02.S08. When production outruns the flush cadence for a whole ring (512 frames on one run within 50 ms) or a run with unflushed frames is evicted from the 64-run cache, the live frame is delivered but its durable row is lost; both cases log a counted warning. The ADR's gap frames describe a window that starts late or is unavailable, not a hole in its middle, so P02.S08 must decide whether a hole needs its own honest reason.

### relay-context-merged-with-the-prune-registry | info | the replay recorder and the per-app prune registry were integrated by hand

Recorded at integration. P01.S04 and architecture-review P06.S42 both reshaped the gateway relay context in `src/vaultspec_a2a/api/internal.py`; the merge gives `_RelayContext.of(app, agg, transport, replay=...)` both collaborators, and the websocket relay passes the seated recorder without a per-frame flush, relying on the writer's cadence as P01.S04 wrote it.

## Recommendations

- Re-tier `src/vaultspec_a2a/streaming/tests/` so a database-backed test is not marked unit (`streaming-tests-marked-unit-use-a-database`).
- Make P02.S07's reader union rows and ring by sequence, with a test that flushes mid-read (`replay-reader-must-union-by-sequence`).
