---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:58c2487b73188273fdac7ab843a9e7d0e529469e5b2929b2c4f0f2585abecfbe'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-audit]]"
---
# S11 recovery architecture root-cause research

## Result

The seventeen observed conditions reduce to two architectural failures. Conditions 1 through 16 share a fragmented run-recovery authority: startup dispatch, read-time abandonment, checkpoint truth, action receipts, retry timing, and response projection are decided by different components without one durable recovery record. Condition 17 is a separate process-lifecycle ownership failure in the verification runtime.

The existing S11 patch protects three writes but cannot resolve the fragmented authority. The recovery architecture must first classify durable evidence, then elect or schedule one outcome, and finally project a fresh row. Startup, periodic operation, and an API read may trigger the same coordinator; none may implement a separate recovery policy.

## Findings

### Permanent current-schema refusals: conditions 1-5 and 13

Absent, corrupt, or retired provider authority; absent or invalid project identity; and a receipt that does not correspond to its current durable action cannot be recovered by retry. They require a bounded typed incompatible outcome through the atomic election. Retired input is refused as unsupported current state and is never parsed, translated, migrated, substituted, or dispatched.

### Retryable worker availability: conditions 6-9

Circuit-open, capacity, transport-unreachable, and worker rejection are presently logged and forgotten while the run remains `reconciling`. One durable recovery record must retain the exact run revision, action receipt, classified condition, attempt number, next eligible attempt, and derived deadline. Capacity is backpressure. A transport failure affects breaker health. A worker rejection must be classified by its typed reason rather than grouped automatically with either one.

### Abandonment and client observation: conditions 10 and 16

A run-derived execution deadline and a client's 90-second observation deadline answer different questions. The client deadline cannot force a valid long run to fail, while the API cannot return bare `reconciling` until a 300-second floor expires. Before the observation deadline, the durable response must disclose the recovery condition and next attempt or a terminal refusal. The recovery coordinator continues independently of the polling client.

### Concurrency and disappearance: conditions 11-12

Every recovery decision uses the exact state, run revision, writer generation, action type, and receipt observed by the coordinator. A newer terminal writer wins. A deleted run produces a no-op/not-found outcome. Neither case is rewritten as recovery failure.

### Checkpoint truth: condition 14

Checkpoint completion or failure is evaluated before abandonment. A checkpoint that proves a terminal graph result settles that result through the same election. Only a nonterminal checkpoint with an expired run-derived deadline may become reconciled failure. Unreadable checkpoint state remains an explicit recovery condition; it is not evidence of completion, cessation, or failure.

### Served projection: condition 15

A projection captured before reconciliation is not safe to serve. After any election attempt, including loss, the response is rebuilt from a fresh durable read. Terminal and deleted winners are removed from active discovery immediately.

### Verification lifecycle: condition 17

A test result and process completion are separate obligations. The resource-aware test owner must close plugin sessions, database engines, subprocess transports, and leases under one bounded finalizer. Printing `[100%]` is not process-exit evidence. A verification command qualifies only when the owned process exits naturally within its declared teardown budget or reports a classified cleanup failure with zero survivors.

## Sources

- `2026-09-05-embedded-runtime-remediation-implementation-review-audit`
- `2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-audit`
- `2026-08-05-served-capability-contract-state-truthfulness-adr`
- `2026-08-02-control-action-leases-adr`
- `src/vaultspec_a2a/control/dispatch.py`
- `src/vaultspec_a2a/control/run_discovery_service.py`
- `src/vaultspec_a2a/database/thread_repository.py`
- `src/vaultspec_a2a/testing`

## Architecture review follow-up

The production review in `2026-09-06-embedded-runtime-remediation-recovery-architecture-audit` identifies missing prerequisites beneath the proposed coordinator. General immutable checkpoint action receipts were absent; startup still used unconditional lifecycle writes; and worker preflight equated empty pending writes with completion. The initial action journal retained title, preset and autonomous input but omitted initial message content and effective dispatch arguments. The graph-action receipt declaration is now implemented; production evidence still depends on durable admission retaining the input it is supposed to certify.

The initial dispatch can be constructed before the database write transaction because `ThreadCreationRequest` already carries the allocated run id. Persisting its non-secret serialized input together with the run removes the crash window without holding the SQLite write lock during project/configuration reads. Actor-token values remain transport-only; recovery needs an explicit fact stating whether such credentials are required. The audit retains the remaining coordinator, checkpoint, integrity-quarantine, deadline and demand-gate findings.

## Immutable receipt production follow-up

Graph receipt creation cannot recompute identity from every current thread revision: normal status transitions advance the revision while the accepted action remains unchanged. Persist the original receipt once on the action journal, and return that exact receipt on retries under the current matching writer generation. A new action may install ownership only from its pre-lease thread witness; recovery cannot promote a stale action. Real independent-session tests distinguish these cases.

The partial producer also exposes an earlier atomicity gap: follow-up and resume acceptance commits before writer installation. Fencing delivery prevents stale execution but does not make that acceptance recoverable after a crash. Consolidation must move acceptance, complete effective input, writer and receipt into one durable transaction. Cancellation remains a separate cessation/no-op evidence problem, and event consumers must verify checkpoint receipts before settling leases. These findings remain queued in the recovery architecture audit.

## Physical transaction boundary finding

A real SQLite discriminator showed that rejecting stale authority and rolling back the session left the reserved action committed. The repository wrapped its INSERT in SAVEPOINT before the driver had emitted BEGIN. Releasing that savepoint committed the action independently of the intended outer transaction. This matches the documented SQLite driver behavior in the [SQLAlchemy transaction documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#enabling-non-legacy-sqlite-transactional-modes-with-the-sqlite3-or-aiosqlite-driver).

The production application engine now owns BEGIN through SQLAlchemy's begin event and disables the driver's delayed BEGIN. This makes the lease transaction a physical transaction before the reservation savepoint. Graph writer election and receipt persistence move inside that same lease transaction. A later delivery binder can read current evidence but cannot install ownership. The stale-action discriminator verifies no reservation survives rollback; the success discriminator reads action, writer and receipt from an independent session before delivery.

## Completion evidence without provider reconstruction

The served compiler has explicit successful terminal routes in star, pipeline, pipeline-loop and research/ADR topologies. Routing each through one finalizer makes successful completion a durable graph output associated with the explicitly active accepted action. Recovery can inspect this committed receipt directly without recompiling mutable provider or graph configuration. The finalizer checks incorporation identity before recording completion, and immutable receipt maps retain prior actions without confusing them with a newly accepted action.

A real checkpointer test completes one action, interrupts a second, reopens the checkpoint and resumes under a third accepted receipt. The first completion remains present while the second is pending; after resume, only the first and third actions carry completion. Production topology inspection verifies END has only the finalizer as predecessor. Failure and cancellation are separate outcomes; their absence must not be converted into successful completion.

## Partial shared recovery consumer

The gateway can settle an exact successful graph completion without provider reconstruction. One reader validates current action incorporation and completion, classifies unavailable, incompatible, prior, pending, interrupted and failed evidence, and never infers completion from empty pending writes. Startup and served reads use the same database election and fresh post-election projection. An explicit startup trigger distinguishes abandoned process ownership from live execution observed by a read.

This removes mutable configuration and wall-clock row age as deadline authority. It does not supply the missing frozen execution deadline or retry lease: those require durable accepted control inputs and scheduling ownership. Worker preflight, notification settlement and deferred replay must consume the same authority before the recovery architecture is complete.
