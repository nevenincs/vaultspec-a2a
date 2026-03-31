---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-6` `step-1`

Extracted FastAPI dependency injection providers into a dedicated module.

- Created: `src/vaultspec_a2a/api/dependencies.py`

## Description

Moved `get_aggregator`, `get_checkpointer`, `get_worker_client`,
`get_circuit_breaker`, `get_worker_spawner`, and `get_services` from
`endpoints.py` into `api/dependencies.py`. Re-exported `get_db` from
`database.session` for convenience so route modules have a single import
source for all DI providers.

## Tests

All 99 API tests pass. No behavioral changes.
