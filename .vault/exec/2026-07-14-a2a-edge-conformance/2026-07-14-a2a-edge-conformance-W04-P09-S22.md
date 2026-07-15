---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S22'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Accept the per-role actor token bundle on run-start, hold each token in worker-scoped runtime state only (never checkpointed, never logged, redacted from any payload logging), inject per worker, drop at run end

## Scope

- `src/vaultspec_a2a/api/`
- `src/vaultspec_a2a/control/`
- `src/vaultspec_a2a/worker/`

## Description

Accept the engine-provisioned per-role actor token bundle on run-start and
thread each token to its owning worker without logging or persisting it, per
ADR R7. Commit `6c0b82b`.

Modified: `src/vaultspec_a2a/thread/__init__.py`,
`src/vaultspec_a2a/ipc/schemas.py`, `src/vaultspec_a2a/api/schemas/rest.py`,
`src/vaultspec_a2a/api/routes/threads.py`,
`src/vaultspec_a2a/control/thread_service.py`,
`src/vaultspec_a2a/worker/executor.py`, `pyproject.toml`.

Created: `src/vaultspec_a2a/thread/actor_tokens.py`,
`src/vaultspec_a2a/worker/token_store.py`.

- Add `ActorTokenBundle`, the shared wire model carrying per-role tokens keyed by
  role identifier plus the optional engine machine bearer. Its `repr`/`str`
  redact every raw token so the bundle is safe to interpolate into any log line,
  while `model_dump`/`model_dump_json` still emit the real values for the
  gateway-to-worker loopback transport. Token count and byte size are bounded so
  the forwarded payload stays safe to wrap in the engine pass-through envelope.
- Thread the bundle through the run-start intake path: `CreateThreadRequest`
  accepts it, `ThreadCreationRequest` carries it, and `create_and_dispatch_thread`
  places it on the `DispatchRequest` only. It is never written to the control
  journal payload or the thread metadata.
- Add `RunTokenStore`, a worker-scoped per-thread holder. The `Executor`
  registers a run's bundle when its active window opens (ingest and resume) and
  drops it when the window closes (`_mark_ingest_done`, and on cancel), so tokens
  never outlive the worker turn that used them and are never checkpointed. Reads
  are scoped to a single role, so a worker only ever obtains its own token.
- Configure ruff `flake8-type-checking` with pydantic `BaseModel` as a
  runtime-evaluated base class so field-type imports (needed at pydantic
  class-build time) stay at module scope rather than a type-checking block.

## Outcome

Complete. `ruff` and `ty` clean on all touched files. A standalone probe
confirmed redaction (raw tokens absent from `repr` of both the bundle and the
whole `DispatchRequest`), transport (real tokens present in `model_dump_json`),
per-role isolation, and the register/read/drop store lifecycle. The full worker,
control, and ipc suites pass (90 passed, no regressions). Live isolation tests
land in S23.

## Notes

Scope was held to `api/`, `control/`, and `worker/` as the plan lists; the
per-role token is exposed to the worker process through `RunTokenStore` (the
injection seam the per-run authoring binding consumes), and the graph-node
consumption of that token — assembling the authoring binding with the catalog
snapshot and run id — remains the deferred W03.P07.S18 binding-assembly work.

The stdio authoring bridge merged into main mid-step (`89a0c53`), and a parallel
session was actively committing to `graph/nodes/`; the chosen scope avoided any
edit to `graph/nodes/worker.py`, so there was no collision.
