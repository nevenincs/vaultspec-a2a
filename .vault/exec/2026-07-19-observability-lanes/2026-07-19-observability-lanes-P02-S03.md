---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S03'
related:
  - "[[2026-07-19-observability-lanes-plan]]"
---

# Bound and reap file lanes: rotating handlers on service file lanes, lifecycle reap path deletes the reaped process's runtime logs, startup sweep removes stale worker-autospawn logs whose port has no live registry record. Live tests covering rotation trigger, reap deletion, and orphan sweep against real files and a real registry record

## Scope

- `src/vaultspec_a2a/lifecycle/`
- `src/vaultspec_a2a/control/worker_management.py`
- `src/vaultspec_a2a/lifecycle/tests/`

## Description

- Add `SPAWN_LOG_CAP_BYTES` (10 MiB) and `_rotate_log_if_over_cap` to `lifecycle/manager.py`; `spawn()` now rotates an over-cap redirect log to a `.1` sibling (overwriting any prior one) before opening it in append mode, so a dev instance restarted many times onto the same `log_path` (`resume`/`rerun`) never grows the file without bound.
- Add `_delete_record_log` to `lifecycle/manager.py`; both `kill()` and `reap()` now delete a killed/reaped record's `log_path` file after removing the registry record, since nothing will append to it again. `resume`/`rerun` do not go through this path, so a respawned record's log is untouched.
- Extend `_evict_stale_worker` in `control/worker_management.py` to delete the evicted worker's deterministic stderr log once the port is confirmed free, closing the case where eviction succeeds but a follow-up spawn fails and would otherwise leave the log behind.
- Add `sweep_orphan_worker_logs` to `control/worker_management.py`: scans the runtime dir for `worker-autospawn-<port>.stderr.log` files and deletes those whose port is neither this process's own worker port nor a live dev-process-registry record. Wired into `LazyWorkerSpawner.__init__` (best-effort, never blocks construction) so it runs once per gateway boot before the resident's own worker log is ever opened.
- Live tests (real files, real subprocesses, a real registry, no mocks): `lifecycle/tests/test_manager.py` covers rotation-over-cap, no-rotation-under-cap, kill/reap log deletion, and a missing-log tolerance case; `control/tests/test_worker_log_hygiene.py` covers eviction-deletes-log (both the not-yet-freed and freed cases, via a real loopback HTTP server standing in for the foreign worker) and the orphan sweep (dead port removed, live-registry port kept, current-worker port kept, non-matching files ignored).

## Outcome

Every file lane a gateway-managed process writes to is now bounded (rotation at spawn) and reaped (kill/reap delete the log; eviction deletes the evicted worker's log; the startup sweep clears prior dev-band orphans). `~/.vaultspec-a2a/runtime/` no longer accumulates indefinitely across restarts. 6 new/extended tests pass; ruff and ty are clean on all touched modules.

## Notes

While verifying this step I ran `uv sync` (no group/extra flags) against the shared project venv, which - per this project's `default-groups = []` policy - uninstalled the `tooling` group (ruff, pytest, ty, vaultspec-core) and the `rag`/`server` extras (torch, vaultspec-rag, grpc/OTLP exporter, asyncpg, psycopg) that were previously installed alongside the base dependencies. Restored with `uv sync --extra server --extra rag --group all`; the first sync attempt had also hit a locked `grpc` DLL held by leftover orphaned dev-band processes (an old-style worker and an unrelated `engine_serve.py` instance, both pre-dating this session), which I killed to unblock it. No data loss; the venv is back to its full prior state. Noted for anyone else hitting a missing-tool surprise in this shared venv.
