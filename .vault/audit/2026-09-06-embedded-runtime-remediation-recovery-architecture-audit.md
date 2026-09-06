---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:6277e69313062c53e3034eb2d517aab1ccb4f5d782fccaec3844df338acb93c1'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research]]"
---
# Recovery authority and evidence architecture review

## Scope

Review of the amended recovery ADRs and the production owners for conditions 1-16 before implementation. Condition 17 is separately owned by the verification lifecycle correction.

## Findings

### startup-unconditional-writer | high | open; lifecycle ownership

`src/vaultspec_a2a/database/reconciliation.py:execute_reconciliation` still calls the unconditional lifecycle setter and changes repair state after deciding from a stale batch snapshot. The shared recovery coordinator must own startup entry as well as exits from reconciling; moving only redispatch and API abandonment leaves this stale writer authoritative.

### checkpoint-completion-heuristic | high | open; evidence integrity

`src/vaultspec_a2a/worker/state_projection.py:pre_flight_checkpoint` equates empty pending writes with completion and permits dispatch after checkpoint-read failure using an in-memory heuristic. Empty pending writes do not establish the absence of scheduled graph tasks or identify the current accepted action. Completion must come from durable action-bound evidence. Unreadable evidence cannot authorize replay.

### missing-action-incorporation | high | open; architectural dependency

`src/vaultspec_a2a/thread/state.py` has clarification-specific fingerprints but no general journal-action, payload-fingerprint and dispatch receipt. The generic worker notification in `executor.py:_emit_dispatch_application_receipt` proves only entry into graph execution. The coordinator cannot distinguish a previous turn's completed checkpoint from the current action until the general receipt declaration and real incorporation producer exist. S78 and S12 are prerequisites of S11/S83, despite their later displayed positions.

### incomplete-durable-dispatch | high | open; recovery authority

`src/vaultspec_a2a/control/thread_service.py:create_thread_service` journals only title, preset and autonomous input before dispatch. Initial content and the effective dispatch inputs are not recoverable from that payload. `dispatch.py:redispatch_reconciling_threads` constructs a fresh INGEST with a newly generated dispatch id. Recovery must retain the accepted dispatch identity and complete recoverable non-secret inputs before network delivery; missing inputs require typed refusal, never reconstruction using defaults. Ephemeral actor tokens require a separately authorized fresh credential path or explicit refusal, never durable secret storage.

### impossible-integrity-election | high | open; decision contradiction

The amended state-truthfulness ADR requires a terminal receipt-mismatch refusal through an election whose SQL predicate requires that missing receipt. `thread_repository.py:elect_thread_status` therefore returns RECEIPT_MISMATCH without changing the indefinitely reconciling row. The decision must distinguish ordinary receipt-authorized advancement from a constrained integrity quarantine: compare the exact observed current row and the absence of its matching receipt, refuse execution, and never invent replacement authority.

### demand-gated-recovery | high | open; lifecycle progress

`src/vaultspec_a2a/api/app.py:_deferred_reconcile` waits for a worker-demand event emitted by a new dispatch. Polling an interrupted run cannot release that gate. Durable checkpoint settlement and recovery disclosure must operate before worker demand; network redelivery must respect the desktop worker ownership contract and disclose a waiting-for-demand obligation when applicable.

### mutable-deadline-authority | high | open; execution contract

`run_discovery_service.py:_derive_reconciling_abandonment_bound` loads the current preset from disk, silently substitutes a global floor when configuration cannot be loaded, and measures from mutable updated_at. These are not frozen run execution authority. Admission must retain the effective execution deadline inputs; recovery attempts and API reads must not extend the deadline.

## Recommendations

Implement the general checkpoint receipt and its producer before the coordinator. Persist complete non-secret dispatch authority at admission before delivery. Centralize startup, periodic and read-triggered recovery after resolving the quarantine and desktop-demand rules. Keep all conditions open until the production consumers use these owners; declaration tests alone do not close a recovery defect.

## Review disposition

FAIL for the amended architecture as an immediately implementable S11-only change. No production code changed during this review. The single-agent executor proceeds through the prerequisite corrections and updates the audit on each implementation pass.

### checkpoint-receipt-declaration | low | resolved within S78; producer remains open

Formal self-review of `thread/action_receipts.py`, its `TeamState` reducer and the real checkpoint test passes the declaration boundary. The version, journal action, fingerprint, dispatch and ownership fields are required, bounded and immutable. Cancellation cannot masquerade as graph incorporation. Receipt reuse with different evidence raises instead of replacing the prior fact. Existing clarification and permission state are unchanged. This is an incorporation declaration, explicitly not proof of terminal completion. S12 still owns production receipt creation and validation; S11/S83 and every runtime recovery finding remain open.

Verification: the two focused tests passed in 0.31 seconds. The exact subprocess exited naturally with code 0 and an empty descendant census under a 60-second owner deadline. Ruff and Ty passed on the three changed source/test paths. No legacy interpretation, translation or inferred receipt is present.

### initial-dispatch-authority | high | resolved at admission by S86; recovery consumption open

Formal self-review of `control/thread_service.py` and `control/tests/test_thread_service_tokens.py` passes the initial admission boundary. The effective dispatch is built before the run INSERT; the run, stable action identity and versioned non-secret input record commit in one transaction before HTTP. An independent database session inside the receiving HTTP handler reads the same non-secret input and dispatch id. An invalid project fails before any durable reservation; even an explicit caller commit leaves no run or action. Actor-token values are absent from the journal while their required-presence flag is retained. Concurrent completion, deletion and a different cancellation writer preserve their existing election behavior.

The initial admission part of incomplete-durable-dispatch is corrected. Recovery decoding and refusal, other action admission, frozen deadline authority and production incorporation remain open under S11/S12/S83; none is inferred from this result.

Verification: the first five-case battery exited naturally with five passes in 19.12 seconds and zero survivors. After adding the invalid-input discriminator, one six-case command printed six dots but exceeded its 60-second owner deadline before producing a summary; it was terminated with zero survivors and is classified FAIL. The same six-case battery then completed through the resource-aware runner with run timeout 60 seconds and exit timeout 5 seconds: six passed in 3.54 seconds, process exit 0. Ruff and Ty passed on both changed paths. The earlier timeout is retained as verification-lifecycle evidence for S85, not relabelled as a pass.

### graph-action-producer | high | partially corrected in S12; recovery remains open

Formal self-review confirms immutable journal receipts are persisted before graph dispatch, under the exact durable thread writer. A status-only revision preserves the original receipt; recovery cannot install an older action. New message, permission, clarification and verdict actions install ownership only from the witness observed before acquiring their lease. Initial accepted input excludes the derived receipt as well as transport secrets, avoiding a circular payload fingerprint. Worker admission refuses missing or mismatched current evidence before compilation. Graph input carries the receipt, and application notification reads the matching committed loop checkpoint instead of treating entry into execution as incorporation.

Verification: the initial admission and checkpoint declaration battery passed eight tests in 8.85 seconds; two real-SQLite ownership tests passed in 8.90 seconds; the real worker and StateGraph incorporation test passed in 0.67 seconds. All commands used the bounded runner and exited 0. The ownership test first failed at setup because its fixture belonged to another package, then failed validation because its request omitted required recursion_limit; both test construction defects were corrected before the reported passing run. Ruff passed changed production paths and receipt tests; focused Ty passed. Whole-project Ty reported eight diagnostics outside the receipt implementation, including concurrent provider work, so no whole-project type-check pass is claimed.

### cancellation-proof | high | open; S12 remaining work

Cancellation still emits terminal state from in-memory absence of an active ingest and has no durable cessation or no-op receipt. Graph incorporation deliberately excludes cancellation. S12 remains unchecked until the separate cessation evidence exists and is consumed.

### receipt-consumer-boundary | high | open; S13 dependency

The worker now emits checkpoint identity and its exact journal receipt, but generic progress-event settlement still trusts dispatch_id without validating those durable fields. S13 must precede recovery completion claims. Existing worker tests that construct pre-current graph requests require current authority; they have not been mass-adapted or counted as evidence of runtime completion.

### admission-transaction-gap | high | open; accepted-action atomicity

Follow-up and resume producers still commit their lease and requested projection before installing thread ownership. The binder fences network dispatch and prevents stale installation, but a crash between those transactions leaves an accepted action that recovery cannot promote. The single durable admission/recovery authority must commit accepted payload, writer and receipt together. Complete effective input storage currently covers initial admission only; other actions still require equivalent recoverable inputs.

### schema-refusal-verification | medium | open; migration evidence

Migration 0018 refuses populated pre-current stores instead of inventing historical graph receipts. Fresh-schema admission was exercised through the production migration-backed test fixture. A dedicated populated-store refusal and cancellation/no-op migration discriminator remains required. This partial S12 pass does not close the recovery conditions.

### physical-transaction-escape | high | corrected in continuing S12; broader contention review open

Formal review and a real SQLite test found reservation SAVEPOINT release committed a new accepted action before the intended outer transaction existed. Rolling back a failed writer election left that action present. This was reproduced as one failing test in the first two-case atomicity run (10.76 seconds, exit 1). The application engine now owns physical BEGIN before SAVEPOINT through SQLAlchemy events. Graph-action claim installs the writer and persists the receipt before committing its lease; delivery cannot promote a writer. The corrected two-case discriminator passed in 8.97 seconds with bounded runner exit 0. An independent session verifies accepted action, writer and receipt are visible together; stale refusal leaves no action row.

The graph writer/receipt portion of admission-transaction-gap is corrected. Permission/requested projections and full non-initial effective dispatch input still need integration into the durable authority. Explicit SQLite read transactions also expose lock or snapshot-upgrade contention that must be classified and scheduled through S83; this pass does not claim that retry owner is complete. Cancellation-proof and receipt-consumer-boundary remain open. Focused Ty passed; the continuing S12 row remains unchecked.