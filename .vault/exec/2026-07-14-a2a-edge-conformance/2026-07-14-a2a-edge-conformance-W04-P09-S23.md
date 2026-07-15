---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S23'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Write live tests proving token isolation per role, absence from checkpoints and logs, and disposal at run end

## Scope

- `src/vaultspec_a2a/worker/tests/`
- `src/vaultspec_a2a/control/tests/`

## Description

Real, mock-free tests proving the ADR R7 guarantees for the actor-token
pipeline built in S22. Commit `1b7b2f9`.

Created: `src/vaultspec_a2a/worker/tests/test_token_store.py`,
`src/vaultspec_a2a/worker/tests/test_executor_token_lifecycle.py`,
`src/vaultspec_a2a/control/tests/test_thread_service_tokens.py`.

Modified: `src/vaultspec_a2a/control/tests/conftest.py`.

- `test_token_store` exercises the real `ActorTokenBundle` and `RunTokenStore`:
  per-role lookup returns only that role's token, `repr`/`str` redact every raw
  token, `model_dump` still carries them for transport, an empty or `None` bundle
  registers nothing, drop is idempotent, and two runs holding the same role key
  resolve to different tokens.
- `test_executor_token_lifecycle` drives a genuine ingest through a real
  `Executor`, a real `AsyncSqliteSaver`, a real `WorkerBridge` over an in-process
  ASGI gateway, and a real compiled one-node `StateGraph`. A probe node reads the
  worker-scoped store from inside the running graph, so the assertions observe
  what a worker actually sees: the owning role receives its own token during
  execution, an unheld role reads `None`, no token survives into the durable
  checkpoint, no token appears on any log record emitted during the dispatch, and
  the store holds nothing for the run once the dispatch completes.
- `test_thread_service_tokens` proves the gateway half: a real
  `create_and_dispatch_thread` threads the real tokens onto the dispatch payload
  a real ASGI worker captures, while the control journal rows for the thread
  contain no token string.

## Outcome

Complete. 16 new tests pass; the full worker, control, and ipc suites pass at 90
passed with no regressions. `ruff`, `ruff format --check`, and `ty` clean on all
new files.

## Notes

`test_thread_service_tokens` imports `control.thread_service`, which triggered a
latent `context -> thread -> graph -> nodes -> supervisor -> context` import
cycle whenever that module is the first vaultspec import in a fresh interpreter
(importing `graph` first resolves `context.token_budget` fully and avoids it).
The source-level fix for the cycle is graph-domain work outside this wave's scope
and would collide with the active parallel session, so the immediate mitigation
is a `graph` warm-up import in the control test package's `conftest`, and the
cycle is flagged as a successor finding.
