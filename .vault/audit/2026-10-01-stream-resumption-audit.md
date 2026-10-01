---
tags:
  - '#audit'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:2bd77e321330c86bcf1ca0f21f9868de8abe02def350c9ae640962708651537d'
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

Closed unreproduced by the plan-close review (6 serial runs and 10 boots under five-way contention passed); re-raised as `restart-test-leaks-a-read-only-sqlite-connection`. `test_a_gateway_serving_no_replay_retains_nothing[false]` in `src/vaultspec_a2a/api/tests/test_stream_sequence_restart.py` failed once in a three-worker run of the database, streaming and API suites on the integrated tree and passed alone and in a full three-worker API re-run; the failure text was not kept. It spawns a real gateway and posts a worker batch, so a boot or request timeout under CPU contention is the likely cause, not a root cause. The next full gate either reproduces it with its error or it is closed.

### replay-writer-poisoned-by-a-deleted-run | critical | one run delete permanently stops the replay log for every run on the gateway

Open; plan-close review, reopens P01.S04. `RunEventWriter.flush` (`src/vaultspec_a2a/streaming/run_event_writer.py:145-175`) builds one `executemany` across every tracked run and treats any failure as transient, while `_idempotent_insert` (`src/vaultspec_a2a/database/run_event_repository.py:131-155`) absorbs a primary-key conflict but not a foreign-key violation. Deleting a run (`src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:775-785`) clears the allocator but not the writer's ring (`src/vaultspec_a2a/streaming/subscribers.py:400-406`), so a frame produced inside the last flush interval points at a thread that no longer exists. Proven against a real migrated SQLite store: three consecutive flushes wrote nothing with `FOREIGN KEY constraint failed` and a healthy run's frames never reached the table; it clears only on restart or after 64 other runs evict the poisoned ring. Repair: scope a flush failure to the failing run and drop a removed run's ring.

### sequence-reused-when-a-run-is-forgotten-before-its-flush | high | the terminal path resets a run's counter below what it already allocated

Open; plan-close review, reopens P01.S03. `forget()` drops the counter and the next `seed()` re-reads the flushed high-water mark, which cannot see the writer's unflushed ring (`src/vaultspec_a2a/streaming/subscribers.py:111-165`). The terminal relay clears thread state inside `_relay_single_event` (`src/vaultspec_a2a/control/event_handlers.py:719`) before the batch flush (`src/vaultspec_a2a/api/internal.py:234,247,481-482`), so progress, terminal, then one more frame in one batch allocated sequence 1 twice; the second row is discarded by the idempotent insert and a live viewer's de-dup drops it. Breaks the decision's "monotonic per run, never reused" constraint. `test_a_forgotten_run_reseeds_from_the_durable_mark` retains the rows before forgetting, which is the one state where reseeding is safe. Repair: seed from the higher of the durable mark and the ring, or keep a run with unflushed allocations.

### concurrent-seed-resets-the-counter | high | two first touches of one run both write the seed, rewinding the allocator

Open; plan-close review, reopens P01.S03. `seed()` tests membership before two awaited store reads and then assigns unconditionally (`src/vaultspec_a2a/streaming/subscribers.py:118-137`); two concurrent first touches fanned six frames out under sequences `[1,2,3,1,2,3]` with three durable rows. Reachable from a worker bridge retry re-posting a batch the gateway is still processing, or the WS and HTTP ingest paths live together. `SubscriberManager._lock` is declared and unused. Repair: re-check after the awaits or serialize the seed per run.

### cursor-past-the-high-water-mark-silences-the-stream | high | a resume above the run's mark is reported complete and then suppresses every live frame

Open; plan-close review, reopens P02.S07 and P02.S08. `_empty_replay_window` (`src/vaultspec_a2a/api/thread_stream.py:484-511`) never compares the cursor to the run's high-water mark, so a cursor above it yields an empty window with no gap reason, and `highest_emitted` is seeded from the client's value (`:628,718-730`), dropping every live frame at or below it. Proven over a real uvicorn server: a resume at `{run}:5000` on a run holding three frames served the snapshot, no `progress_dropped`, and then nothing until the client timed out. The drop-site comment states an invariant the code does not hold. Repair: answer a cursor ahead of the mark with a gap reason and clamp the de-dup mark to what this stream emitted.

### run-status-takes-a-second-pooled-connection-per-call | medium | the hottest read endpoint now holds two connections at once

Open; plan-close review, in-scope correction for P02.S09. `_stream_is_resumable` (`src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:291-326,377`) opens a factory-bound session while the request-scoped session is held, halving `run-status` pool concurrency for an additive boolean. Repair: probe `MAX(sequence)` on the request-scoped session.

### ws-relay-path-is-unproven-and-carries-a-dead-collaborator | medium | the relay context's replay recorder is never read and no test covers WS retention

Open; plan-close review, in-scope correction for P01.S04; supersedes the integration note in `relay-context-merged-with-the-prune-registry`. `_RelayContext.replay` is populated (`src/vaultspec_a2a/api/internal.py:287`) and read nowhere; the WS relay relies on the writer's 50 ms ticker, which works but has no test, and that cadence widens the forget window above. Repair: flush the WS path through the context per ingested group, or remove the field and prove WS retention.

### restart-test-leaks-a-read-only-sqlite-connection | low | the suspected flake's test opens a WAL reader it never closes

Open; plan-close review, replaces `restart-test-failed-once-under-load`. `with sqlite3.connect(...)` commits but does not close (`src/vaultspec_a2a/api/tests/test_stream_sequence_restart.py:118-126`), so a read handle on the WAL database survives the first gateway's reap and the second boot; on Windows that can block recovery and would read as an intermittent readiness failure. The single-value `parametrize("enabled", ["false"])` (`:211`) claims both directions in its docstring. Repair: `contextlib.closing`, and fix the parametrize or its docstring.

### replay-retention-setting-missing-from-env-example | low | operators cannot discover the retention bound

Fixed as a P03.S10 correction: the line was added beside the other two, and the env-example coverage gate, which failed on the integrated tree, passes. Original finding: `.env.example:272-280` documented the replay switch and window but not `VAULTSPEC_A2A_STREAM_REPLAY_RETENTION_HOURS`, which P03.S10 added. Repair: add the entry.

### relay-payload-promises-a-return-it-never-makes | low | the documented stamped payload is always None

Open; plan-close review. `relay_payload` (`src/vaultspec_a2a/streaming/subscribers.py:445-467`) is annotated `-> object` and documents a stamped return but has no `return`; the aggregator (`src/vaultspec_a2a/streaming/aggregator.py:206-208`) forwards the `None`. No caller reads it. Repair: return the payload or restore `-> None` and the docstrings.

### an-unstampable-frame-still-burns-a-sequence | low | a declined frame leaves a permanent hole that costs the older window

Open; plan-close review. A number is allocated before the `Mapping` check (`src/vaultspec_a2a/streaming/subscribers.py:456-460`) and the projector declines unshapable frames (`src/vaultspec_a2a/api/_replay_writer_seat.py:43-57`), so `_contiguous_tail` (`src/vaultspec_a2a/api/thread_stream.py:408-424`) discards every retained frame older than the hole. Repair: allocate only for a retainable frame, or keep the sequence space contiguous.

### contract-reference-misattributes-backpressure-gaps | low | the dashboard record ties the wrong notice to the wrong mechanism

Open; plan-close review. The contract reference says backpressure drops leave gaps the resume reasons disclose; backpressure drops happen after allocation and recording, so those frames are retained and replayed, and they are disclosed live by the existing `progress_dropped` reason `backpressure` (`src/vaultspec_a2a/api/thread_stream.py:225-244`). Repair: separate the two mechanisms in the reference.

### plan-does-not-link-two-governing-decisions | low | coverage of two governing decisions is argued in prose rather than linked

Fixed at review intake: `2026-03-10-postgres-dual-backend-adr` and `2026-08-05-served-capability-contract-state-truthfulness-adr` linked to the plan.

### unnumbered-run-with-replay-enabled-untested | low | no test withholds the id from an unnumbered run while replay is on

Open; plan-close review, found by inversion. Only the replay-switched-off direction of the id invariant is covered; an unnumbered run with replay enabled, the state the forget defect creates, is not. Repair: add the proof with the P01.S03 repair.

## Recommendations

- Re-tier `src/vaultspec_a2a/streaming/tests/` so a database-backed test is not marked unit (`streaming-tests-marked-unit-use-a-database`).
- Make P02.S07's reader union rows and ring by sequence, with a test that flushes mid-read (`replay-reader-must-union-by-sequence`).
- Repair the numbering identity and its durable write in the reopened Steps, in order: seed and forget (P01.S03), flush scoping and ring ownership (P01.S04), cursor validation (P02.S07, P02.S08); per-run flush batching and serving `stream_resumable` from the request session sit within the decision's tuning latitude and are execution choices.
