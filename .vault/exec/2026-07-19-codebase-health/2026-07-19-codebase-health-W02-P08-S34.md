---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:5786ec2b4030f1ee6879e3d90928d394f5ae5f0cd0a1df3f67499b6844ec6fed'
step_id: 'S34'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Classify every Wave W02 review finding and append unresolved work to the audit queue

## Scope

- `.vault/audit/2026-07-19-codebase-health-audit.md`

## Description

- Take the formal Wave W02 review's findings and classify each by severity, type, and status.
- Append the six unresolved findings to the rolling audit queue.
- Reconcile five finding entries whose status lines contradicted the closure narrative already recorded in the same document.
- Correct the evidence commit attributed to the published-artifact closure.
- Record the shared blocked-proof root cause spanning two campaigns.

## Outcome

Classified and queued. Six unresolved findings from the review are now carried with
severity and status: three high - the unbounded replay on the integrity-error race, the
positive progress model with no producer, and the type-default pass-through in the
progress allowlist; two medium - the two enforcement layers that are not independent,
and the delete route that drops the abandoned-cleanup outcome; one low - the latent
subscriber slot leak. The delete-route entry supersedes the earlier cleanup-abandonment
finding, carrying the confirmed caller-visible consequence and the correct repair, which
is a success-carrying-the-flag response rather than a retryable error, since the saga is
settled and signalling retryable would invite a client to re-drive a completed deletion.

Five entries were reconciled from open to closed. Each had already been closed with
evidence by the 2026-07-25 fleet pass, recorded in this document's own narrative, while
the individual entry status lines still read open - so the document contradicted itself
and the open count was inflated. Every one was re-derived independently from source at
HEAD before being flipped rather than retired on the strength of the claim, because a
wrongly-retired finding does more damage than a stale-open one. The boot-harness orphan
reap needed no change, already carried as fixed in both homes.

One evidence correction landed: the published-artifact closure is commonly attributed to
the commit that added its drift gate, but that commit touched only the gate's test. The
artifact itself was regenerated in an earlier commit. Both are now cited for what they
actually did.

The queue also gained a reconciliation note for two live proofs that failed today with
one shared root cause - an engine binary predating the token-mint route - so a stale
cross-repository binary is recorded as a blocker spanning two campaigns rather than as
an incident inside one.

## Notes

The owning Wave W02 review returned REVISE, so this classification deliberately does not
close that review's Step. Two Steps closed under the Wave do not deliver what their rows
charter: the replay conflict is required on both the normal and the integrity-error path
and the integrity-error branch compares nothing, and the positive progress model that
two Steps define is constructed by no production path. Those revisions are queued work,
not a re-write, and they must land before the review Step can honestly close.

No source code was changed by this Step; it is a queue and classification pass only.
