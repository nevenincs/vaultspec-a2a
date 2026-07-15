---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase1` `step2`

Extracted `LazyWorkerSpawner`, `WorkerWatchdog`, and all helper functions from `api/app.py` to `control/worker_management.py`. Introduced `WorkerState` dataclass.

- Created: `src/vaultspec_a2a/control/worker_management.py`
- Modified: `src/vaultspec_a2a/api/app.py`
- Modified: `src/vaultspec_a2a/api/endpoints.py`

## Description

Moved the following to `control/worker_management.py` (~450 lines):

- `LazyWorkerSpawner` class
- `WorkerWatchdog` class
- Helper functions: `_spawn_worker`, `_shutdown_worker_process`, `_tcp_port_ready`, `_check_worker_health`, `_runtime_dir`, `_worker_stderr_log_path`, `_read_log_tail`, `_build_worker_restart_detail`

Introduced `WorkerState` dataclass containing the 9 attributes the watchdog previously wrote directly to `app.state`: `worker_status`, `worker_restart_count`, `worker_last_restart_reason`, `worker_last_restart_detail`, `worker_last_restart_started_at`, `worker_last_restart_completed_at`, `worker_last_restart_succeeded`, `worker_last_restart_attempts`, `worker_stderr_log_path`.

The `WorkerWatchdog.__init__` now accepts `worker_state: WorkerState` and `app_state: Any` (for heartbeat reading). The lifespan in `app.py` creates a `WorkerState`, stores it on `app.state.worker_state`, and passes it to the watchdog.

Health endpoints (`/health` and `/api/health`) now read worker lifecycle metadata from `app.state.worker_state` instead of individual `app.state` attributes.

`app.py` reduced from 1507 to 880 lines. Removed unused `subprocess` import.

## Tests

All 10 `api/tests/test_app.py` tests pass (updated to use `WorkerState`). Full suite: 1026 passed. Core: 425 passed. Hygiene test updated to reference `control/worker_management.py` instead of `api/app.py`.
