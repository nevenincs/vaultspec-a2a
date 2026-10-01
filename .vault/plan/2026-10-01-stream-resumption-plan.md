---
tags:
  - '#plan'
  - '#stream-resumption'
date: '2026-10-01'
tier: L2
related:
  - '[[2026-10-01-stream-resumption-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-03-04-worker-process-architecture-adr]]'
  - '[[2026-07-19-observability-lanes-adr]]'
  - '[[2026-02-26-event-aggregation-server-side-replay-adr]]'
  - '[[2026-03-10-postgres-dual-backend-adr]]'
  - '[[2026-08-05-served-capability-contract-state-truthfulness-adr]]'
modified: '2026-10-01'
body_schema: body-v2
body_hash: 'sha256:3987230282b71d5d944cbe371f822f4b97c10a41e8cd024da8de0cda20696efe'
---

# `stream-resumption` plan

Serve a resumable progress stream: a durable per-run sequence allocated at the fan-out chokepoint, a bounded replay log, and `Last-Event-ID` resumption.

## Description

Approved 2026-10-01

Authorization basis: the user's blanket approval of this feature's implementation sequencing, given in session on 2026-10-01, together with the acceptance of the stream-resumption ADR on the same date. The user separately decided to keep the stream's one-heartbeat terminal bound rather than persist before fan-out, so allocation and the durable write sit behind the fan-out and the relay's ordering is unchanged. No further authorization is outstanding for the Steps below.

A viewer that loses its connection to a run's progress stream cannot recover the frames it missed, and the service keeps no durable record of what a run emitted. This plan closes both halves at once. The gateway allocates one monotonic per-run sequence where frames enter subscriber queues, appends each outgoing frame to a bounded per-run replay log in the application database, emits that sequence as the SSE `id:` only where its replay is served, and replays the retained rows after the snapshot when a client reconnects with a cursor. Retention is the log's own, in rows and in hours, and touches no checkpoint.

Decision coverage. One decision governs this work and it is accepted: the stream-resumption ADR, whose Implementation sections S1 to S9, Constraints, and enumerated verification are binding here. Four existing accepted decisions constrain parts of it and are linked for that reason. No new costly decision is taken by this plan, so no further ADR is owed. Evidence is inherited transitively through the governing records; the stream-resumption research and the 2026-09-24 architecture-review audit are its grounding.

Coverage map to containers:

- The stream-resumption ADR governs every Phase. Its S1, S5 and S6 land in `P01`; its S2, S3, S4 and S8 land in `P02`; its S7 lands in `P03`. Its S9 enumerates the verification each Step carries.
- The event-aggregation server-side-replay ADR governs `P01`. Its rejection of a custom event-logging database stands for conversational history and is reversed only in the bounded form built here: an append-only table of already-projected progress frames, from which nothing is reconstructed and which expires by its own retention.
- The a2a-edge-conformance ADR governs `P02` and `P03.S11`. R7 and the engine fence hold by construction, because only the already-projected frame body is persisted; R6 makes the cursor, the id and the new `run-status` field a cross-repository contract event, which `P03.S11` records.
- The worker-process-architecture ADR governs `P01.S03`: the worker-to-gateway relay carries no sequence authority, so the worker counter is demoted to a worker-local ordering aid and the gateway stamps the authoritative number.
- The observability-lanes ADR governs `P03.S10`: the replay log is a database lane, not one of the four process-kind log lanes, and is bounded by row and age retention rather than by rotation and the reaper.
- The postgres dual-backend decision is inherited transitively through the governing ADR. The table is backend-agnostic application schema under Alembic, and every Step that touches it is proved on both backends.

Two details are fixed here as routine corrections within the authorized scope, not as changes to the decision. First, the Alembic revision is named by purpose, `run_event_log`; its revision id and `down_revision` are assigned at execution in the order it merges, because other plans are adding migrations concurrently and the ADR's `0023` is only the id this revision would have taken alone. Second, the ring size and the flush cadence are the implementation hypotheses the ADR declares tunable; the ordering it fixes - allocate, ring, fan out, flush - is not.

Out of scope. The reconciliation edits the stream-resumption ADR proposes to the four older records are owned by the ADR skill and are not Steps here; this plan neither applies nor depends on them. The OpenTelemetry GenAI span model, provider-transcript linkage, and token-accounting columns remain the follow-on decision the audit names. The dashboard repository is out of scope: `P03.S11` records the contract event in the vault only.

## Steps

### Phase `P01` - durable event log and sequence authority

Delivers the durable substrate the decision rests on: the per-run event table, its repository, one gateway-side sequence allocator at the fan-out chokepoint that survives a restart, and the batched write that lands behind fan-out.

- [x] `P01.S01` - Create the run_events table with its composite thread_id and sequence primary key, projected payload column, allocation-time UTC stamp, nullable W3C trace and span ids, a created_at index for the sweep, and cascade removal with its thread, in an Alembic revision named by purpose; `src/vaultspec_a2a/database/models.py, src/vaultspec_a2a/database/migrations/versions/, src/vaultspec_a2a/database/tests/`.
- [x] `P01.S02` - Add the run-event repository: one executemany append, a replay read strictly after a cursor, the per-run high-water mark, the newest-N window trim, and the age-bounded delete, all on the application engine and never on the checkpointer connection; `src/vaultspec_a2a/database/run_event_repository.py, src/vaultspec_a2a/database/__init__.py, src/vaultspec_a2a/database/tests/`.
- [ ] `P01.S03` - Allocate one authoritative per-run sequence at the fan-out chokepoint in enqueue_payload and broadcast, seeding on first touch after a gateway start from the replay table's high-water mark, else threads.last_sequence, else zero, and demote the worker's per-thread counter to a worker-local ordering aid whose number the relay overwrites; `src/vaultspec_a2a/streaming/subscribers.py, src/vaultspec_a2a/streaming/aggregator.py, src/vaultspec_a2a/streaming/emitters.py, src/vaultspec_a2a/streaming/tests/`.
- [ ] `P01.S04` - Append each allocation to a bounded per-run ring and flush it as one batch behind the fan-out, per ingested relay batch or every 50 ms, trimming the run to its window in the same batch, degrading to the ring on a flush failure, under the new stream_replay_enabled and stream_replay_window_events settings; `src/vaultspec_a2a/streaming/run_event_writer.py, src/vaultspec_a2a/streaming/subscribers.py, src/vaultspec_a2a/api/internal.py, src/vaultspec_a2a/control/infra_config.py, src/vaultspec_a2a/streaming/tests/, src/vaultspec_a2a/service_tests/`.

### Phase `P02` - resumable stream surface

Delivers the served contract: the SSE id emitted only where replay is served, the resumption cursor on the run stream, replay after the snapshot, the gap-honest frames, and the additive run-status capability field.

- [x] `P02.S05` - Emit the SSE id as run_id colon decimal sequence on a frame whose replay is served, write no id where replay is disabled, unavailable, or outside the retained window, and replace the encoder's standing no-id rationale with the invariant it becomes; `src/vaultspec_a2a/streaming/sse_frames.py, src/vaultspec_a2a/api/thread_stream.py, src/vaultspec_a2a/streaming/tests/test_sse_frames.py`.
- [x] `P02.S06` - Accept the resumption cursor on the run stream as the Last-Event-ID header and the last_event_id query fallback with the header winning, honour the dash sentinel as the start of the retained window, close a cursor naming another run with a stream_rejected frame of reason resume_cursor_foreign_run, and regenerate the committed openapi.json; `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py, src/vaultspec_a2a/api/thread_stream.py, openapi.json, src/vaultspec_a2a/api/tests/`.
- [ ] `P02.S07` - Replay the retained rows then the unflushed ring after the snapshot and before going live, tracking the highest sequence emitted so a live frame at or below it is dropped, and closing through the existing terminal path when a terminal is reached during replay; `src/vaultspec_a2a/api/thread_stream.py, src/vaultspec_a2a/api/tests/test_stream_session_scope.py, src/vaultspec_a2a/api/tests/`.
- [ ] `P02.S08` - Emit exactly one bounded resynchronization frame when a resume cannot be served completely, carrying progress_dropped reason replay_window_exceeded with the first sequence it can serve, or reason replay_unavailable, and never present a short replay as a complete one; `src/vaultspec_a2a/api/thread_stream.py, src/vaultspec_a2a/api/tests/`.
- [x] `P02.S09` - Serve the additive run-status boolean stream_resumable from the served switch and the run's retained rows so a consumer can tell the two postures apart without probing, and regenerate the committed openapi.json; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py, openapi.json, src/vaultspec_a2a/api/tests/`.

### Phase `P03` - retention, operations, and the contract event

Delivers the bounds and the announcement: the age sweep that is independent of checkpoint retention in both directions, and the vault record of the cross-repository contract event the dashboard is told about before release.

- [x] `P03.S10` - Sweep the replay log on its own bounds under the new stream_replay_retention_hours setting, deleting rows of runs settled longer ago than the bound and rows of any run older than it from a gateway background task, reading and deleting no checkpoint; `src/vaultspec_a2a/database/run_event_retention.py, src/vaultspec_a2a/api/app.py, src/vaultspec_a2a/control/infra_config.py, src/vaultspec_a2a/database/tests/`.
- [x] `P03.S11` - Record the cross-repository contract event as a vault reference under this feature, naming the id on run-stream frames, the honoured Last-Event-ID cursor and its query fallback, the two new progress_dropped reasons, the new stream_rejected reason, and the run-status stream_resumable field; the dashboard repository is out of scope here; `.vault/reference/`.

## Parallelization

`P01` is strictly sequential and is the hard prerequisite for the rest: `S01` creates the table `S02` reads and writes, `S02` supplies the high-water-mark read `S03` seeds from, and `S04` is the first writer, which is what makes `S03`'s seeding true across a real restart. Nothing in `P02` or `P03.S10` may start before `P01.S04` closes.

Once `P01` closes, three assignments run concurrently with disjoint write ownership.

- Assignment A, `P02.S05` through `P02.S09`, in that order. Owns `src/vaultspec_a2a/streaming/sse_frames.py`, `src/vaultspec_a2a/api/thread_stream.py`, `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`, `src/vaultspec_a2a/api/schemas/gateway.py`, `openapi.json`, and `src/vaultspec_a2a/api/tests/`. The five Steps are not parallel with each other: every one of them edits `src/vaultspec_a2a/api/thread_stream.py` or the committed `openapi.json`, so they share one owner and one order.
- Assignment B, `P03.S10` alone. Owns `src/vaultspec_a2a/database/run_event_retention.py`, `src/vaultspec_a2a/api/app.py`, `src/vaultspec_a2a/control/infra_config.py`, and `src/vaultspec_a2a/database/tests/`. It shares no file with Assignment A. It follows `P01.S04` because that Step is the other writer of `src/vaultspec_a2a/control/infra_config.py`.
- Assignment C, `P03.S11` alone. Owns `.vault/reference/` and no source file, so it may start as soon as the ADR is accepted and may run beside `P01` as well.

Assignments A and B commit into the same repository. Isolate their working trees, or serialize their commits; neither may stage a path the other owns.

## Verification

Every Step carries a real-behaviour test that fails before its change and passes after it, against the real gateway, a real uvicorn process, and a real database. No mocks, no monkeypatching, no skip or expected-failure marker. Every Step closes only when `just ci` passes on the worktree.

Per-Step proofs, which together are the enumerated verification the governing ADR requires:

- `P01.S01` - the migration upgrades and downgrades on SQLite and on PostgreSQL; a repeated insert of the same `(thread_id, sequence)` is refused by the primary key rather than duplicating a frame; deleting a thread removes its rows.
- `P01.S02` - the repository appends a batch, reads strictly after a cursor in sequence order, reports the per-run high-water mark, trims a run to its newest N, and deletes by age, on SQLite and on PostgreSQL; a replay read releases its pooled connection before returning.
- `P01.S03` - two frames from different producers on one run receive consecutive numbers from one counter; an allocator constructed over a run whose rows already exist continues from the stored maximum, falls back to `threads.last_sequence` when no row exists, and disables ids for the run when neither can be read rather than restarting the numbering.
- `P01.S04` - a gateway restarted mid-run continues the sequence instead of restarting it, asserted across the restart boundary on a live gateway; a frame reaches a subscriber before its row is durable, so the fan-out is provably not delayed by the write; a flush failure degrades to the ring and is logged with a count; an authoring-shaped run leaves no stored payload containing a prompt, a document body, an edit diff, or a per-role actor token.
- `P02.S05` - a frame carries `id: {run_id}:{sequence}` while replay serves it, and no frame carries an id when the feature is switched off or the run has no retained rows.
- `P02.S06` - the header and the query parameter are both accepted, the header wins when both are present, the `-` sentinel starts at the retained window, a cursor naming another run closes the stream with `stream_rejected` reason `resume_cursor_foreign_run` and replays nothing, and the committed `openapi.json` matches the live application.
- `P02.S07` - a connection killed mid-run and reconnected with the id it last received yields, over the union of both connections, every sequence to the terminal with no gap and no duplicate; the replay read does not hold a pooled connection for the life of the stream.
- `P02.S08` - a window set small enough to be overrun yields exactly one `replay_window_exceeded` frame naming the first sequence served, followed by contiguous frames; a store that cannot serve the replay yields `replay_unavailable`.
- `P02.S09` - `run-status` reports `stream_resumable` true for a run with retained rows and false when the feature is off, and the committed `openapi.json` matches the live application.
- `P03.S10` - the sweep deletes a settled run's replay rows while `prune_settled_checkpoints` leaves them untouched, and the checkpoint prune runs without the sweep deleting a checkpoint; both directions are asserted in the same test module.
- `P03.S11` - the reference record names every changed wire element and passes `vaultspec-core vault check all`.

Suite-level criteria:

- `just ci` passes.
- The PostgreSQL proofs run with `VAULTSPEC_A2A_TEST_POSTGRES_URL` exported and `--require-prerequisite=postgres` passed, so a missing server fails the run instead of silently skipping the backend half of the evidence.
- `src/vaultspec_a2a/api/tests/test_openapi_artifact.py` passes at every Step that changes the served surface, with the artifact regenerated by its own documented command rather than hand-edited.
- `vaultspec-core vault check all` and `vaultspec-core vault plan check` report no error for this plan and its records.

The plan is complete when every Step is closed and the final cohesive review passes. Review runs at each Phase close and at plan close, per the vaultspec system section; coincident plan-close and handoff gates share one review.
