---
tags:
  - '#research'
  - '#mantest-probe'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:30026f2f01bdf22a5f30bb6b54d645c15e3fe75a16890b9a9eecb55ab5a1cfdd'
related: []
---

# `mantest-probe` research: gateway `/health` restart count

Should the a2a gateway `/health` expose `worker_restart_count`? The evidence says no: keep `/health` liveness-only, and leave restart count in the richer health aggregate or operator-facing surfaces.

## Findings

### Keep anonymous `/health` minimal.
The armed gateway route returns `LivenessResponse` only, and that schema is limited to the liveness fact (`src/vaultspec_a2a/api/app.py:713`, `src/vaultspec_a2a/api/schemas/gateway.py:1022`). `worker_restart_count` already appears in the broader health assembly with restart reason/detail fields (`src/vaultspec_a2a/control/health.py:357`, `src/vaultspec_a2a/control/health.py:412`).

### Two options, one kept.
Option A: expose `worker_restart_count` on public `/health`. Rejected because it expands the anonymous contract beyond liveness and duplicates operator telemetry already available elsewhere (`src/vaultspec_a2a/api/app.py:713`).

Option B: keep `/health` minimal and preserve restart count in richer health data. Kept because service-state/readiness already carries richer gateway facts, and the ops docs frame `/health` as a public supervisor check (`src/vaultspec_a2a/api/schemas/gateway.py:962`, `src/vaultspec_a2a/api/schemas/gateway.py:979`, `docs/operations.rst:76`).

## Open Gap

No retrieved consumer currently depends on `worker_restart_count` on anonymous `/health`.

## Sources

src/vaultspec_a2a/api/app.py:713
src/vaultspec_a2a/api/schemas/gateway.py:962
src/vaultspec_a2a/api/schemas/gateway.py:979
src/vaultspec_a2a/api/schemas/gateway.py:1022
src/vaultspec_a2a/control/health.py:357
src/vaultspec_a2a/control/health.py:412
docs/operations.rst:76
