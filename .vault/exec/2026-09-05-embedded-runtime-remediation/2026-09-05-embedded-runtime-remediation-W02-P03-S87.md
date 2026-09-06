---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:07e2883641d2e34c2ba7fee6cfd6b612a039e65edab3f4b591188480dbada2aa'
step_id: 'S87'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Persist exact active-action completion through one graph finalizer on every served topology END route, so recovery reads durable completion without provider compilation or pending-write heuristics

## Scope

- `src/vaultspec_a2a/graph`
- `src/vaultspec_a2a/thread`
- `src/vaultspec_a2a/worker/executor.py`

## Changes

- `M` `src/vaultspec_a2a/graph/compiler.py`
- `A` `src/vaultspec_a2a/graph/nodes/action_completion.py`
- `A` `src/vaultspec_a2a/graph/tests/nodes/test_action_completion.py`
- `M` `src/vaultspec_a2a/graph/tests/test_compiler.py`
- `M` `src/vaultspec_a2a/thread/action_receipts.py`
- `M` `src/vaultspec_a2a/thread/state.py`
- `M` `src/vaultspec_a2a/worker/executor.py`
- `M` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `verify:` `bounded runner: interruption/reopen, topology routes and worker active-action input` -> `pass`