---
tags:
  - '#audit'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:c211d3aaf4f517c2083d5cf197243ffd5167620e90f5c44ad0f4375890b1787e'
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

Fixed in P02.S07: the reader merges durable rows and the ring into one map keyed by sequence, durable row winning (`src/vaultspec_a2a/api/thread_stream.py`, `_retained_after`); the overlap is permanent for any flushed window, not momentary, because a flush advances a mark and does not drain the ring. Original finding: between the store committing an append and the flush advancing the run's mark, one sequence is present in both the durable rows and `RunEventWriter.pending()`. The replay reader must union by sequence, not concatenate, or a resumed client sees that frame twice.

### mid-window-hole-on-ring-overflow | low | a ring overflow or eviction loses a durable row in the middle of a run's window

Fixed in P02.S08 with no new reason: the replay window is cut to its longest contiguous tail before anything is sent, so a hole moves the served start past it and `replay_window_exceeded` with `first_sequence` describes it exactly, at the cost of discarding retained frames older than the hole; a real ring overflow leaving rows [1, 2, 9, 10, 11, 12] proves it. Original finding: when production outruns the flush cadence for a whole ring (512 frames on one run within 50 ms) or a run with unflushed frames is evicted from the 64-run cache, the live frame is delivered but its durable row is lost; both cases log a counted warning. The ADR's gap frames describe a window that starts late or is unavailable, not a hole in its middle, so P02.S08 must decide whether a hole needs its own honest reason.

### relay-context-merged-with-the-prune-registry | info | the replay recorder and the per-app prune registry were integrated by hand

Recorded at integration. P01.S04 and architecture-review P06.S42 both reshaped the gateway relay context in `src/vaultspec_a2a/api/internal.py`; the merge gives `_RelayContext.of(app, agg, transport, replay=...)` both collaborators, and the websocket relay passes the seated recorder without a per-frame flush, relying on the writer's cadence as P01.S04 wrote it.

### unused-symbol-gate-red | medium | the unused-symbol gate reports six symbols and one orphaned test module

Open; raised by the P02 executor. The harness's unused-symbol coverage reports `control/health.py`, `control/repair_transitions.py`, `control/thread_service.py`, `graph/nodes/supervisor.py`, `lifecycle/procs_config.py`, `lifecycle/singleton.py` and an orphaned `testing/tests/test_children.py`. None is in a file this phase touched, but the gate fails `just ci` until each is used, removed or justified.

### replay-expiry-reads-updated-at | low | settled-run replay expiry is measured from the thread's last update

Recorded from P03.S10. The schema has no settle time, so the settled-run sweep reads `threads.updated_at`; a repair write on a settled run refreshes it and defers that run's replay expiry by the bound. The age clause still collects the rows.

### fresh-run-resume-reads-unavailable | info | resuming a run that has produced nothing yet is answered as replay unavailable

Recorded from P02.S08. Truthful, but a brand-new run and a swept run are indistinguishable from the frame.

### live-terminal-dropped-at-the-cursor | info | a terminal whose sequence the cursor already names closes through the heartbeat fallback

Recorded from P02.S07. If a run settles between the attachment state read and the live loop and the client's cursor already names the terminal, the live terminal is dropped as already seen and the stream closes on the existing one-heartbeat durable-terminal path; documented at the drop site.

### restart-test-failed-once-under-load | low | the replay-off restart test failed once in a three-worker run

Open. `test_a_gateway_serving_no_replay_retains_nothing[false]` in `src/vaultspec_a2a/api/tests/test_stream_sequence_restart.py` failed once in a three-worker run of the database, streaming and API suites on the integrated tree and passed alone and in a full three-worker API re-run; the failure text was not kept. It spawns a real gateway and posts a worker batch, so a boot or request timeout under CPU contention is the likely cause, not a root cause. The next full gate either reproduces it with its error or it is closed.

## Recommendations

- Re-tier `src/vaultspec_a2a/streaming/tests/` so a database-backed test is not marked unit (`streaming-tests-marked-unit-use-a-database`).
- Make P02.S07's reader union rows and ring by sequence, with a test that flushes mid-read (`replay-reader-must-union-by-sequence`).
