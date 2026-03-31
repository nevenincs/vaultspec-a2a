---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase1` `step3`

Rewired all imports and verified test baseline.

- Modified: `src/vaultspec_a2a/api/app.py`
- Modified: `src/vaultspec_a2a/api/endpoints.py`
- Modified: `src/vaultspec_a2a/api/tests/test_app.py`
- Modified: `src/vaultspec_a2a/api/tests/conftest.py`
- Modified: `src/vaultspec_a2a/protocols/mcp/tests/test_server.py`
- Modified: `src/vaultspec_a2a/tests/test_repo_hygiene.py`
- Modified: `src/vaultspec_a2a/control/__init__.py`

## Description

Updated all consumer imports:

- `api/app.py`: imports `WorkerCircuitBreaker` from `control.circuit_breaker`, `LazyWorkerSpawner`/`WorkerState`/`WorkerWatchdog` from `control.worker_management`
- `api/tests/test_app.py`: imports from new locations, adds `WorkerState` import, updates watchdog test to pass `worker_state` parameter and health test to construct `WorkerState` dataclass
- `api/tests/conftest.py`: imports from new locations
- `protocols/mcp/tests/test_server.py`: imports from new locations
- `api/endpoints.py`: updated `/api/health` to read `worker_last_restart_detail` and `worker_stderr_log_path` from `app.state.worker_state`
- `tests/test_repo_hygiene.py`: updated runtime path check from `api/app.py` to `control/worker_management.py`
- `control/__init__.py`: updated docstring and `__all__` to reflect new modules

No backwards-compat re-export shims. Old import paths break loudly.

## Tests

- `pytest -m core`: 425 passed (Layer 1 isolation preserved)
- Full suite: 1026 passed, 39 deselected (standard exclusions)
- Pre-existing `test_factory.py` failure excluded (npm dependency, unrelated)
