---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S01'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Boot gateway and worker together and prove live IPC dispatch (worker_connected true, a message round-trips), fixing whatever blocks it

## Scope

- `src/vaultspec_a2a/control/worker_management.py`
- `src/vaultspec_a2a/worker/app.py`
- `src/vaultspec_a2a/api/app.py`

## Description

- Rag-first then read the integrated-layer wiring whole: the gateway lifespan builds a `LazyWorkerSpawner` (`auto_spawn_worker` defaults true) and launches a startup reconcile task that calls `ensure_worker()`, which spawns the worker as a plain subprocess (`python -c "from vaultspec_a2a.worker.app import main; main()"`) and polls its `/health`. The worker's heartbeat loop POSTs to the gateway `/internal/heartbeat`, setting `worker_last_heartbeat_ts`; the gateway health check derives `worker_connected` from heartbeat freshness against `worker_heartbeat_timeout_seconds`.
- Author a live boot probe that starts the gateway as a real uvicorn subprocess on 127.0.0.1:8000 (sqlite, dev-mode IPC auth off, worker on :8001), polls the gateway `/health` until the worker is both spawned and connected, and directly probes the worker `/health`. Teardown terminates the gateway and reaps the worker tree by its reported PID so nothing is orphaned.
- Run the probe twice; confirm exit 0 and no residual listeners on 8000/8001.

## Outcome

IPC dispatch is proven live — no code fix was required; the gateway booted alone DOES auto-spawn and connect the worker. Captured evidence from the probe: gateway `/health` reports `worker_spawned: true`, `worker_connected: true`, `worker_pid` set, sqlite fallback active (`postgres_required: false`); the worker `/health` returns `{status: ok, service: worker, database_backend: sqlite}`. Both IPC directions are exercised: gateway->worker (spawn + `/health` reachability + `/dispatch` target) and worker->gateway (heartbeat round-trip delivered to `/internal/heartbeat`, which is exactly what flips `worker_connected` true). The probe exits 0 on two consecutive runs and leaves no orphaned worker or port listener.

Salvage verdict for the integrated IPC layer: CONFIRMED healthy. The research document's earlier `worker_connected/worker_spawned false` observation reflected a gateway started without its lifespan reconcile task completing (or checked before the ~10s heartbeat interval), not a broken IPC path.

## Notes

Proven vs presumed: PROVEN live — worker subprocess spawn, worker->gateway heartbeat, `worker_connected` computation, and headless sqlite boot. PRESUMED still (deferred to S02): that a full agent turn executes end-to-end through the dispatch — S01 proves the dispatch plumbing and the fire-and-forget `/dispatch` contract, not graph completion (which needs the VidaiMock tape server on :8100). The probe is a standalone verification script (kept in the session scratchpad, method fully recorded here for reproducibility) rather than a committed integration test, per the mandate's preference for probe scripts over brittle live-service tests for one-off gate verification. This step made no source changes, so it has no code commit; the step record commit is deferred to the post-release vault batch.
