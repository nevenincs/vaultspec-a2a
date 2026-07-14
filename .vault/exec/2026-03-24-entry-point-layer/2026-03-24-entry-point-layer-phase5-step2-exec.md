---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase5` `step2`

Wired both health routes to use `assemble_health_status()`.

- Modified: `src/vaultspec_a2a/api/app.py` (`health_endpoint` now delegates to `assemble_health_status`, adds only `status`, `service`, `ready`, `production_certifying`)
- Modified: `src/vaultspec_a2a/api/endpoints.py` (`health` now delegates to `assemble_health_status`, adds only `checks` dict and readiness probes)

## Description

Refactored `app.py:health_endpoint()` from ~100 lines to ~20 lines. It calls `assemble_health_status()` for the shared payload, computes its `ready` flag from the shared fields, and adds liveness-specific fields (`status: ok`, `service: gateway`, `production_certifying`).

Refactored `endpoints.py:health()` from ~95 lines to ~50 lines. The detailed per-subsystem probes (DB query, checkpoint presence, worker HTTP ping) remain route-specific since they require injected dependencies. The shared metadata (restart info, repair summary, backend config, sqlite fallback) comes from `assemble_health_status()` via dict spread.

Also simplified the checkpointer presence check in `endpoints.py` -- the previous code had an unnecessary double-`getattr` pattern.

## Tests

All 10 `test_app.py` tests pass. 425 core tests pass. 1026 full suite tests pass.
