---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:8bdd976730327bd8dd8bc1eaef59ef8d715a36b9a2c6498713c68312c746e7fb'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-06-embedded-runtime-remediation-recovery-architecture-audit]]"
---
# `embedded-runtime-remediation` audit: `W02 P03 S83 recovery ledger review`

## Scope

Formal implementation review of S83 durable recovery scheduling, accepted-run deadlines, ordinary-operation draining, initial-dispatch recovery, exact authority races, migrations, and current-contract verification.

## Review verdict

The reviewed increment now covers durable retry ownership, typed producer failure settlement, corrupt-input quarantine, exact lease races, applied-action rechecks, and recovery-owner health disclosure. It is safe to checkpoint as an incomplete S83 increment. S83 remains open for checkpoint/deadline precedence and schema-local deadline authority.

## Implemented state

- Every executable shipped graph declares a positive run timeout; executable graph freezing refuses an absent or non-positive budget.
- Recoverable control actions persist one immutable absolute recovery deadline. Current-only migration 0020 refuses populated stores because historical deadlines cannot be inferred.
- Recovery attempts are exact to thread, run revision, writer generation, action type, and action receipt. Missing schedules are seeded only for the current active unapplied authority.
- A periodic two-second application owner drains due recovery work during startup and ordinary operation. Empty ledgers do not start a lazy worker.
- Capacity, circuit-open, rejection, unreachable transport, permanent refusal, and deadline expiry follow typed retry or quarantine paths.
- Worker scheduling acknowledgement leaves the retry open until durable application evidence appears.
- Initial dispatch failure keeps accepted work recoverable instead of electing a false FAILED terminal.
- An exact terminal or competing accepted action that wins during initial dispatch suppresses stale retry creation and remains authoritative.
- Successful dispatch rescheduling is clamped to the later of delivery observation and action-lease expiry, within the accepted deadline.

## Verification evidence

| Result | Command surface | Natural result |
| --- | --- | --- |
| PASS | thread service token and terminal-race suite | 6 passed in 12.73s |
| PASS | recovery repository, direct recovery, and direct lease suite | 17 passed in 62.73s |
| PASS | corrupt accepted-input quarantine proof | 1 passed in 3.57s |
| PASS | missing accepted-action quarantine proof | 1 passed in 3.56s |
| PASS | live producer typed-condition repository proof | 5 passed in 28.20s |
| PASS | exact-lease typed settlement repository proof | 5 passed in 36.12s |
| PASS | selected typed message and cancel settlement proofs | 3 passed, 5 deselected in 68.93s |
| PASS | applied-action versus deadline quarantine proofs | 2 passed, 6 deselected in 4.13s |
| PASS | recovery-owner service degradation proof | 1 passed in 3.03s |
| PASS | live message definite/ambiguous classification proof | 1 passed in 25.65s |
| PASS | full direct-control lease suite | 8 passed in 71.82s |
| FAIL | dispatch-failure transition suite | 3 non-current fixtures refused for missing initial action/receipt authority; 3 passed in 43.98s |
| FAIL | three-test quarantine lane | no session result within 60s; owned tree reaped |
| PASS | earlier combined focused recovery/cancel/receipt suite | 20 passed, 4 deselected in 34.70s |
| PASS | earlier team config, frozen graph, and schema parity suite | 163 passed in 49.06s |
| PASS | Ruff over all changed production and migration modules | all checks passed |
| PASS | Ty over all changed production modules | all checks passed |
| PASS | git diff whitespace review | no errors |
| FAIL | dispatch-failure transition suite | 3 stale fixtures lack current initial action/receipt authority; 4 passed |
| FAIL | earlier broad combined lane | emitted 65 passes, then exceeded 60s and was reaped |
| UNVERIFIED | pre-compaction thread-service run | process session disappeared before a natural result |
| FAIL | current team config, frozen graph, and schema parity lane | 227 passed in 39.73s, then the owned process tree missed the 5s exit deadline and was reaped |
| PASS | isolated recovery repository timing probe | 1 passed in 2.56s; bounded owner returned naturally in 15.40s |
| PASS | cold-start localization | virtualenv Python 0.405s; graph import 0.441s; action-lease import 4.113-4.965s; collect-only wall 7.888s versus pytest-reported 1.20s |

## Findings

| Severity | Type | Status | Finding | Ownership |
| --- | --- | --- | --- | --- |
| RESOLVED HIGH | Architecture | Closed | Message, permission, clarification, cancel, and verdict producers now use one exact-authority failure boundary that persists the observed typed condition immediately and releases the action lease only for proven non-delivery. The old release-only helper was removed. | this increment |
| HIGH | Correctness | Open | Deadline quarantine now locks and rechecks the exact action, so an already-durable `applied_at` wins. A checkpoint application receipt can still arrive concurrently without a persisted incorporation timestamp proving whether it preceded the deadline. Establish one transactional precedence rule using S12 incorporation evidence before closing this condition. | S12/S83/S84 |
| HIGH | Invariant | Open | The nullable action deadline is enforced by service code rather than a schema-local discriminator. A recoverable accepted action can still be inserted without a deadline through lower-level repository APIs. Add a current-only dispatch-required invariant or narrow the repository surface. | S83 |
| RESOLVED HIGH | Correctness | Closed | Corrupt payloads and inconsistent deadlines now atomically reject the exact action, move its thread to reconciling, block execution readiness, and settle the retry as incompatible. A missing or type-corrupt action receipt preserves the last proven lifecycle state while atomically blocking readiness and settling the exact retry; no replacement authority is fabricated. | this increment |
| MEDIUM | Architecture | Open | Clarification has a separate startup redriver while the direct recovery coordinator also admits RESUME, producing fragmented ownership even though action leases prevent duplicate dispatch. Consolidate recovery ownership. | S11/S14 |
| RESOLVED HIGH | Concurrency | Closed | Live failure settlement now returns a closed disposition for definite non-delivery, ambiguous delivery, lost authority, expired deadline, or application victory. It verifies the exact action lease token before changing the retry ledger, so a stale dispatcher cannot overwrite a newer owner condition. | this increment |
| RESOLVED HIGH | Observability | Closed | A periodic recovery-owner failure now uses the closed `recovery_pass_failed` token, degrades the authenticated service health check, keeps process liveness true, and blocks new run admission until a successful pass clears the condition. | this increment |
| RESOLVED MEDIUM | Operations | Closed | Lease contention now persists next eligibility at the known action-lease boundary, bounded by the accepted deadline, instead of waking every two seconds. | this increment |
| MEDIUM | Data lifecycle | Open | Settled recovery rows have no bounded retention or archival policy. | later persistence step |
| MEDIUM | Contract drift | Open | `RecoveryCondition` duplicates most of `FailureType`; mapping completeness can drift without an exhaustive current-contract assertion or one shared closed vocabulary. | S84 |
| MEDIUM | Test infrastructure | Open | A narrow recovery test spends about 0.37s in setup/body and reports completion in 2.56s, while the bounded owner takes 15.40s end to end. No orphaned pytest process remains and plain Python starts in 0.405s. Cold import profiling attributes 4.965s to `control.action_lease`, including 4.278s under the eager `database` package initializer and 2.092s under schema validation/migration imports. Replace the 69-caller aggregate persistence import surface with direct repository boundaries in a dedicated pass; do not preserve it through compatibility aliases. | audit harness queue |
| RESOLVED HIGH | Correctness | Closed | Initial dispatch failure attempted to record stale recovery after an exact terminal or cancel action won in flight. A typed authority-loss result now preserves the winner and creates no stale ledger row. | this increment |
| RESOLVED MEDIUM | Correctness | Closed | Slow successful dispatch could schedule eligibility before observation. The schedule now clamps to delivery time and the lease boundary. | this increment |
| RESOLVED HIGH | Concurrency | Closed | Deadline classification is now written only after locking and rechecking the exact thread and action; an action already marked applied cannot acquire a contradictory deadline ledger row. | this increment |

## Recommendations

Continue S83 by defining application-receipt precedence at the deadline and enforcing the recoverable-action deadline invariant at the repository/schema boundary. Preserve current-only refusal semantics throughout.

## Handoff state

S83 is open. Runtime work is checkpointed through `a164f120`, with Vault status through `7de34fc0`. The next implementation target is the recoverable-action deadline invariant at the repository/schema boundary. Deadline-versus-application closure requires S12 persisted incorporation evidence. The measured test delay is cold aggregate import/collection overhead, not a surviving pytest tree; its 69-caller persistence boundary conversion remains queued. Do not add compatibility behavior, aliases, inferred deadlines, or legacy-store backfill.
