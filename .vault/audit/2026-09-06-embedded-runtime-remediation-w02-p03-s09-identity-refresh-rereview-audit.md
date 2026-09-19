---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:79d9f84dd59ac3f180d258dc2b211c9f40d7be611b431557093334f2964a8089'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-08-05-served-capability-contract-state-truthfulness-adr]]"
  - "[[2026-09-05-embedded-runtime-remediation-research]]"
  - "[[2026-09-06-embedded-runtime-remediation-w02-p03-s09-atomic-election-review-audit]]"
---
# embedded-runtime-remediation audit: W02.P03.S09 identity refresh correction rereview

## Scope

Independent formal rereview of correction 2fab08a4a415fb5ba9266f6fdbef94265dc2a820 against implementation 8c37f800bdf9e8e0c47565a5f0360d573b421bef, formal FAIL 7aa096ec, accepted state-truthfulness T6, the S76/S77 authority contract, remediation research, plan and execution record. The rereview targeted same-session visibility of status and all four authority fields, the post-win populate-existing read, transaction and race behavior, receipt flushing, bounded contention evidence and current-only scope.

## Findings

### same-session-election-state | high | resolved by an exact post-win identity-map refresh

Type: lifecycle correctness and transaction consistency. Status: resolved. After the conditional update reports one affected row, the correction selects the exact thread with populate-existing before returning WON. The regression preloads the ThreadModel, creates a changed-action CANCEL receipt in the same session, wins the election, and proves the identical mapped object observes CANCELLED, revision one, generation two, CANCEL and the exact receipt both before and after commit under expire-on-commit false. This closes the HIGH defect recorded by formal FAIL 7aa096ec.

### winner-refresh-transaction-order | low | no new election or external race window is introduced

Type: transaction semantics. Status: verified. The refresh occurs only after one-row success and inside the same transaction. SQLite retains the write transaction; PostgreSQL retains the updated row lock until transaction end. The exact-row select therefore reads the transaction's own elected values and cannot be interleaved with an external delete or conflicting update before the refresh. It does not perform a second ownership decision. The production session factory uses normal autoflush, and the regression proves a newly added same-transaction control receipt is flushed before the conditional update evaluates its EXISTS predicate.

### exact-election-and-contention | low | conditional ownership behavior remains intact

Type: durable state ownership. Status: verified. The correction does not alter the status-plus-four-authority predicate, successor revision and generation rules, receipt correspondence, typed dispositions, failure metadata or transition map. The election suite covers both COMPLETED-versus-CANCELLED stale orderings, early SUBMITTED completion, every stale authority dimension, missing and mismatched receipts, changed-action generation, terminal non-reopen and failure-reason bounds.

### production-writer-adoption | high | deferred current callers remain open under their named steps

Type: integration scope. Status: open and queued. Transitional writers and archive/deletion entry remain assigned to S10, abandoned reconciliation to S11, terminal evidence and settlement to S78/S12/S13, and durable terminal retry to S14. The unconditional status writer remains until those current callers migrate. ER02 is not closed by this correction.

### archive-deletion-adoption | high | atomic teardown entry remains open in S10

Type: lifecycle integration. Status: open and queued. Archive and deletion-saga creation plus DELETING entry still require election adoption in one caller-owned transaction. S10 retains that explicit ownership.

### postgresql-election-proof | medium | live PostgreSQL evidence remains open

Type: portability evidence. Status: open under the existing PostgreSQL server-profile proof obligation. The correction's read-after-write and row-lock shape is valid SQLAlchemy transaction behavior, but no locked live PostgreSQL service was available to prove READ COMMITTED predicate recheck and affected-row behavior.

### current-only-semantics | low | correction adds no legacy or deprecated behavior

Type: compatibility boundary. Status: verified. The correction refreshes only a current row after its complete authority and matching receipt won. It adds no default, backfill, nullable authority, inferred history, translation, alias, fallback, compatibility lane, deprecated provider behavior or legacy execution path.

### bounded-verification | low | correction gates complete without a hang

Type: verification. Status: verified. The complete focused election suite passed 10 tests in 3.66 seconds, including same-session identity truth and both stale terminal orderings. Ruff and Ty passed on the exact correction production and test paths. No retained process remained, and PID 58992 was not touched.

## Recommendations

Accept correction 2fab08a4a415fb5ba9266f6fdbef94265dc2a820 as a formal PASS for the S09 implementation boundary. Keep the plan Step open until the separate lifecycle closure record and review are complete. Preserve production adoption, archive/deletion adoption and live PostgreSQL proof under their existing owners.
