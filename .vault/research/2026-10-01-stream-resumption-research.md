---
tags:
  - '#research'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:08305ca8f2300dc6e66376b8d48f32814d99bc01602ffb66419d2a851618519c'
related:
  - "[[2026-09-24-architecture-review-audit]]"
  - "[[2026-09-24-architecture-review-research]]"
---

# `stream-resumption` research: `resumable progress streams and a durable per-run event record`

Can a dashboard viewer that loses its connection rejoin a run's progress stream without a gap, and what would have to become durable for that to be true? The question matters because the only recovery this service offers today is a full re-read of `run-status`, which carries run state and no progress history, so a viewer that drops for ten seconds loses every tool call, thought, and message chunk produced in that window with no indication that anything was missed. The evidence shows three things. The pieces of a resumable stream are mostly present but none of them is durable: a per-run sequence exists twice, both copies in process memory, and no buffer holds a frame after it is handed to a subscriber queue. The standards answer is settled and narrow: the SSE specification defines resumption entirely in terms of an `id:` field the server chooses and a `Last-Event-ID` request header the user agent replays, and it imposes no storage obligation, so the whole cost of resumption is the server-side replay window. And the reference implementation in this stack, LangGraph's Agent Server, treats stream resumability as an explicit per-run opt-in backed by persisted stream chunks, which is the same shape the durable-event-log gap recorded in `2026-09-24-architecture-review-audit` would need. What the ADR must settle is where the replay window lives, how long it is kept, and whether the same rows are the per-run event log that a later GenAI span model attaches to.

## Findings

### No SSE frame carries an `id:`, and the refusal is deliberate and still correct

`_encode` writes only `event:` and `data:` lines (`src/vaultspec_a2a/streaming/sse_frames.py:520-527`), and its docstring records why (`:511-519`): the only number a frame could offer is the run's event sequence, the worker keeps that in memory and restarts it from zero, and the gateway keeps no buffer a `Last-Event-ID` could resume from, so an id would promise a resumption that does not exist and would invite a consumer to deduplicate away a restarted worker's events. The sequence stays in the body. This is the state the `sse-id-without-resumption` finding of `2026-09-24-architecture-review-audit` reached after an in-memory sequence was put in the id field and removed again. The refusal is conditional, not permanent: it names exactly the two missing properties, a durable sequence and a replay buffer.

### The per-run sequence exists twice, in two processes, both in memory

The worker's emitters hold a per-thread counter (`src/vaultspec_a2a/streaming/emitters.py:148-149`), hand out numbers through `next_sequence` (`:173-176`), and drop a thread's counter on prune or state clear (`:190-196`, `:307`). The gateway keeps a second, independent counter: `sync_worker_event` advances it once per relayed event and never reads a number the worker assigned (`:757-774`). Neither counter survives its process. The sequence a consumer sees in a frame body is therefore an ordering aid within one process lifetime, not an identity.

### One durable cursor field already exists, and it is written only at terminal settle

`threads.last_sequence` is a nullable integer column (`src/vaultspec_a2a/database/models.py:431`, migration `0016_thread_last_sequence`), captured from the gateway aggregator's counter immediately before the terminal durable write and before the aggregator's state is pruned (`src/vaultspec_a2a/control/event_handlers.py:684-686`). `run-status` serves it as `last_sequence`, falling back to the live aggregator read while the run is unsettled (`src/vaultspec_a2a/control/thread_state_service.py:427-436`, `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:337`, schema `src/vaultspec_a2a/api/schemas/gateway.py:502`). The column is a reconnect cursor with nothing behind it: it tells a client how many events a settled run produced and offers no way to obtain any of them. The acceptance evidence bundle carrying `last_sequence: 0` with no events, noted in the audit's `no-durable-event-log` finding, is that gap seen from the outside.

### The relay path is lossy by design at three bounded stages, and every drop is recoverable only from `run-status`

The worker buffers events and posts them in batches (`src/vaultspec_a2a/worker/ipc.py:271-288`) under a 10,000-event drop-oldest cap (`src/vaultspec_a2a/control/infra_config.py:884`) whose eviction takes the oldest non-outcome entry so a terminal is given up last (`src/vaultspec_a2a/worker/ipc.py:291-331`, protected set `src/vaultspec_a2a/streaming/fanout.py:40-49`). The gateway ingests a batch bounded by `internal_max_event_batch_bytes`, four times the 1 MiB internal body limit (`src/vaultspec_a2a/control/config.py:406`, `src/vaultspec_a2a/control/infra_config.py:855,861`), refusing a larger body with 413 (`src/vaultspec_a2a/api/internal.py:410`); the worker splits a backlog into deliverable batches rather than reposting it whole (`src/vaultspec_a2a/worker/ipc.py:74-103`). Each subscriber then owns a 512-slot queue (`src/vaultspec_a2a/domain_config.py:64`) that drops oldest under pressure (`src/vaultspec_a2a/streaming/fanout.py:128-169`), and the stream emits a counted `progress_dropped` resynchronization frame telling the consumer to re-read `run-status` (`src/vaultspec_a2a/api/thread_stream.py:118-137,187-205`). Nothing in this path retains a frame after delivery, so a resynchronization notice is the only thing a consumer can be told, and the remedy is always a status re-read rather than the missing events.

### Fan-out precedes the durable write, and the user has kept that ordering

`_relay_single_event` fans a relayed payload out to subscriber queues and advances the gateway counter (`src/vaultspec_a2a/api/internal.py:206-207`) before awaiting `relay_event`, which performs the durable projection (`:219`). The `terminal-fanout-before-persist` entry of `2026-09-24-architecture-review-audit` records the consequence and the alternative: persisting first would close the window at the cost of a database write in front of every relayed frame. The stream bounds the exposure instead, re-reading durable status on each idle heartbeat and closing on a terminal (`src/vaultspec_a2a/api/thread_stream.py:270-282`), with the heartbeat at 30 s by default (`src/vaultspec_a2a/control/infra_config.py:841`). The user has decided to keep the one-heartbeat bound. Any replay design must therefore write its record off the fan-out path, which means a frame can be delivered live before its replay row is durable.

### Attachment already registers before it reads authority, so only the gap behind the cursor is missing

The stream subscribes first and reads durable state second (`src/vaultspec_a2a/api/thread_stream.py:244-257`), leads with a `stream_snapshot` frame, and replays a durable error and terminal for an already-settled run (`:154-184,259-262`). This closes the attach race the `terminal-frame-race` finding opened and is the snapshot-first shape A2A requires of a subscription. What it does not do is deliver anything that happened before the attach: the snapshot is run state, not history.

### WHATWG defines resumption as an id the server chooses and a header the user agent replays

The SSE specification sets the last event ID buffer from an `id:` field whose value contains no U+0000 NULL and ignores it otherwise; the buffer is not reset between events, so the value persists until the server sets it again; and on reconnection the user agent sends `Last-Event-ID` with that value when it is not the empty string. `retry:` sets the reconnection time when its value is only ASCII digits. A response that is not 200 with `text/event-stream` fails the connection. The specification imposes no obligation to retain anything: everything resumption costs is the server's replay window and the id format is the server's own choice, subject only to the NULL exclusion and to the single-line field grammar.

### LangGraph Agent Server treats resumability as opt-in persistence of stream chunks

Agent Server's thread stream is resumable through the same header: a client passes the last event id it received to `client.threads.join_stream(thread_id, last_event_id=...)`, or the `Last-Event-ID` header over cURL, and the sentinel `"-"` replays from the beginning. The run-level `join_stream` is explicitly NOT buffered - "any output produced before joining will not be received" - so resumability is a property of the persisted thread stream, not of joining a run. The SDK exposes `stream_resumable`, documented as "Whether to persist the stream chunks in order to resume the stream later", which makes the storage cost a per-run decision rather than a global one. The server changelog records the mechanism: v0.7.91 (2026-03-29) introduced "an optimized streaming implementation using Redis Streams with a new protocol version (v2) for better performance and resumability, featuring payload compression", and v0.8.6 (2026-05-04) added v2 streaming primitives to the API. Retention of stream chunks is not documented; the documented TTLs are `LANGGRAPH_THREAD_TTL` and the store TTL block, which govern threads and store items rather than the stream log.

### A2A guarantees no replay, which bounds what the dashboard edge may be promised

The A2A specification requires `SubscribeToTask` to "return a `Task` object as the first event in the stream, representing the current state of the task at the time of subscription", states that clients "MAY not receive all status update messages if the client is disconnected and then reconnects", and offers push notifications as the alternative for disconnected scenarios. Snapshot-first subscription is therefore a requirement and gap-free replay is not, so a resumption guarantee offered on this repository's edge is an addition above the protocol baseline rather than conformance to it.

### The independent-implementation norm for a replay store is a monotonic cursor log with a short TTL

The `assistant-ui` resumable-stream store contract describes the shape a replay window converges on independently of this stack: per stream, a monotonic byte log of entries carrying an opaque cursor, the chunk, a terminal flag with status, and an expiry; a read takes a cursor and yields entries strictly after it; an empty cursor means start from the beginning; cursors must be strictly monotonic per stream; the expiry is refreshed on every append and on finalize; the built-in stores default to 24 hours; and expired streams become an error rather than silently returning a short read. Backends named include Postgres and other relational stores with native sweeps, and Redis-like engines using native TTL. The contract is deliberately backend-agnostic, which is what makes it applicable to this repository's SQLite-and-Postgres pair.

### Checkpoint history cannot be the replay source, because it is pruned at settle

`prune_settled_checkpoints` keeps each namespace's latest checkpoint and its pending writes and removes the rest (`src/vaultspec_a2a/database/checkpoint_retention.py:1-20`), scheduled as a background task at terminal settle (`src/vaultspec_a2a/control/event_handlers.py:697`). Even before the prune, a checkpoint records graph state at a superstep, not the progress frames derived from it: tool-call lifecycle is not a superstep and appears in no stream mode, reaching the emitters through a run-scoped callback handler, as the 2026-09-30 amendment to `2026-02-26-event-aggregation-server-side-replay-adr` records. Checkpoints and a replay log are therefore different records with different lifetimes, and a replay window keyed to checkpoint retention would be empty exactly when a reconnecting client needs it.

### Storage cost is small per run and is dominated by write rate, not volume

Frames reaching a subscriber are already projected onto the positive progress allowlist at the relay seam (`src/vaultspec_a2a/streaming/aggregator.py:192-201`) and re-projected at the encode boundary (`src/vaultspec_a2a/streaming/sse_frames.py:554`), and a frame over 1 MiB is replaced by a sentinel (`:84`, `:556-568`). A replay row is therefore a bounded, already-redacted JSON body, and a window of a couple of thousand rows per run is tens of megabytes at the extreme and far less in practice. The real constraint is the write path: the application database defaults to Postgres with SQLite as a first-class fallback (`2026-03-10-postgres-dual-backend-adr`), and on SQLite the gateway and worker already contend for one WAL writer, which argues for one batched insert per ingested relay batch rather than one statement per frame. Alembic owns the application schema; the latest revision is `0022_cost_tracking_token_breakdown`, so a replay table is `0023`.

### OpenTelemetry GenAI conventions supply the vocabulary a later span model would use, and they are not stable

The GenAI conventions name the operations `chat`, `invoke_agent`, `execute_tool`, `embeddings`, and `create_agent`, with span names of the form `invoke_agent {gen_ai.agent.name}` and `execute_tool {gen_ai.tool.name}`. `gen_ai.operation.name` and `gen_ai.provider.name` are required on those spans; `gen_ai.agent.id`, `gen_ai.agent.name`, `gen_ai.conversation.id`, and `gen_ai.tool.call.id` are recommended, with `gen_ai.conversation.id` the attribute that groups spans belonging to one conversation. Token accounting includes `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, and `gen_ai.usage.reasoning.output_tokens`, which are the counts the `token-accounting-gaps` finding records as dropped. Message content lives in a separate event rather than in span attributes and is opt-in, exemplified by `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`. The whole `gen_ai.*` set is at Development stability and moved to a dedicated repository in June 2026 explicitly to iterate faster than the core stability bar allows. Binding a durable schema to these names today would therefore import an unstable vocabulary into a persisted record; carrying a correlation identity that a span model can later attach to does not.

### The option space, and what the ADR must settle

Four options are distinguishable at the same level. Keep no resumption and continue to answer a reconnect with snapshot plus `run-status`: zero cost, and the gap stays unreported beyond a drop count. Hold a bounded in-memory replay ring in the gateway keyed by a gateway-assigned sequence: cheap and fast, dies with the gateway process, and cannot serve a run whose frames crossed a restart. Write an append-only per-run row for each relayed frame in the application database and replay from it: survives a restart, costs one batched insert per relay batch and a retention sweep, and is the same record the `no-durable-event-log` finding asks for. Or reuse checkpoint history, which the prune and the frame-versus-superstep mismatch above rule out.

The ADR must settle: whether an `id:` may ever be emitted without a served replay for it; which process allocates the sequence and how it stays monotonic across a worker or gateway restart; the id's wire format under the NULL and single-line constraints; the replay window's two bounds, rows per run and age; how retention relates to the settled-checkpoint prune and to the thread-deletion saga; what a resume whose cursor is older than the window is told; whether the row set is also the per-run event log, and if so what it may contain given that actor tokens are prohibited from persistence by `2026-07-14-a2a-edge-conformance-adr` R7; and whether offering `Last-Event-ID` on the dashboard edge is a contract event under R6.

### What was not investigated

No live measurement of insert cost was taken on either backend; the sizing above is derived from the existing frame bound and row shape, not measured. The dashboard repository's consumer was not read, so what it would do with an `id:` is unknown. Agent Server's stream-chunk retention is undocumented and was not determined from its source. No LangGraph `DeltaChannel` interaction was examined, because a replay log is not a checkpoint channel. Whether a browser `EventSource` or the dashboard's own client reuses a `Last-Event-ID` across different run URLs was not tested.

## Sources

- https://html.spec.whatwg.org/multipage/server-sent-events.html
- https://docs.langchain.com/langsmith/streaming
- https://docs.langchain.com/langsmith/streaming.md
- https://docs.langchain.com/oss/python/langchain/frontend/join-rejoin
- https://reference.langchain.com/python/langgraph-sdk/schema/CronUpdate/stream_resumable
- https://docs.langchain.com/langgraph-platform/langgraph-server-changelog
- https://docs.langchain.com/langsmith/configure-ttl
- https://a2a-protocol.org/latest/specification/
- https://www.assistant-ui.com/docs/guides/resumable-stream-stores.md
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md
- https://opentelemetry.io/docs/specs/semconv/gen-ai/
- https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained
- `src/vaultspec_a2a/streaming/sse_frames.py:71,84,511-527,554-568`
- `src/vaultspec_a2a/streaming/emitters.py:148-149,173-176,190-196,307,757-774`
- `src/vaultspec_a2a/streaming/aggregator.py:192-201`
- `src/vaultspec_a2a/streaming/fanout.py:40-49,128-169`
- `src/vaultspec_a2a/api/thread_stream.py:118-137,154-184,187-205,244-262,270-282`
- `src/vaultspec_a2a/api/internal.py:206-207,219,410`
- `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py:337,378-409`
- `src/vaultspec_a2a/api/schemas/gateway.py:502`
- `src/vaultspec_a2a/worker/ipc.py:74-103,271-288,291-331`
- `src/vaultspec_a2a/control/infra_config.py:841,855,861,884`
- `src/vaultspec_a2a/control/config.py:406`
- `src/vaultspec_a2a/control/event_handlers.py:684-686,697`
- `src/vaultspec_a2a/control/thread_state_service.py:427-436`
- `src/vaultspec_a2a/domain_config.py:64,79`
- `src/vaultspec_a2a/database/models.py:431`
- `src/vaultspec_a2a/database/checkpoint_retention.py:1-20`
- `src/vaultspec_a2a/database/migrations/versions/0016_thread_last_sequence.py`
- `src/vaultspec_a2a/database/migrations/versions/0022_cost_tracking_token_breakdown.py`
