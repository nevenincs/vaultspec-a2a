---
tags:
  - '#adr'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-09-05'
body_schema: 'body-v1'
body_hash: 'sha256:d58d2be809cc62e6948c24bf717fd201b2d8c89409801b2c4f183878d582ba81'
related:
  - "[[2026-08-02-control-action-leases-research]]"
  - "[[2026-08-02-control-action-leases-reference]]"
  - '[[2026-09-05-embedded-runtime-remediation-research]]'
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
- Existing six-verb gateway compatibility remains unchanged.

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
