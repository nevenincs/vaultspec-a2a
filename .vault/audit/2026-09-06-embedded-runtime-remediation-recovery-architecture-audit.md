---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:4aa0a7bcef21a06535ddc0058484a24fb441513c06c2f234da23eaba08df5df0'
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
