---
tags:
  - '#audit'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:879b43906424b4ad39ed94d06d85f00b456b5251993bd86a77f560c86465c726'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
  - "[[2026-08-02-control-action-leases-adr]]"
---

# `control-action-leases` audit: `leased control dispatch implementation review`

## Scope

Reviewed the durable control-action lease implementation against the accepted
decision and execution plan. The review covered database election and migration,
worker admission, clarification and permission resumes, direct message and cancel
controls, verdict redrive, application receipts, restart reconciliation, public
wire disclosure, deterministic concurrency tests, and real Codex certification.

## Findings

### leased control dispatch implementation review | high | lookup before dispatch allowed duplicate graph resumes

Clarification, permission, message, cancel, and verdict callers previously read
for an action and dispatched before a committed cross-process election. The
shared reservation and renewable lease now commits ownership and a stable
dispatch identity before network I/O; real concurrent SQLite and HTTP tests prove
one dispatch or an explicit payload conflict.

### leased control dispatch implementation review | high | worker acknowledged duplicate dispatch identities as new work

The worker previously acknowledged before reserving a stable task identity, so a
lost acknowledgement could schedule the same graph command again. Synchronous
bounded admission now runs before task scheduling and duplicate IDs receive a
normal acknowledgement without a second Executor task.

### leased control dispatch implementation review | high | transport acknowledgement falsely marked message application

Follow-up messages marked repair state applied immediately after HTTP acceptance.
That confused transport admission with graph application. The worker now emits a
private first-event receipt carrying the stable dispatch ID; the gateway settles
only the exact journal action and never projects the identifier onto positive SSE.

### leased control dispatch implementation review | high | dispatch identity was not database unique

Worker admission and receipt lookup treat dispatch ID as global identity, but the
initial schema allowed collisions. A globally unique nullable index now exists in
the model and migration; a real cross-thread collision test proves enforcement.

### leased control dispatch implementation review | high | rollback expired async ORM state and produced HTTP 500

Concurrent losing inserts roll back their session and expire previously loaded
objects. Message, cancel, the shared claim helper, and finally a live clarification
replay attempted synchronous attribute reads afterward, producing
`MissingGreenlet`. Required scalar state is now snapshotted before rollback and a
real-worker test races six replays during receipt settlement.

### leased control dispatch implementation review | high | ambiguous message delivery blocked lease redrive

An unreachable worker retained the lease but terminalized the run, making expiry
redrive ineligible. Ambiguous delivery now retains ownership without marking the
thread failed; definite non-delivery releases ownership.

### leased control dispatch implementation review | high | verdict acknowledgement was mistaken for graph application

The first formal review found verdict actions, document permission rows, and
thread status settled immediately after the worker returned HTTP success. Verdict
ACK now leaves all three pending. The first exact resume application receipt
settles the stable dispatch ID, permission request, and thread projection; real
worker and Executor tests replace the former ACK-only recording endpoint.

### leased control dispatch implementation review | high | historical rows had no claimable dispatch identity

Migration 0012 originally left pre-upgrade action rows with null dispatch IDs,
which made shared lease acquisition fail. Upgrade now backfills each historical
row from its immutable globally unique action primary key before creating the
unique index. A real 0011 insert, 0012 upgrade, and lease claim passes.

### leased control dispatch implementation review | high | ambiguous cancel delivery undid durable intent

An unreachable cancellation retained its lease but restored the pre-cancel
projection and reported rejection even though the worker may already have acted.
Ambiguous delivery now preserves accepted `CANCELLING` state and the canonical
lease; only definite non-delivery restores the prior repair projection.

### leased control dispatch implementation review | high | direct control leases lacked startup redrive

The first implementation only redrove clarification and verdict actions. Startup
now reconstructs expired permission, message, and cancel actions from their stored
typed payloads and stable dispatch IDs, restores requested state for fresh leases,
and performs a bounded TTL retry before generic reconciliation. Real restart tests
cover each direct action family.

### leased control dispatch implementation review | medium | verdict metadata claim was a whole-blob multiwriter race

Verdict resume ownership lived in thread metadata and could be overwritten by an
unrelated metadata writer. Verdicts now use the same row-level lease and atomic
permission settlement as the other controls; obsolete metadata helpers are gone.

### leased control dispatch implementation review | medium | generic progress could not correlate message application

Progress frames carry no dispatch or action identity. Selecting the latest message
would be unsafe, so an explicit internal `dispatch_applied` receipt was introduced
and consumed before public SSE projection.

### leased control dispatch implementation review | medium | permission progress settlement was not request exact

Generic progress previously applied every answered permission row on a thread.
It is now a no-op for application truth. Exact resume receipts correlate one
stable dispatch ID to one journal and permission request before settlement.

### leased control dispatch implementation review | high | permission acknowledgement still wrote applied repair state

The first re-review found the permission service still moved the thread to
`RUNNING` and wrote an applied repair projection on worker scheduling ACK;
startup recovery repeated the premature transition. Both ACK paths now preserve
`INPUT_REQUIRED`, `answered_pending_apply`, and requested repair state. Exact
`dispatch_applied` settlement exclusively owns application, `RUNNING`, commit,
and aggregator resolution. A real worker with no registered graph proves ACK
alone produces no applied state. The final focused re-review found no remaining
critical, high, or medium issue.

### leased control dispatch implementation review | medium | verdict tests encoded an ack-only stub contract

The verdict suite used a recording Starlette endpoint and asserted application
from its HTTP acknowledgement. Those tests now use the production worker app,
Executor, checkpointer, and callback bridge, assert ACK remains unapplied, then
relay an exact receipt and assert settlement.

### leased control dispatch implementation review | medium | startup reconciliation omitted parked clarification actions

Accepted clarification actions could remain parked forever after claim-before-
dispatch loss. Startup now classifies clarification interrupts, redrives expired
leases, and settles from request-scoped checkpoint receipts.

### leased control dispatch implementation review | low | live certification asserted stale response field names and excessive work

The initial service test read `provider` instead of the served `provider_id`,
expected a synthetic duplicate label instead of the durable applied status, and
waited for five research roles plus synthesis. It now asserts the production wire
shape and stops at authoritative graph application; completed Codex output is
certified independently through the production factory.

### leased control dispatch implementation review | low | post-teardown checkpoint reopen was unstable on Windows

The live test reopened a temporary WAL database after the certified gateway had
shut down and observed `disk I/O error`. The assertion duplicated the already
proven applied replay and one-copy transcript and was removed.

### leased control dispatch implementation review | low | strict typing baseline remains in shared large modules

Ruff and formatting pass across the affected clusters, and the new clarification
service is strict-clean. A wider selected BasedPyright invocation still reports
pre-existing diagnostics in shared database model representations, worker route
registration, and Executor typing. Those baseline diagnostics are not presented
as a passing gate.

### leased control dispatch implementation review | low | endpoint test retained unused imports after concurrent edits

The final broad Ruff pass found two unused imports in the shared permission
endpoint test after concurrent worktree edits. They were removed and the full
affected-cluster lint and formatting gates then passed.

### leased control dispatch implementation review | low | plan scaffold examples parsed as identifiers without canonicalisation

The VaultSpec plan serializer initially treated scaffold comment examples as real
wave and phase identifiers. Recreating the plan and using `--canonicalise`
prevented the false entries. This is a cross-repository VaultSpec CLI tooling
finding, not an A2A runtime defect.

## Recommendations

Keep every future control verb on the shared lease and stable dispatch identity;
do not add per-route lookup-before-create orchestration. Require an authoritative
application receipt whenever checkpoint state cannot correlate the action
directly. Retain the unique dispatch-ID index and migration ratchet. Add the
remaining shared-module strict diagnostics and the VaultSpec serializer comment
parsing defect to their owning maintenance queues; neither weakens the green
runtime and live-provider evidence recorded here.
