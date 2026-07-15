---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S03'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# Deepen service-state: truthful ready/degraded/unavailable status, service and API versions, gateway pid, provider and engine-authoring-backend reachability, active-run capacity, discovery freshness, and the alive versus can-accept-run versus preset-eligible distinction

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/control/health.py`

## Description

- Replaced the hardcoded service-state status with a probe-derived one: the
  endpoint now runs the real dependency probes through build_full_health
  (database, checkpoint, worker) instead of the no-probe assembler, and maps the
  result to ready, degraded, or unavailable (unavailable when the database probe
  fails, degraded when a dependency is unready, ready otherwise).
- Deepened the service-state schema: service_version, gateway_pid,
  active_run_capacity, the alive-versus-can-accept-run distinction, per-probe
  database_ready / checkpoint_ready / worker_ready, degraded_reasons, and the
  authoring-backend reachability tri-state.
- Added a non-blocking engine-discovery freshness probe to the health module: it
  classifies the service.json candidates by heartbeat only, never a live health
  call, so the readiness path does not block, and returns True fresh / False
  stale-or-malformed / None not-configured.
- Derived degraded_reasons from genuine failure statuses only, excluding
  informational checks such as worker_spawned and the stderr-log marker.
- Sourced service_version from the installed distribution metadata and
  active_run_capacity from the configured max-concurrent-threads cap.
- Updated the five-verbs live assertion to the probe-derived ready status and
  added a service-state depth test asserting versions, identity, capacity, the
  alive-versus-can-accept-run fields, per-probe readiness, empty degraded reasons
  in a healthy app, and the reachability tri-state.

## Outcome

- service-state no longer claims a hardcoded ok: it reflects real database,
  checkpoint, and worker probes, distinguishes a live process from one that can
  accept a run, and reports versions, pid, capacity, and non-blocking engine
  discovery freshness.
- Scoped suites green: api and control (257); `ruff check`, `ruff format`, and
  `ty check` clean on the changed modules.

## Notes

- Engine authoring-backend reachability is intentionally discovery-freshness
  based rather than a live HTTP probe: resolve_engine performs a blocking
  synchronous health call unsuitable for the async readiness path, so this Step
  reports heartbeat freshness (which also satisfies the handover's
  discovery/heartbeat-freshness field) and leaves a live authoring probe to the
  evidence battery.
- The alive-versus-can-accept-run-versus-preset-eligible triad is split across
  surfaces: service-state carries alive and can_accept_run; preset eligibility is
  the per-preset loadable flag from presets-list and the run-start eligibility
  check, not a service-level field.
