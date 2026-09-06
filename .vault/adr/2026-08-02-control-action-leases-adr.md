---
tags:
  - '#adr'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-09-06'
body_schema: 'body-v1'
body_hash: 'sha256:7b8b62f6ddcfbb78f05ce30d2e350f9c9157209bf65c7760abc0e38c3d48b050'
related:
  - "[[2026-08-02-control-action-leases-research]]"
  - "[[2026-08-02-control-action-leases-reference]]"
  - '[[2026-09-05-embedded-runtime-remediation-research]]'
  - '[[2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-research]]'
---
# `control-action-leases` adr: `durable leased dispatch claims` | (**status:** `accepted`)

## Problem Statement

Concurrent or retried control requests must not dispatch the same intention more
than once, while a gateway or worker crash must not strand a durably accepted
intention. Clarification exposed the defect, and the same ordering exists across
permission, follow-up, cancel, and verdict paths. The decision is grounded by
`2026-08-02-control-action-leases-research` and
`2026-08-02-control-action-leases-reference`.

## Considerations

- The database must elect one dispatcher across processes, not only one event loop.
- Worker acceptance is asynchronous and cannot stand for graph application.
- Lost acknowledgements require stable dispatch identity and recoverable payload.
- Existing journal and checkpoint owners remain single homes for their facts.
- Competing bodies conflict without disclosure or silent winner substitution.

## Considered options

- **Extend the generic control journal with renewable dispatch leases (chosen).** One atomic primitive covers every affected caller and retains audit identity.
- **Create a clarification-only resolution table.** Rejected because it leaves equivalent races and duplicates claim machinery.
- **Copy the verdict metadata lease.** Rejected because whole-blob read and write is not a conditional multi-writer election.
- **Rely on the worker's per-thread active slot.** Rejected because admission precedes slot acquisition and gives the gateway no replay contract.

## Constraints

- Reservation and lease acquisition are conditional database writes committed before network dispatch.
- The winning typed payload and stable dispatch ID are durable.
- Fresh leases replay without dispatch; expired leases permit one recovery dispatcher.
- Definite non-delivery releases ownership; ambiguous delivery waits for reconciliation or expiry.
- Graph-mutating message, clarification, permission and verdict actions settle only from durable request-scoped evidence associating action identity, winning payload fingerprint and dispatch identity with a persisted checkpoint proving incorporation. Cancellation settles from durable action-specific cessation or terminal/no-start no-op evidence; it does not require a checkpoint for work that never started. Worker acceptance, first output, generic progress and provider completion alone do not establish application or cessation. Recovery reconciles the journal with the evidence required for that action kind before redelivery; uncertain external effects are not blindly replayed.
- Worker dispatch-ID suppression is synchronous, bounded, and cleared on restart.
- The current six gateway verbs retain their exact contracts; retired inputs are refused and carry no compatibility behavior.

## Implementation

Add lease token, expiry, and stable dispatch identity to the control-action journal.
Repository operations atomically reserve an intention, acquire or renew one lease,
release definite failures, compare replay payloads, and settle application. Migrate
clarification, permission, message, cancel, and verdict callers to this owner.

Clarification adds a request-id and fingerprint receipt to checkpointed graph state,
and restart reconciliation classifies and redrives parked clarification actions from
journal plus checkpoint truth. The worker suppresses repeated stable dispatch IDs
before scheduling.

The journal owns pending delivery. One renewable dispatcher per run drains eligible messages in durable acceptance order during ordinary operation and after restart. A busy worker never removes accepted work. Admission atomically enforces configured positive per-run and service queue limits before acknowledgement; overflow has a typed retryable disposition. Duplicate requests retain their original position and payload, while conflicting retries refuse. Typed clarification and permission answers retain their dedicated request-scoped paths.

Cancel and interrupt bypass ordinary execution-capacity admission while remaining authenticated, bounded and idempotent. Cancellation can wake a blocked event/provider await. Acknowledgement, cessation and terminal settlement remain separate observations; unresolved cessation is disclosed for reconciliation.

Worker saturation is admission backpressure, not evidence of transport failure, and does not open the shared failure breaker. Recovery atomically reserves the configured half-open probe allowance; success, failure or abandoned ownership settles it before replacement admission.

Storage admission uses bounded transactions and a typed retryable refusal on exhausted contention. No durable acceptance is reported for an uncommitted run. Transaction diagnosis precedes tuning; increasing the busy timeout alone is not a proven remedy. Network dispatch follows committed acceptance. Atomic run-state election remains owned by the state-truthfulness ADR.

Grounding for the 2026-09-05 refinement: `2026-09-05-embedded-runtime-remediation-research`. Accepted under the owner's explicit ADR auto-approval; implementation awaits plan approval.

## Rationale

The shared lease closes every discovered race without forking current-state tables
per verb. It combines the journal's existing unique identity with renewable
ownership, while checkpoint receipts preserve the stronger rule that application
belongs to graph state. This follows `2026-08-02-control-action-leases-reference`
and `2026-08-02-control-action-leases-research`.

## Consequences

- Concurrent identical requests replay one durable outcome; competing intentions receive conflict.
- Gateway and worker restarts can redrive stale unapplied work without changing dispatch identity.
- Clarification, permission, message, cancel, and verdict share one election mechanism.
- Database migrations, lifecycle deletion, worker memory bounds, and recovery tests expand the implementation surface.
- Lease duration becomes an operational parameter tested against slow real-provider turns.
## Amendment (2026-09-06): durable recovery scheduling

The recovery coordinator decided by the state-truthfulness ADR leases recovery work through a durable recovery record rather than a one-shot startup sweep. The record binds the current run revision, writer generation and applicable action receipt to the classified condition, attempt number, next eligible attempt and run-derived deadline. One dispatcher may own an eligible attempt; crash or lease expiry makes it eligible again without changing action identity.

Permanent current-schema refusal settles atomically and is never retried. Circuit-open, capacity and transport-unreachable outcomes retain accepted work and schedule typed retry. Capacity does not affect transport health. Transport failure may affect the circuit breaker. Worker rejection follows its served reason. Ambiguous delivery reconciles checkpoint and action evidence before redelivery.

Checkpoint terminal truth takes precedence over timeout classification. A receipt mismatch is a current-schema integrity refusal, not a reason to leave accepted work pending. Startup and ordinary operation drain the same durable recovery owner. API reads may request an immediate coordinator pass but cannot create a second lease policy or report a pre-election projection.

No retired action, provider or ownership representation is supported. Recovery never translates, backfills, aliases, substitutes or dispatches it.

### Complete input precedes durable acceptance

An initial graph action is accepted only when its run row, stable action receipt and complete effective non-secret dispatch input are committed together. Resolve local configuration and project inputs before acquiring the database write lock. The initial message, frozen assignment, effective controls and context belong to the accepted input; title and preset identifiers alone cannot authorize recovery of them.

Ephemeral actor tokens never enter the journal or checkpoint. The durable record states whether the accepted dispatch requires those credentials. Recovery must obtain credentials through their existing authorized owner or return a typed refusal; it may not silently omit required tokens, store them durably, or substitute ambient authority. Missing or retired dispatch records are refused without reconstruction, translation or backfill. General checkpoint incorporation receipts identify the exact accepted journal action and payload; they do not certify terminal completion.

### Transaction ownership at action acceptance

Graph-action acceptance commits the reserved action, renewable lease, conditional thread writer and immutable graph receipt in one database transaction. A lost prior-writer witness refuses acceptance and rolls back the reservation. Recovery may renew only an action that already owns the current run; delivery cannot promote an action in a later transaction.

The application engine owns the physical SQLite BEGIN boundary before any SAVEPOINT. Releasing a reservation savepoint must not commit an action independently of the outer acceptance transaction. SQLAlchemy's transaction event begins that transaction; driver-delayed BEGIN is not an alternative authority. Cancellation still requires its separate durable cessation or no-op evidence.