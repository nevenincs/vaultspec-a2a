---
tags:
- '#adr'
- '#event-aggregation-server-side-replay'
date: 2026-02-26
modified: '2026-10-07'
body_hash: 'sha256:db73023e0641bbb312f502e6932851c2c14e3987f3bd51c6ac1a000809abbeb8'
related:
- '[[2026-03-31-docs-vault-migration-research]]'
- '[[2026-10-01-stream-resumption-adr]]'
- '[[2026-10-06-codebase-remediation-audit]]'
- '[[2026-10-07-codebase-remediation-sqlite-only-adr]]'
---

# `event-aggregation-server-side-replay` adr: `adr-4` | (**status:** `accepted`)

## Migration Note

This ADR was migrated from the legacy pre-pipeline documentation tree during the issue #19 cleanup so that the repository no longer depends on the removed `docs/` directory.

- Original ADR number: `ADR-4`
- Original title: `Event Aggregation & State Replay (LangGraph Core)`
- Legacy status at migration time: `Proposed`

## Original ADR

## ADR-004: Event Aggregation & State Replay (LangGraph Core)

**Date:** 2026-02-26
**Status:** Proposed

## 1. Context & Problem Statement

The orchestrator must handle a high volume of diverse event streams
originating from multiple concurrent LangGraph agent executions. The
frontend Gateway requires a single, multiplexed WebSocket
connection to display these events in real-time. Crucially, because
LangGraph executions are highly stateful, the frontend needs to be able
to reliably reconstruct the current state of an agent (including its
memory, tool calls, and pending interrupts) upon browser reconnects or
refreshes.

## 2. The Decision

We will handle Event Aggregation and State Replay via the following
mechanisms:

- **Native LangGraph Stream Aggregator:** A central Python component
  within the orchestrator will serve as the Event Aggregator. Its
  responsibilities include:
  - Ingesting LangGraph's `astream` (node state updates) and
    `astream_events` (granular LangChain callback events like tokens
    streaming, tool starts, tool ends).
  - Performing necessary payload transformations (e.g., adding
    universally formatted timestamps, grouping `run_id`s, structuring
    message arrays).
  - Broadcasting these unified JSON events over a single, multiplexed
    WebSocket connection to the Gateway frontend.
- **SQLite Checkpoint Sourcing:** Rather than reinventing a custom
  event-sourcing database, all graph state transitions and checkpoints
  are inherently persisted by LangGraph's `checkpointer` (via
  `langgraph-checkpoint-sqlite`).
- **Server-Side State Replay:** Upon a frontend reconnect or refresh,
  the Gateway will request the latest persisted Graph State for
  a given `thread_id` via a dedicated REST endpoint.
  - The server will retrieve the state using `graph.get_state(config)`.
  - This state object (containing the entire message history and
    current node values) serves as the "source of truth", allowing the
    frontend to immediately render the full conversational history and
    UI components without needing to replay individual granular events,
    followed immediately by live WebSocket updates for ongoing
    operations.

## 3. Rationale

- **Unified Stream & Ecosystem Alignment:** Utilizing LangGraph's native
  `astream_events` provides a rich, deeply integrated stream of
  execution data (far superior to parsing raw stdout text). Aggregating
  this centrally simplifies client-side logic.
- **Checkpoint Reliability:** LangGraph's `checkpointer` is specifically
  designed for this exact use case—fault-tolerant state persistence.
  Leaning on it entirely removes the need for us to maintain separate,
  complex SQLite event-sourcing schemas for conversational history.
- **Robust Frontend Recovery:** Reconstructing UI from a final holistic
  State Object (rather than streaming thousands of historical delta
  events to the browser just to rebuild state on the client) is
  dramatically faster and far less prone to race conditions or sync
  errors during reconnects.

## 4. Rejected Alternatives

- **Raw Subprocess Stdout Ring Buffers (Original Design):** Rejected.
  Since we no longer run CLI binaries as subprocesses, there is no raw
  ANSI stdout/stderr to capture. Agents run natively as python
  functions.
- **Custom Event Logging Database:** Rejected. LangGraph's
  `checkpoint-sqlite` covers 95% of our event persistence needs
  natively. Building a parallel, custom event-sourcing database
  introduces unnecessary complexity and potential data divergence.

## 5. Implementation Constraints & Pitfalls

- **Payload Bloat:** LangGraph `astream_events` can be extremely noisy
  (e.g., emitting an event for every single chunk of a streaming LLM
  response). The Event Aggregator must carefully batch or debounce
  certain high-frequency events before broadcasting them over the
  WebSocket to prevent blowing out the browser's memory or network
  queue.
- **Differentiating Threads:** The multiplexed WebSocket must strictly
  encapsulate all payloads with their corresponding LangGraph
  `thread_id` to ensure the frontend routes updates to the correct
  agent UI instance.

## 6. Negative Consequences

- **Loss of "Terminal" View:** Because we are no longer piping raw ANSI
  stdout, the "Terminal" view concept in the Gateway is
  deprecated. It must be replaced with structured UI components (e.g.,
  Chat Bubbles, Tool Call components, Markdown renderers) that
  visualize the structured LangGraph JSON payloads. While this is
  cleaner, it requires more frontend work than simply dropping
  `xterm.js` on the page.

## 7. References

- LangGraph Gap Audit Research
- Gateway Domain - Distilled

## Amendment - a2a-edge-conformance (2026-07-15)

Superseded WHERE this record served the deleted React UI. The event model
it defines is replaced by the engine-relayed SSE split: orchestration
progress frames are now versioned, bounded, and droppable
(non-authoritative), with durable truth read from `run-status` and the
engine's authoring events. Server-side replay for document lifecycle is the
engine's `/authoring/v1/events` outbox, not this repo's concern. The
in-repo event dataclasses survive as the relay substrate. See
`2026-07-14-a2a-edge-conformance-adr` and its supersession map in
`2026-07-14-a2a-edge-conformance-reference`.

## Amendment - langgraph-conformance (2026-09-30)

A run is consumed through LangGraph's public `astream` stream modes, not `astream_events`. Ingest opens one stream over `messages`, `updates`, `tasks`, `custom` and `checkpoints` with `subgraphs=True` (`src/vaultspec_a2a/streaming/transformer.py`, `src/vaultspec_a2a/streaming/ingest.py`). Three commitments follow from that choice and bind with it:

- An interrupt is observed from the stream frame that reports it, not from a state read taken after the stream ended.
- The dispatch application receipt fires on the first durable checkpoint frame, not on the first chain event.
- A run's drain control is passed to the documented `control=` parameter, not seated under a private LangGraph config key.

Tool-call lifecycle is not a graph superstep and appears in no stream mode. It reaches the emitters through a run-scoped callback handler seated in the run config (`src/vaultspec_a2a/streaming/_run_callbacks.py`), built in one place by the ingest manager. A tool frame and a node-status frame are therefore ordered by when they happen, not by one queue; each family stays internally ordered. Frames tagged `nostream` are dropped by the library, not by a filter this layer writes. A node's own custom stream write carries the writing node's identity in its payload, because LangGraph drops that node's segment from a custom write's namespace (`src/vaultspec_a2a/streaming/custom_writes.py`).

A run that keeps checkpoints asks for `durability="sync"`, so every superstep is persisted before the next one starts (`src/vaultspec_a2a/streaming/ingest.py`). LangGraph's default, `"async"`, persists a superstep while the next one executes and may lose the most recent one to a crash, which the checkpoint-first recovery this service depends on cannot tolerate. A graph compiled without a checkpointer is left on the library default, because langgraph 1.2.12 kills such a run when durability is requested. That guard is an implementation hypothesis, not a commitment, and is removed when the upstream defect is fixed.

Checkpoint sourcing is no longer SQLite-only; `2026-03-10-postgres-dual-backend-adr` chooses the backend. Grounding: `2026-09-30-langgraph-conformance-audit`.

Accepted 2026-10-01 by the user, with this amendment as its binding content; the parts the 2026-07-15 amendment marks superseded stay superseded.

## Amendment - stream-resumption (2026-10-01)

Section 4's rejection of a Custom Event Logging Database is reversed in bounded form, and
the reversal is recorded here where the rejection lives. Superseded bullet: "**Custom Event
Logging Database:** Rejected. LangGraph's `checkpoint-sqlite` covers 95% of our event
persistence needs natively. Building a parallel, custom event-sourcing database introduces
unnecessary complexity and potential data divergence." Replacement: **Custom Event Logging
Database:** Rejected for CONVERSATIONAL history, which the checkpointer owns and still
owns. Reinstated, in a bounded form, for the PROGRESS stream: `2026-10-01-stream-resumption-adr`
adds an append-only per-run event table whose only purpose is a replay window for
`Last-Event-ID` resumption and a durable record of what a run emitted. It is not a parallel
event-sourcing database for state: nothing is reconstructed from it, it carries only
already-projected frames, and it is deleted by its own retention. The divergence this
rejection feared is prevented by `run-status` remaining the sole authority, not by the
absence of the table.

Addition to the 2026-07-15 amendment above, so its scope cannot be read as covering this:
server-side replay for DOCUMENT lifecycle remains the engine's `/authoring/v1/events`
outbox. Replay of this service's own orchestration PROGRESS stream is a different subject
and is decided by `2026-10-01-stream-resumption-adr`.

## Amendment (2026-10-07): the `custom` stream mode is retired

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

The 2026-09-30 amendment opens ingest over a `custom` mode and binds a rule for a node's own custom stream write. Neither has a producer. No shipped node calls `get_stream_writer`, and `emit_custom_node_write` (`src/vaultspec_a2a/streaming/custom_writes.py:54-70`) has only test callers; its module states that no shipped node calls it (`src/vaultspec_a2a/streaming/custom_writes.py:12-13`). The consumer, `_project_custom` and `_custom_text` (`src/vaultspec_a2a/streaming/transformer.py:351-394`), and the `custom` entry in `STREAM_MODES` (`src/vaultspec_a2a/streaming/transformer.py:52`) serve only tests. Grounding: R2-F16 in `2026-10-06-codebase-remediation-audit`; decision D17 in `2026-10-06-codebase-remediation-plan`.

Superseded clause: "Ingest opens one stream over `messages`, `updates`, `tasks`, `custom` and `checkpoints` with `subgraphs=True`". Replacement: ingest opens one stream over `messages`, `updates`, `tasks` and `checkpoints` with `subgraphs=True`.

Superseded sentence: "A node's own custom stream write carries the writing node's identity in its payload, because LangGraph drops that node's segment from a custom write's namespace (`src/vaultspec_a2a/streaming/custom_writes.py`)." Replacement: none. The mode, `streaming/custom_writes.py`, its consumer and its streaming facade export are removed.

The other commitments of the 2026-09-30 amendment are unchanged. Reconsideration: a node that must stream its own writes re-adds the mode together with that producer, by amendment, and restores the identity-in-payload rule with it.

## Amendment (2026-10-07): reconciliation with the codebase-remediation decisions

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

`2026-10-07-codebase-remediation-sqlite-only-adr` supersedes `2026-03-10-postgres-dual-backend-adr` and makes SQLite the only checkpoint store in every profile. Grounding: R3-F12 in `2026-10-06-codebase-remediation-audit`; decision D1 in `2026-10-06-codebase-remediation-plan`.

Superseded sentence in the 2026-09-30 amendment: "Checkpoint sourcing is no longer SQLite-only; `2026-03-10-postgres-dual-backend-adr` chooses the backend." Replacement: checkpoint sourcing is SQLite-only, through `langgraph-checkpoint-sqlite` (`pyproject.toml:32`), and `2026-10-07-codebase-remediation-sqlite-only-adr` owns the store. Section 2's "SQLite Checkpoint Sourcing" bullet again describes the backend. The other 2026-09-30 commitments, as amended above, are unchanged.
