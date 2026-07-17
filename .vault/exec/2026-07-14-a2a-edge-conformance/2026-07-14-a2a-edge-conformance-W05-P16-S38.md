---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S38'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Promote the current build to the machine-global :8000 discovery point (restart the resident gateway so its OpenAPI serves the run-stream route) and add a doctor staleness check that detects a resident serving an older route set than the installed source, so a stale resident is diagnosable instead of silently 404ing the engine relay

## Scope

- `src/vaultspec_a2a/lifecycle/`
- `src/vaultspec_a2a/cli/`
- `src/vaultspec_a2a/api/`

## Description

- Add `route_signature(app)` in `api/routes/gateway.py`, deriving a sorted `"METHOD path"` list from `app.openapi()["paths"]` rather than walking `app.routes` directly, since the installed FastAPI version defers route resolution behind an internal `_IncludedRouter` wrapper that `app.routes` does not flatten.
- Add a `routes: list[str]` field to `ServiceStateResponse` and populate it in the `/v1/service` endpoint with `route_signature(request.app)`.
- Extend the `doctor` CLI command (`cli/main.py`) to fetch `/v1/service`, build the expected signature from a locally-constructed `create_app()` (no lifespan I/O), and diff it against the live `routes` field. Adds `stale_resident`/`missing_routes` to the reported JSON body. A resident predating the `routes` field entirely (no key in the response) is reported unconditionally stale, since that predates this diagnostic itself - exactly the pid 45724 case at `:8000`.
- Add a live test (`test_doctor_flags_a_resident_missing_a_route`) that removes the run-stream route from the real, shared `gateway_router` singleton for the duration of a real uvicorn server, runs the doctor CLI as a real subprocess against it, and asserts the diff catches it; restores the route in a `finally` to avoid leaking the mutation into later tests sharing the same process.
- Ran doctor against the live `:8000` resident (pid 45724) and confirmed it reports `stale_resident: true` with the full expected route list under `missing_routes`, since that process predates the `routes` field.

## Outcome

Doctor now detects a resident gateway serving an older route set than the installed source, without depending on a version string that editable installs do not bump per commit. Verified live against the actual stale `:8000` process. Promotion of `:8000` (restart) was sequenced after `exec-s37`'s worker->gateway wiring fix landed (`ee2cdc5`), and is now complete.

Promotion steps performed, in order:

- Confirmed `main` at `ee2cdc5` (exec-s37's fix) locally before restarting anything.
- Backed up the shared sqlite database (`vaultspec.db`, `-wal`, `-shm`) to sibling `*.bak-2026-07-17-pre-epoch-repair` files before any write, per team-lead's precondition.
- Applied a scoped, two-row DB repair: `UPDATE threads SET recovery_epoch = 1 WHERE id IN ('pw7-1784286176', 'pw7-1784286557') AND recovery_epoch = 0`. Justification: both threads already carried an applied `repair_started:1` control action (idempotency key `startup-repair:{thread_id}:1`) from an earlier successful reconciliation pass, but `recovery_epoch` was never actually incremented to match, so every subsequent boot re-derived the same idempotency key and crashed on the `control_actions` UNIQUE constraint. Setting `recovery_epoch = 1` brings the row in line with the control action already recorded for it - no other columns or threads touched. The underlying code defect (the `paused_resumable` reconciliation outcome not setting `increment_recovery_epoch`) is out of this step's scope; team-lead has folded it into the plan as `W05.P16.S40` for `exec-s37`.
- Gracefully stopped the stale resident (`POST /api/admin/shutdown` against pid 45724), confirmed the process exited and the port was free.
- Booted a fresh resident (`vaultspec-a2a serve`) on `:8000` from current `main`; it came up clean (no repeat of the `IntegrityError`).
- The pre-existing worker process on `:8001` (pid 35724) was itself stale (its `/health` response lacked the `gateway_url` provenance field `ee2cdc5` added, since it predated that change) and the new gateway had adopted it as externally-managed rather than evicting it (no gateway/worker URL mismatch to trigger eviction - it really was this resident's own worker, just old code). Stopped it via its own `POST /admin/shutdown` and started a fresh `python -m vaultspec_a2a.worker` on `:8001` to complete the promotion end to end.
- Ran a real smoke dispatch (`run start` with the `mock-success-single` preset) through the promoted gateway to prove the gateway->worker HTTP dispatch path; the run reached the worker and executed (it failed inside graph execution with an unrelated `httpcore.ConnectError`, consistent with a missing companion mock-model service in this ad hoc environment rather than any wiring regression - `worker_ready`/`can_accept_run` on `/v1/service` were `true` throughout).

## Notes

Promotion evidence:

- `GET :8000/health` → `200`, `{"status":"ok","service":"gateway","pid":45112,...}`.
- `GET :8000/openapi.json` → `"paths"` includes `/v1/runs/{run_id}/stream`.
- `~/.vaultspec-a2a/service.json` → `{"port": 8000, "pid": 45112, "last_heartbeat": <fresh>}` (new pid, matches the current resident; the old pid 45724 record is gone).
- `doctor --url http://127.0.0.1:8000` → `"stale_resident": false`, `"missing_routes": []`, full `"routes"` list present.
- `GET :8001/health` (fresh worker) → `{"status":"ok","service":"worker","gateway_url":"http://127.0.0.1:8000",...}` - the live gateway URL provenance field from `ee2cdc5`.

One residual observation, not a regression: the top-level `/health` endpoint's `worker_status` field stayed `"down"` even after the fresh worker connected and successfully executed a dispatch, while `worker_connected` was `true` and `/v1/service`'s `worker_ready`/`can_accept_run` were `true` throughout. This looks like the watchdog's `WorkerState` string not being reconciled for an externally-adopted (not gateway-spawned) worker, distinct from the heartbeat-driven `worker_connected` and probe-backed `/v1/service` readiness fields. Flagging for awareness, not filing as a new bug against this step's scope.

DB backups (untracked, left on disk, not committed): `vaultspec.db.bak-2026-07-17-pre-epoch-repair`, `vaultspec.db-wal.bak-2026-07-17-pre-epoch-repair`, `vaultspec.db-shm.bak-2026-07-17-pre-epoch-repair` in the repo root.

## Revision (code review REVISION REQUIRED, doctor-exit-code-silent finding)

Code review of `e47c882` (`.vault/audit/2026-07-17-a2a-edge-conformance-audit.md`) required a distinct non-zero `doctor` exit code for a detected stale resident, since automation keying on exit status would otherwise miss what only JSON-parsing consumers could see. Added `_EXIT_STALE_RESIDENT = 3` in `cli/main.py`: exit `0` healthy, `1` unreachable/HTTP error (unchanged), `3` reachable but stale. Updated `test_doctor_flags_a_resident_missing_a_route` to assert `returncode == 3` instead of `0`. Ruff, ty, and the live CLI suite (3/3) pass.

Also re-did the `:8000` restart-promotion cleanly against the current tree (now including `exec-s37`'s `W05.P16.S40` fix, `7e308cf`, which landed after the original promotion committed pid 45112 into memory - a running process does not pick up a file-level fix without a restart, so a fresh boot was needed to actually exercise S40 rather than just carry it on disk):

- Gracefully stopped both the previous gateway (pid 45112) and its adopted legacy worker (pid 52168) via their `/admin/shutdown` endpoints, closing the `legacy-worker-adoption-compat-hole` finding's operational half - no no-provenance worker survives the promotion.
- Booted a fresh gateway (`vaultspec-a2a serve`, new pid 3264); this time, with no pre-existing worker to adopt, it spawned its own worker (pid 92376, gateway-owned rather than externally-adopted) and reached `worker_status: "up"` cleanly - the earlier "stuck on down" cosmetic observation does not reproduce for a gateway-owned worker.
- Confirmed provenance end to end: `GET :8001/health` → `{"status":"ok","service":"worker","gateway_url":"http://127.0.0.1:8000",...}`.
- Re-ran the full evidence bundle against the new pids: `GET :8000/health` → `200`; `GET :8000/openapi.json` paths include `/v1/runs/{run_id}/stream`; `~/.vaultspec-a2a/service.json` → fresh pid 3264; `doctor --url http://127.0.0.1:8000` → `stale_resident: false`, `missing_routes: []`, exit code `0`.
- The two-row `recovery_epoch` repair from the first promotion attempt remains in place (belt-and-braces, per team-lead); this boot did not need to re-derive those idempotency keys since the affected threads already carry the corrected epoch, and S40 additionally makes the boot tolerant of either state going forward.
