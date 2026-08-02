---
tags:
  - '#adr'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:b8a5fd1d69543d855fd22437cf7deed37e6ac1d0fd0cd4d252cd8f539fb56eed'
related:
  - "[[2026-08-02-control-action-leases-research]]"
  - "[[2026-08-02-control-action-leases-reference]]"
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
- Application settles only from a request-scoped checkpoint receipt or authoritative worker progress.
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
