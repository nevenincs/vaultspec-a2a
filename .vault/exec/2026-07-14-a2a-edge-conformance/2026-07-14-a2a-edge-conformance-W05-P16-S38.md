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

Doctor now detects a resident gateway serving an older route set than the installed source, without depending on a version string that editable installs do not bump per commit. Verified live against the actual stale `:8000` process. Promotion of `:8000` (restart) is coordinated with the concurrent `exec-s37` worker-wiring fix so the promoted resident carries both changes; see Notes.

## Notes

Restart-promotion of the `:8000` resident is sequenced after `exec-s37`'s worker->gateway wiring fix lands, per task instructions, so the promoted process carries the newest source from both steps. This record will be updated with promotion evidence once that coordination clears.
