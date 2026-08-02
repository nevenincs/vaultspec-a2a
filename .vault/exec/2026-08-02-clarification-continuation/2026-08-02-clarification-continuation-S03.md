---
tags:
  - '#exec'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:24b6f8686215bde210caf5839e23f83007aa93bb58b009437aed0cecba748a92'
step_id: 'S03'
related:
  - "[[2026-08-02-clarification-continuation-plan]]"
---

# Prove contract boundaries and the real worker continuation loop

## Scope

- `src/vaultspec_a2a/thread/tests/test_clarification.py`
- `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`

## Description

- Prove discriminator, request identity, exact-one-of shape, blank rejection, and bounds.
- Exercise prompt continuation through the real gateway, worker, executor, graph, and SQLite checkpoint.
- Run the focused clarification suite, lint, formatting, strict typing, and formal review.

## Outcome

All 123 focused tests pass. The live test proves the parked state remains
unchanged until prompt submission and then durably contains exactly one new
human turn with no fabricated clarification answer. Focused Ruff and targeted
BasedPyright checks pass.

## Notes

The test run reports one upstream `importlib.metadata` deprecation warning. The
repository-wide strict typing gate remains red in unrelated concurrent work;
the four changed gateway and live-test files checked directly report zero
errors.
