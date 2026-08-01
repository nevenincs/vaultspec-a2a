---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:cf65e3114a86625382428aa225e192878349a5bdbfe2f3cd5d9f2e0a994f614c'
step_id: 'S23'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Repair the API live-gateway and clarification test partitions without overlapping peer work.

## Scope

- `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `src/vaultspec_a2a/api/tests/test_clarification_endpoint.py`
- `src/vaultspec_a2a/api/tests/test_acceptance_five_verb.py`
- `src/vaultspec_a2a/api/tests/clarification_harness.py`
- `src/vaultspec_a2a/control/tests/test_verdict_loop_live.py`
- `src/vaultspec_a2a/worker/executor.py`
- `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `src/vaultspec_a2a/worker/tests/test_executor.py`
- `src/vaultspec_a2a/worker/tests/test_executor_token_lifecycle.py`

## Description

- Typed live gateway fixtures, JSON protocol helpers, server lifespans, and runtime pool boundaries while retaining real TCP and SSE behavior.
- Extracted the shared real clarification graph harness and migrated clarification, acceptance, verdict, executor, and token-lifecycle tests away from private lifecycle-cache mutation.
- Added the public atomic compiled-graph registration seam, then strengthened its structural contract to require stream, checkpoint, and invocation behavior.
- Centralized the dynamic LangGraph state-graph construction boundary in the shared harness and retained real compiled graphs in each test.
- Completed an independent corrective review and recorded the resolved medium and low findings in the audit log.

## Outcome

Focused Basedpyright over the live gateway, shared harness, and clarification partitions reported 0 errors, 0 warnings, and 0 notes. Ty, Ruff check, and Ruff format checks passed across all ten scoped paths. The real S23 selection passed 90 tests; one configured service test was deselected. The independent re-review found no new S23 issue and confirmed no external private cache access, no unsafe concrete graph-protocol casts, and no prohibited test shortcut.

## Notes

The all-ten-path Basedpyright invocation still reports 109 pre-existing executor and test-fixture diagnostics outside the focused S23 strict lane; it is explicitly not a clean broader-type claim. The test run emitted one existing Python 3.13 `importlib.metadata` deprecation warning. The audit queue records no new S23 follow-up, while the residual broader typing debt remains scheduled under the plan's production-domain and final graduation steps.
