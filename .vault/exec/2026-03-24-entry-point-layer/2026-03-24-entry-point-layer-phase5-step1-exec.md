---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase5` `step1`

Created `control/health.py` with consolidated health assembly logic.

- Created: `src/vaultspec_a2a/control/health.py`
- Modified: `src/vaultspec_a2a/api/app.py` (removed `_build_sqlite_fallback_diagnostics`, removed `inspect_sqlite_database` import)
- Modified: `src/vaultspec_a2a/api/tests/test_app.py` (updated import path)

## Description

Moved `_build_sqlite_fallback_diagnostics` from `api/app.py` to `control/health.py` as `build_sqlite_fallback_diagnostics` (public, no leading underscore). Created `assemble_health_status(app_state=...)` which extracts all shared health data from `app.state`: circuit breaker state, spawner state (spawned, process PID), worker heartbeat connectivity, full `WorkerState` restart metadata (9 fields), repair summary, and SQLite fallback diagnostics. Returns a flat dict suitable for merging into either endpoint's response.

## Tests

All 10 `test_app.py` tests pass. 425 core tests pass. 1026 full suite tests pass (1 pre-existing unrelated failure in `test_factory.py` due to missing npm dependency).
