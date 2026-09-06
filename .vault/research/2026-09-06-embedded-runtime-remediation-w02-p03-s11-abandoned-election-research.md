---
tags:
  - '#research'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:bc994fc0e2416959d99202096569380e58f4e5ada35a4adc6abc6417c02495f9'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-06-embedded-runtime-remediation-w02-p03-s11-abandoned-election-audit]]"
---
# S11 abandoned reconciliation election integration

## Result

The hang trace and the older served-capability plan separate two concerns. `W04.P08.S56` remains the owner of checkpoint-aware abandonment: the current reader backstop waits at least 300 seconds and must distinguish a graph that already reached its end from one that truly stalled. `W02.P03.S11` integrates the durable election into the writers already present without reassigning that semantic decision.

Three `reconciling` failure writers were stale-write capable: incompatible frozen authority and missing project refusal in startup redispatch, and elapsed-bound abandonment in run discovery. Each now snapshots the row's exact status, revision, writer generation, action type and receipt, retains that same durable action identity, advances one run revision, and commits only `WON`. `LOST`, `NOT_FOUND`, and `RECEIPT_MISMATCH` cannot invent an authority or apply a failure.

The focused tests now create matching control-action journal receipts. A two-session SQLite case holds a stale abandoned observation while a newer session commits `completed`; the abandonment election loses and the completed result survives.

## Verification

The selected 14-case gate emitted `14 passed in 25.05s`; Ruff and Ty pass. Pytest then failed to exit naturally, so session `74355` was interrupted and no matching test process survived. This is retained as open resource-aware test lifecycle evidence. The production 90-second restart hang remains HIGH/open under S56 because S11 neither shortens the declared run budget nor adds checkpoint interpretation.
## Findings

S11 can close only the atomic-writer integration after formal review. S56 remains the semantic owner of checkpoint inspection and the recovery deadline. The test process exit failure is independent infrastructure work and remains open.

## Sources

- `src/vaultspec_a2a/control/dispatch.py`
- `src/vaultspec_a2a/control/run_discovery_service.py`
- `src/vaultspec_a2a/control/tests/test_reconciling_abandonment.py`
- `src/vaultspec_a2a/control/tests/test_redispatch_failure_ladder.py`
- `.vault/plan/2026-08-05-served-capability-contract-plan.md`
- `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
