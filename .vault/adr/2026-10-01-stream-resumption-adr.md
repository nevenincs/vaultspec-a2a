---
tags:
  - '#adr'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-07'
body_schema: 'body-v2'
body_hash: 'sha256:5217212021a424b97d4e82cfb46dc117cf0efef2a7bcfe8f78493a69ea0ceaea'
related:
  - "[[2026-10-01-stream-resumption-research]]"
  - "[[2026-09-24-architecture-review-audit]]"
  - "[[2026-09-24-architecture-review-research]]"
  - "[[2026-02-26-event-aggregation-server-side-replay-adr]]"
  - "[[2026-07-14-a2a-edge-conformance-adr]]"
  - "[[2026-07-19-observability-lanes-adr]]"
  - "[[2026-03-04-worker-process-architecture-adr]]"
  - "[[2026-03-10-postgres-dual-backend-adr]]"
  - '[[2026-10-06-codebase-remediation-audit]]'
  - '[[2026-10-07-codebase-remediation-sqlite-only-adr]]'
---

# `stream-resumption` adr: `durable event sequence and bounded replay for resumable progress streams` | (**status:** `accepted`)

## Problem Statement

A viewer that loses its connection to a run's progress stream cannot recover the frames it missed. It can reattach and it can re-read `run-status`, which carries run state and no progress history, so every tool call, thought, and message chunk produced while it was away is gone with no account of what was lost. The same absence has a second consequence: the service keeps no durable record of what a run emitted, so there is nothing to read after the fact, nothing for an acceptance bundle to carry, and nothing a GenAI span model could attach to. `2026-09-24-architecture-review-audit` records both halves as `stream-resumption` and `no-durable-event-log` and names the decision as owed to a follow-on ADR.

A decision is needed now because the obvious partial fix has already been tried and reverted. `P03.S17` put the worker's in-memory sequence in the SSE `id` field; the reopen removed it, because an id whose number restarts with its process promises a resumption the stream does not serve and invites a consumer to deduplicate away a restarted worker's events (`sse-id-without-resumption`). The removal was correct and it is also a standing block: no `id:` can be emitted until something makes the sequence restart-stable and holds the frames an id would resume from. Evidence and the standards picture are in `2026-10-01-stream-resumption-research`.

## Considerations

- No frame carries an SSE `id:` today, and the encoder records the two missing properties by name: a durable sequence and a replay buffer (`src/vaultspec_a2a/streaming/sse_frames.py:511-527`).
- The per-run sequence exists twice, in the worker's emitters and in the gateway's aggregator, both in process memory and independent of each other (`src/vaultspec_a2a/streaming/emitters.py:148-149,173-176,757-774`).
- A durable cursor column already exists with nothing behind it: `threads.last_sequence` is captured only at terminal settle and served by `run-status` (`src/vaultspec_a2a/database/models.py:431`, `src/vaultspec_a2a/control/event_handlers.py:684-686`, `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:337`).
- Fan-out precedes the durable write (`src/vaultspec_a2a/api/internal.py:206-207,219`) and the user has decided to keep that ordering with the stream's one-heartbeat bound rather than persist first (`terminal-fanout-before-persist`), so any replay record must be written off the fan-out path.
- Attachment already subscribes before it reads authority and leads with a snapshot (`src/vaultspec_a2a/api/thread_stream.py:244-262`), so the only thing a reconnect still lacks is the history behind its cursor.
- The SSE specification defines resumption entirely as a server-chosen `id:` and a replayed `Last-Event-ID`, with no retention obligation; the whole cost is the server's replay window (research, WHATWG section).
- The reference implementation in this stack makes resumability an explicit opt-in backed by persisted stream chunks (`stream_resumable`, Redis Streams protocol v2), and the independent store contract that converged on the same shape defaults its retention to 24 hours (research, Agent Server and store-contract sections).
- A2A guarantees snapshot-first subscription and explicitly no replay, so a resumption guarantee here is an addition above the protocol baseline (research, A2A section).
- Checkpoint history cannot serve as the replay source: the settled-history prune keeps only each namespace's latest checkpoint (`src/vaultspec_a2a/database/checkpoint_retention.py:1-20`, scheduled at `src/vaultspec_a2a/control/event_handlers.py:697`), and a progress frame is not a superstep in the first place.
- Every frame reaching a subscriber has already crossed the positive progress projection (`src/vaultspec_a2a/streaming/aggregator.py:192-201`) and is capped at 1 MiB (`src/vaultspec_a2a/streaming/sse_frames.py:84`), so a stored frame is bounded and already redacted.
- The `gen_ai.*` vocabulary is at Development stability and moved to its own repository to iterate faster than the core bar allows, so a persisted schema must not bind to it (research, OpenTelemetry section).

## Considered options

- **No resumption; snapshot plus `run-status` re-read (status quo, rejected).** Costs nothing and keeps every current property. Rejected because the gap is unbounded and unreported: a consumer is told only that frames were dropped by its own queue, never that frames were produced while it was absent, and no durable record of a run's events exists for anything else to read.
- **Gateway-side bounded in-memory replay ring keyed by a gateway-assigned sequence (rejected as the whole answer, kept as a component).** Cheap, fast, and sufficient for a brief network drop. Rejected alone because the ring and the sequence die with the gateway process, which reintroduces exactly the restart hazard that forced the `id:` removal, and because it produces no record the `no-durable-event-log` finding asks for.
- **Durable append-only per-run event rows in the application database, replayed by sequence (CHOSEN).** Survives a gateway restart, makes the sequence an identity rather than a counter, and is the same record a per-run event log needs. Costs one batched insert per ingested relay batch, one new table, and a retention sweep.
- **Reuse LangGraph checkpoint history as the replay source (rejected).** Needs no new storage. Rejected on two independent grounds: the settled-history prune removes all but the latest checkpoint exactly when a reconnecting client would need the rest, and a checkpoint records graph state at a superstep rather than the frames derived from it, with tool-call lifecycle appearing in no stream mode at all.
- **Redis or another external stream store (rejected).** The reference implementation's choice. Rejected because this service ships SQLite as a first-class backend and a loopback, single-host deployment; adding a required external service to make a progress stream resumable is a larger operational change than the problem warrants.

## Constraints

Binding:

- An SSE `id:` is emitted only on a frame whose replay is served. Where replay is disabled, unavailable, or outside the retained window, no id is written. This generalises the `sse-id-without-resumption` ruling into an invariant rather than a one-time fix.
- The sequence is monotonic per run, never reused, and continues across a worker or a gateway restart. A restart that cannot establish the run's high-water mark disables ids for that run rather than restarting the numbering.
- Allocation and durable writing happen behind the fan-out, never in front of it. The relay's existing ordering and the stream's one-heartbeat terminal bound are unchanged by this decision.
- Progress frames remain non-authoritative. Durable retention of a replay window does not make a frame run state: `run-status` stays the sole authority, and a replayed frame is the same droppable progress it was live.
- A replayed stream is gap-honest. A resume that cannot be served completely emits one bounded resynchronization frame naming the reason and the first sequence it can serve, and never presents a short replay as a complete one.
- Only the already-projected frame body is persisted. Prompts, document and artifact bodies, edit diffs, raw provider payloads, and per-role actor tokens are excluded by construction, preserving `2026-07-14-a2a-edge-conformance-adr` R7 and the engine fence. No content-capture opt-in is introduced.
- The replay log's retention is its own and is independent of checkpoint retention in both directions. The settled-checkpoint prune does not read or delete these rows; this sweep does not read or delete checkpoints.
- Offering `Last-Event-ID` and an `id:` on `GET /v1/runs/{run_id}/stream`, and any new `run-status` field, is a cross-repository contract event under `2026-07-14-a2a-edge-conformance-adr` R6, announced before release.

Scope: this record decides the sequence, the replay window, the durable row, and its retention. It does NOT decide the OpenTelemetry GenAI span model, provider-transcript linkage, or token-accounting columns, which stay the follow-on decision the audit names; it constrains them only by fixing the correlation identity they must attach to.

## Implementation

We will serve a resumable progress stream: the gateway allocates a durable per-run event sequence, appends each outgoing frame to a bounded per-run replay log in the application database, emits that sequence as the SSE `id:`, and replays from the log when a client reconnects with `Last-Event-ID`.

**S1 - One sequence authority, at one chokepoint.** The gateway allocates the sequence where frames enter subscriber queues, in `SubscriberManager.enqueue_payload` and `broadcast` (`src/vaultspec_a2a/streaming/subscribers.py:215,259`), so relayed worker payloads and the gateway's own in-process domain events get exactly one number each from the same counter. Allocation seeds from the run's durable high-water mark on first touch after a gateway start: `MAX(sequence)` for the run in the replay table, else `threads.last_sequence`, else zero. The worker's per-thread counter (`src/vaultspec_a2a/streaming/emitters.py:148-149,173-176`) is demoted to a worker-local ordering aid; the relay stamps the authoritative number and the body's existing sequence field keeps reporting it for compatibility.

**S2 - Wire format.** `id: {run_id}:{sequence}`, the sequence in decimal. Both halves are single-line and NULL-free by construction, which is all the SSE grammar requires. The stream accepts a cursor as the `Last-Event-ID` request header and, because `EventSource` cannot set headers, as a `last_event_id` query parameter on `GET /v1/runs/{run_id}/stream`; the header wins when both are present. The sentinel `-` means "from the start of the retained window", matching Agent Server. A cursor whose run segment is not the path's run id closes the stream with a `stream_rejected` frame of reason `resume_cursor_foreign_run`, rather than replaying another run's history.

**S3 - Attachment order under resume.** The existing order is kept and extended: subscribe, read durable state, emit `stream_snapshot`, then - when a cursor was supplied - replay the retained rows strictly after it in sequence order, then go live. The generator tracks the highest sequence it has emitted and drops any live frame at or below it, so one connection delivers each sequence exactly once even though the subscription was attached before the replay ran. A terminal reached during replay closes the stream through the existing terminal path.

**S4 - Gap honesty.** A cursor older than the first retained row emits one `progress_dropped` frame carrying `reason: "replay_window_exceeded"` and `first_sequence`, then continues from the window. A replay the store cannot serve emits `reason: "replay_unavailable"`. Both reuse the existing bounded resynchronization frame (`src/vaultspec_a2a/api/thread_stream.py:118-137`) and keep its remedy: re-read `run-status`.

**S5 - The table.** Alembic revision `0023_run_event_log`, one table `run_events`, identical on both backends: `thread_id` TEXT NOT NULL referencing `threads.id` with cascade delete, `sequence` INTEGER NOT NULL, primary key `(thread_id, sequence)`, `event_type` TEXT NOT NULL, `payload_json` TEXT NOT NULL holding the projected frame body, `created_at` UTC timestamp stamped at allocation (production time, never read time), and nullable `trace_id` and `span_id` carrying the ambient W3C ids. A secondary index on `created_at` serves the sweep. The composite primary key is both the replay index and the uniqueness guard that makes a retried write idempotent.

**S6 - Write path, behind the fan-out.** Each allocation appends to a bounded per-run in-memory ring and is flushed to the table as one `executemany` per ingested relay batch or every 50 ms, whichever comes first, on the application engine and never on the checkpointer connection. A replay reads the durable rows and then the ring, so a resume taken before a flush still sees the newest frames. A flush failure is logged with a count and degrades replay to the ring; a cursor outside both ranges takes the S4 gap frame. The ring size and the flush cadence are implementation hypotheses and may be tuned within these constraints; the ordering - allocate, ring, fan out, flush - is not.

**S7 - Retention.** Two bounds, both settings. `stream_replay_window_events` (default 2000) caps rows per run; the flush trims a run to its newest N in the same statement batch. `stream_replay_retention_hours` (default 24, the figure the independent store contract converged on) drives a periodic sweep that deletes rows of runs settled longer ago than that and rows of any run older than that. The thread-deletion saga removes a run's rows by cascade. `threads.last_sequence` keeps its current meaning and writer.

**S8 - Served capability, honestly advertised.** `stream_replay_enabled` (default true) governs the whole feature. When it is false, or when a run has no retained rows, the stream emits no `id:` at all, which is exactly today's behaviour, so a client never holds an id it cannot resume from. `run-status` gains one additive boolean, `stream_resumable`, so a consumer can tell the two postures apart without probing.

**S9 - Verification.** Real-behaviour tests against the live gateway, no mocks: a connection killed mid-run and reconnected with its received id, asserting the union of both connections covers every sequence to the terminal with no gap and no duplicate; a gateway restarted mid-run, asserting the sequence continues rather than restarting, which is the property whose absence forced the id removal; a window set small enough to be overrun, asserting exactly one `replay_window_exceeded` frame and contiguous frames after it; a cursor naming another run, asserting the typed refusal; the retention sweep deleting a settled run's rows while `prune_settled_checkpoints` leaves them untouched, and the converse; an authoring-shaped run asserting no stored payload contains a prompt, document body, diff, or token; replay disabled, asserting no frame carries an id; and a pooled-session assertion that a replay read does not hold a connection for the life of the stream, the lesson of `sse-pins-db-session`.

## Rationale

The durable row wins on a knockout the other options fail: the sequence must survive a restart or the `id:` cannot be emitted at all, and only a durable record makes it survive. The in-memory ring is strictly faster and strictly cheaper and still leaves the stream in the state `sse-id-without-resumption` describes, because a gateway restart mid-run would hand two different frames the same number. Checkpoint reuse fails twice over, on the prune that empties history exactly at settle and on the mismatch between a superstep and a frame. Keeping the status quo fails the operational question the audit raised rather than answering it.

Choosing the application database over an external stream store follows the deployment this service actually has: a loopback, single-host gateway with SQLite as a first-class backend. The reference implementation's Redis Streams choice is right for a multi-tenant hosted server and wrong here, where it would add a required service to make a progress stream resumable.

The write ordering follows the user's own decision on `terminal-fanout-before-persist`: fan-out is not to be delayed by a database write, so the replay log is written behind it, and the price is that a frame can be live before it is durable. That price is already paid elsewhere on this stream and is bounded by the same rules - the frame is non-authoritative, `run-status` is the authority, and a resume that lands in the unflushed window reads the ring.

Grounding is in `2026-10-01-stream-resumption-research`; the findings this record answers are in `2026-09-24-architecture-review-audit`.

## Consequences

The stream becomes recoverable across a disconnect, the `id:` block lifts, and `threads.last_sequence` stops being a cursor pointing at nothing. The service gains the durable per-run event record it has not had, on which the acceptance bundle, post-hoc inspection, and a later GenAI span model can all stand without inventing a second identity.

Accepted costs. One table, one migration, and a sweep to operate. A write per relay batch on a database whose SQLite configuration has one WAL writer shared with the worker, which the batching bounds but does not remove. Storage is bounded at roughly a couple of thousand frames per run for a day, which is tens of megabytes at the extreme, but it is new storage that did not exist. A cross-repository contract event: the dashboard must be told that frames now carry `id:`, that `Last-Event-ID` is honoured on the run stream, that a `progress_dropped` frame may now say `replay_window_exceeded` or `replay_unavailable`, that `stream_rejected` may say `resume_cursor_foreign_run`, and that `run-status` carries `stream_resumable`. A consumer that deduplicates by id is now safe, which was not true before, and that safety depends on S1 holding.

Reconsideration conditions. If measurement shows the batched insert contending materially with the worker on SQLite, the right revision is a separate replay store file or a smaller default window, not an id without a replay. If a deployment ever needs multiple gateway processes behind one run, S1's single-allocator assumption breaks and the sequence must move to a database-side allocation. If the dashboard declines the contract event, S8's switch is the honest posture and the log still serves the event-record half of the decision.

## Proposed reconciliation of existing decisions

Not applied. Each edit below is proposed for authorization with this record; none of it is in the accepted text today.

**`2026-02-26-event-aggregation-server-side-replay-adr`, section 4, "Custom Event Logging Database".** This record directly reverses that rejection and the reversal must be written where the rejection lives. Proposed replacement for that bullet: "**Custom Event Logging Database:** Rejected for CONVERSATIONAL history, which the checkpointer owns and still owns. Reinstated, in a bounded form, for the PROGRESS stream: `2026-10-01-stream-resumption-adr` adds an append-only per-run event table whose only purpose is a replay window for `Last-Event-ID` resumption and a durable record of what a run emitted. It is not a parallel event-sourcing database for state: nothing is reconstructed from it, it carries only already-projected frames, and it is deleted by its own retention. The divergence this rejection feared is prevented by `run-status` remaining the sole authority, not by the absence of the table."

Proposed addition to the 2026-07-15 amendment, so its scope cannot be read as covering this: "Server-side replay for DOCUMENT lifecycle remains the engine's `/authoring/v1/events` outbox. Replay of this service's own orchestration PROGRESS stream is a different subject and is decided by `2026-10-01-stream-resumption-adr`."

**`2026-07-14-a2a-edge-conformance-adr`, R6, final paragraph.** The sentence "droppable progress frames do not become durable history" contradicts this record as written, while its intent - that a progress frame is never authoritative - survives intact. Proposed replacement for that sentence: "Droppable progress frames are never authoritative history: `run-status` is the sole authority, and a frame's durable retention does not change that. A bounded replay window may be retained so a disconnected consumer can resume by `Last-Event-ID` under `2026-10-01-stream-resumption-adr`; it expires by its own retention and is not run history." Proposed addition to the same paragraph: "Stream attachment accepts a resumption cursor and replays the retained window after the snapshot. An `id:` is served only where its replay is served. Introducing the cursor, the id, and the `stream_resumable` field on `run-status` is a contract event on the frozen edge and is announced to the dashboard before release."

**`2026-03-04-worker-process-architecture-adr`, section 2.2.** The worker's relay is described without saying who owns event identity, which is why two counters exist. Proposed addition: "The worker→gateway event relay carries no sequence authority. The worker's per-thread counter orders a run's events within one worker lifetime; the stream's identity is allocated by the gateway at fan-out and is durable across a restart of either process (`2026-10-01-stream-resumption-adr`)."

**`2026-07-19-observability-lanes-adr`, Constraints.** The record's rotation-plus-reaper retention is about process log lanes and should not be read as covering, or failing to cover, a database record. Proposed addition: "The durable per-run event log of `2026-10-01-stream-resumption-adr` is a database lane, not one of the four process-kind log lanes. It is not routed through `configure_logging`, writes to no file, and is bounded by its own row and age retention rather than by rotation and the reaper."

**`2026-03-10-postgres-dual-backend-adr`.** No edit proposed. The new table is application schema under Alembic and backend-agnostic by construction, which is exactly the boundary that record draws; it is named here only so a reader does not look for a missing reconciliation.

**`2026-08-05-served-capability-contract-state-truthfulness-adr`.** No edit proposed. T4 forbids a structured field contradicting a run's outcome; a replayed frame is ordered before the durable terminal the same stream then emits, so the replay path satisfies T4 rather than straining it.

Accepted 2026-10-01 under the user's blanket approval of that date.

## Amendment (2026-10-07): one sequence authority for frame ids and `threads.last_sequence`

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

S1 and S7 contradicted each other. S1 seeds the allocator from `threads.last_sequence`, and S7 left that column to a different counter. Settle captures the gateway emitter counter (`src/vaultspec_a2a/control/event_handlers.py:811-813`), and the live fallback serves it (`src/vaultspec_a2a/control/thread_state_service.py:427-431`). That counter skips `graph_registered` (`src/vaultspec_a2a/streaming/emitters.py:856-871`), counts a held terminal that is never numbered (`src/vaultspec_a2a/streaming/emitters.py:785-786`), and restarts at zero with the gateway. Frame ids come from `RunSequenceAllocator` (`src/vaultspec_a2a/streaming/subscribers.py:108-229`). A settled run's cursor can therefore sit below its own terminal frame id, and a later reseed reads that low value. Grounding: R2-F1 and R2-F18 in `2026-10-06-codebase-remediation-audit`; decision D4 in `2026-10-06-codebase-remediation-plan`.

S1 and S7 are amended:

- `threads.last_sequence` is the highest sequence `RunSequenceAllocator` has issued for the run: its live counter, or the floor it keeps for a forgotten run. Settle writes it from the allocator. No other counter writes the column.
- Live run-status for an unsettled run serves the same mark: the allocator's issued mark, else the run's durable high-water mark in S1's seed order, else 0.
- Where no allocator numbers the run, settle writes nothing and the column keeps its prior value. This covers replay disabled, where no allocator is seated (`src/vaultspec_a2a/api/_replay_writer_seat.py:73-74`), and a run left unnumbered because its seed could not be read. Such a run serves no id, and S8's `stream_resumable` already reports it.
- The gateway emitter counter is retired. The gateway's use of `EventEmitters._sequences` and `get_sequence`, `EventAggregator.get_sequence`, and the `next_sequence()` calls inside the `_sync_*` handlers are removed.
- The worker's per-run counter (`src/vaultspec_a2a/streaming/emitters.py:148-157`) is a worker-local ordering aid only. Nothing resumes, deduplicates, persists or serves against it. It survives only as the body `sequence` of a frame on an unnumbered run, which carries no id.
- The gateway produces no in-process domain events. Every numbered frame is a relayed worker payload, numbered in `SubscriberManager.enqueue_payload` (`src/vaultspec_a2a/streaming/subscribers.py:532-562`). S1's mention of the gateway's own in-process domain events describes the path that the 2026-10-07 amendment of `2026-07-14-a2a-edge-conformance-adr` removes.

Superseded sentence in S7: "`threads.last_sequence` keeps its current meaning and writer." Replacement: `threads.last_sequence` is the allocator's issued high-water mark, written at settle by the allocator and by nothing else. S1's seed order is unchanged and now reads one authority.

S5 is amended in two places:

- `trace_id` and `span_id` are stamped at allocation from the ambient OpenTelemetry span context, in the same act that stamps `created_at` (`src/vaultspec_a2a/streaming/subscribers.py:324-333`). On the relay path that context is the gateway request span. The worker propagates its trace on every batch (`src/vaultspec_a2a/worker/ipc.py:394-401`), and the gateway middleware extracts it (`src/vaultspec_a2a/telemetry/middleware.py:125-137`). An invalid span context leaves both columns NULL. The columns stay. Today the writer never sets them (`src/vaultspec_a2a/streaming/run_event_writer.py:132-140`).
- Superseded phrase: "identical on both backends". Replacement: the table lives in the SQLite application store, the only backend under `2026-10-07-codebase-remediation-sqlite-only-adr`. The note on `2026-03-10-postgres-dual-backend-adr` under "Proposed reconciliation of existing decisions" is historical.

S9 gains one real-behaviour test: served `last_sequence`, live and settled, equals the last SSE id the run emitted and `MAX(run_events.sequence)`, and a gateway restart mid-run does not rewind it.

This is a contract event under `2026-07-14-a2a-edge-conformance-adr` R6, announced to the dashboard before release. The `last_sequence` field and its type are unchanged. Its value becomes the sequence of the run's last numbered frame, so it agrees with the SSE ids. With replay disabled a new run reports 0, because no frame is numbered. The trace columns are internal and change nothing on the wire.
