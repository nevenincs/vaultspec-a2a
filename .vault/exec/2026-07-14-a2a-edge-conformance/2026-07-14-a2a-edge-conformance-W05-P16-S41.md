---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S41'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Close the two non-blocking re-review follow-ups: reconcile watchdog worker state for adopted (externally-managed) workers so plain health readiness stops reporting a healthy adopted worker as down (relax the spawned gate to reach the non-owned reconciliation branch, or set the status from the adoption probe), and harden get_or_create_control_action to an atomic on-conflict-do-nothing insert so the helper name matches its guarantee under concurrent boots. Prove with live tests covering an adopted worker reaching status up and readiness true

## Scope

- `src/vaultspec_a2a/control/worker_management.py`
- `src/vaultspec_a2a/api/app.py`
- `src/vaultspec_a2a/database/permission_repository.py`

## Description

Two non-blocking follow-ups from the re-review.

Watchdog reconciliation for adopted workers. The watchdog holds no process handle
for a worker it did not spawn - same-gateway adoption returns no handle, and an
externally-managed worker is owned by the dev-process registry - so there is no
restart path that could ever flip a latched "down" back to "up". The owned-worker
state machine keeps a "down" worker down until a real restart recovers it, which is
correct for a worker the gateway can restart but freezes a healthy adopted worker
at "down"/"pending" and makes plain health readiness lie. Added a branch at the top
of the watchdog tick: when the spawner holds no process, reconcile `worker_status`
purely from the live HTTP probe every tick (`up` when reachable, `down` otherwise)
and return, bypassing the owned-worker sticky-down guard. Restart and breaker paths
are untouched - an adopted worker is still never restarted or breaker-forced.

Health readiness for externally-managed workers. The top-level health readiness
gate failed a spawned worker whenever its pushed heartbeat was not fresh
(`worker_spawned and not worker_connected`). For an adopted / externally-managed
worker (spawned, no owned pid) the heartbeat push may legitimately not reach this
gateway, so its liveness is the probe-driven `worker_status`, not the heartbeat
freshness. Scoped the heartbeat-freshness term to owned workers only
(`worker_spawned and worker_pid is not None`), so a healthy adopted worker reports
ready.

Atomic control-action get-or-create. Hardened the helper from lookup-then-insert to
an atomic insert: the insert runs inside a `begin_nested` savepoint, and an
`IntegrityError` from a concurrent boot winning the UNIQUE key rolls back only the
savepoint (the outer transaction stays usable) and is resolved by re-reading the
committed row. The helper name now matches its guarantee.

## Outcome

Live tests, no mocks:

- Watchdog: an adopted worker (spawner with no owned process, real loopback
  `/health` server) latched at "down" reconciles back to "up" on the next tick,
  while restart count stays zero and the breaker stays closed. Pre-fix the healthy
  branch's down-stays-down guard froze it at "down".
- Readiness: the real gateway app served over ASGI, with the adoption-shaped spawner
  (spawned, `worker_pid` None) and no heartbeat timestamp, reports `/health`
  `ready=true` with `worker_connected=false`. Pre-fix the heartbeat-freshness term
  flipped it to not-ready.
- Atomicity: two separate sessions requesting the same idempotency key yield exactly
  one journal row; the second call returns the committed row with `created=false`,
  no duplicate and no crash.

Validation: `ruff` and `ty` clean on touched modules; `205 passed` across the api,
control, and database suites (the three new tests plus the full existing watchdog,
reconciliation, and health coverage).

## Notes

The existing watchdog tests already proved a healthy adopted worker reaches "up"
from a clean start; the gap this closes is the latched-down recovery, since a
non-owned worker has no restart path to unfreeze it. The two behaviours now share
one probe-driven reconciliation branch.

The savepoint covers the realistic concurrent-boot case where the conflicting row is
already committed by a prior or racing boot. A truly simultaneous cross-connection
insert of an uncommitted row is serialized by the database's write lock; the loser
observes the committed row on its savepoint re-read. `create_control_action` keeps
its plain insert-or-raise contract, so a genuine duplicate outside this replay path
still surfaces rather than being silently swallowed.
