---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:e9ce91c4b4916287c1aea69de06f455608b91d3bc2105156e2f6c61ad39d1bc4'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-09-06-embedded-runtime-remediation-recovery-architecture-audit]]"
  - "[[2026-09-05-embedded-runtime-remediation-W02-P03-S83]]"
---
# `embedded-runtime-remediation` audit: `W02 P03 S83 recovery ledger review`

## Scope

Formal implementation review of S83 durable recovery scheduling, accepted-run deadlines, ordinary-operation draining, initial-dispatch recovery, exact authority races, migrations, and current-contract verification.

## Review verdict

The increment establishes a durable retry owner and closes the crash window between accepted action persistence and worker dispatch. It is safe to checkpoint as an incomplete S83 increment. S83 remains open because producer-side failure classification, deadline/application precedence, corrupted-input quarantine, and health disclosure still require architectural work.

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

## Findings

| Severity | Type | Status | Finding | Ownership |
| --- | --- | --- | --- | --- |
| RESOLVED HIGH | Architecture | Closed | Message, permission, clarification, cancel, and verdict producers now use one exact-authority failure boundary that persists the observed typed condition immediately and releases the action lease only for proven non-delivery. The old release-only helper was removed. | this increment |
| HIGH | Correctness | Open | Deadline expiry can race a worker application receipt. The coordinator can quarantine at the deadline before reading or incorporating concurrent exact checkpoint evidence. Establish one transactional precedence rule between application evidence and deadline settlement. | S83/S84 |
| HIGH | Invariant | Open | The nullable action deadline is enforced by service code rather than a schema-local discriminator. A recoverable accepted action can still be inserted without a deadline through lower-level repository APIs. Add a current-only dispatch-required invariant or narrow the repository surface. | S83 |
| RESOLVED HIGH | Correctness | Closed | Corrupt payloads and inconsistent deadlines now atomically reject the exact action, move its thread to reconciling, block execution readiness, and settle the retry as incompatible. A missing or type-corrupt action receipt preserves the last proven lifecycle state while atomically blocking readiness and settling the exact retry; no replacement authority is fabricated. | this increment |
| MEDIUM | Architecture | Open | Clarification has a separate startup redriver while the direct recovery coordinator also admits RESUME, producing fragmented ownership even though action leases prevent duplicate dispatch. Consolidate recovery ownership. | S11/S14 |
| MEDIUM | API semantics | Open | The shared live failure recorder returns only whether a definite non-delivery lease was released. A lost authority or expired deadline also returns false, which some callers interpret as ambiguous delivery; return a typed settlement result so response semantics cannot conflate these states. | S83/S84 |
| MEDIUM | Observability | Open | Periodic recovery exceptions are retained only as `app.state.direct_control_recovery_error` and logs; health/readiness does not disclose degraded recovery ownership. | condition matrix follow-up |
| RESOLVED MEDIUM | Operations | Closed | Lease contention now persists next eligibility at the known action-lease boundary, bounded by the accepted deadline, instead of waking every two seconds. | this increment |
| MEDIUM | Data lifecycle | Open | Settled recovery rows have no bounded retention or archival policy. | later persistence step |
| MEDIUM | Contract drift | Open | `RecoveryCondition` duplicates most of `FailureType`; mapping completeness can drift without an exhaustive current-contract assertion or one shared closed vocabulary. | S84 |
| MEDIUM | Test infrastructure | Open | Broad combined pytest lanes can pass many tests but exceed their bounded session deadline on this host; retain smaller authoritative lanes and investigate teardown/startup latency separately. | audit harness queue |
| RESOLVED HIGH | Correctness | Closed | Initial dispatch failure attempted to record stale recovery after an exact terminal or cancel action won in flight. A typed authority-loss result now preserves the winner and creates no stale ledger row. | this increment |
| RESOLVED MEDIUM | Correctness | Closed | Slow successful dispatch could schedule eligibility before observation. The schedule now clamps to delivery time and the lease boundary. | this increment |

## Recommendations

Continue S83 by defining application-receipt precedence at the deadline, then expose recovery-owner degradation through health and replace the live failure recorder boolean with a typed settlement result. Preserve current-only refusal semantics throughout.

## Handoff state

S83 is open. The reviewed runtime increment and migration 0020 are checkpointed in commit `a7ba047c`. Next work should define deadline-versus-application precedence, then expose recovery-owner degradation and type the live failure settlement result. Do not add compatibility behavior, aliases, inferred deadlines, or legacy-store backfill.
