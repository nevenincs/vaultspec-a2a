---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:dff0091a1186eb5fc955eab2c249ce3f39ae27e000b9cfb61ac56ec1051e1eb8'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-08-05-served-capability-contract-state-truthfulness-adr]]"
  - "[[2026-09-05-embedded-runtime-remediation-research]]"
  - "[[2026-09-05-embedded-runtime-remediation-W02-P03-S09]]"
---
# embedded-runtime-remediation audit: W02.P03.S09 atomic lifecycle election formal review

## Scope

Independent formal review of implementation commit 8c37f800bdf9e8e0c47565a5f0360d573b421bef against accepted state-truthfulness T6, the remediation ADR, research, plan Step W02.P03.S09, execution record, rolling audit, S76/S77 current authority schema and the exact implementation diff. The review attempted to falsify the exact status-plus-four-authority compare-and-swap, successor rules, same-thread/action/receipt correspondence, typed dispositions, concurrent terminal settlement, early completion, terminal non-reopen, failure metadata, transaction visibility and current-only scope.

## Findings

### same-session-election-state-remains-stale | high | a winning election leaves the caller's identity-mapped thread at the losing state

Type: lifecycle correctness and transaction consistency. Status: open and blocking W02.P03.S09. The SQL update disables session synchronization and returns only an outcome. A real file-backed SQLite discriminator loaded the thread into the same AsyncSession, won RUNNING to COMPLETED, then read the identical mapped object as RUNNING with revision zero. The session uses expire_on_commit=False; after commit that object still reported RUNNING and revision zero. A caller performing same-transaction effects or deriving a follow-up witness from that object can therefore act on state that contradicts its own successful election. This violates T6's truthful ownership boundary even though a fresh session reads the correct durable row.

### exact-conditional-election | low | exact predicate, successor rules and receipt correspondence are verified

Type: durable state ownership. Status: verified subject to the blocking identity-map defect. The single SQL update predicates thread id, expected status, run revision, writer generation, action type, action receipt and an existing same-thread/same-action control-action dispatch. One affected row is the only winning outcome. Revision advances by exactly one; generation remains fixed for the same action identity and advances by exactly one for a new action identity. Missing rows, receipt mismatch and lost elections have distinct closed outcomes. Failure reason and provider condition values, when present, are part of the same conditional update; the reason retains the repository's byte cap.

### terminal-race-and-early-completion | low | terminal results cannot reopen and early completion has an admissible atomic path

Type: lifecycle behavior. Status: verified at the primitive boundary. Both COMPLETED-versus-CANCELLED stale orderings produce one winner and one loser. A reviewer-run overlapping SQLite discriminator also produced exactly one winner and one loser. SUBMITTED to COMPLETED is admitted, and its late RUNNING witness loses. The transition declaration refuses reopening COMPLETED, FAILED, CANCELLED and ARCHIVED into active states.

### production-writer-adoption | high | current callers still use the unconditional lifecycle writer

Type: integration scope. Status: open and explicitly queued. S09 honestly establishes only the repository primitive. Transitional and archive/deletion entry adoption remains assigned to S10, abandoned reconciliation to S11, terminal evidence and settlement to S78/S12/S13, and durable settlement retry to S14. ER02 remains open. S10 explicitly owns removal of the unconditional status setter after the final current caller migrates.

### postgresql-election-proof | medium | live PostgreSQL lock and row-count behavior remains unproved

Type: portability evidence. Status: open under the existing PostgreSQL server-profile evidence obligation. The statement is cross-dialect SQLAlchemy Core and uses the normal one-row update count. The focused proof is SQLite. No locked live PostgreSQL service was available, so PostgreSQL READ COMMITTED predicate recheck and affected-row behavior are not certified by this review.

### archive-deletion-adoption | high | teardown entry still needs the atomic primitive

Type: lifecycle integration. Status: open and queued in S10. Archive and DELETING entry can race a stale lifecycle writer. S10 now explicitly owns archive migration, atomic deletion-saga creation plus DELETING entry, and final unconditional-setter removal.

### current-only-semantics | low | no legacy or deprecated accommodation was added

Type: compatibility boundary. Status: verified. The implementation requires complete current authority and an already persisted matching receipt. It adds no default, nullable authority, inferred history, backfill, translation, alias, fallback, migration accommodation, deprecated provider behavior or legacy execution lane.

### focused-verification | low | bounded implementation checks completed without a hang

Type: verification. Status: verified. The focused election and transition suite completed 25 tests in 3.72 seconds. Ruff and Ty passed on the exact production and test surfaces. The reviewer identity-map discriminator reproduced the blocking stale state; the overlapping SQLite discriminator returned one WON and one LOST. No test process remained running and PID 58992 was not touched.

## Recommendations

Correct the winner path so every already identity-mapped ThreadModel in the supplied session reflects or is explicitly expired from the committed election state, and add a regression that loads the model before the update and checks status plus all four authority fields after election and after commit with expire_on_commit=False. Preserve the exact SQL predicate and typed dispositions.

Keep S09 open and formally FAIL implementation commit 8c37f800bdf9e8e0c47565a5f0360d573b421bef. Rereview the correction before lifecycle closure. Retain production adoption, archive/deletion adoption and live PostgreSQL proof under their recorded owners.
