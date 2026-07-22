---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S43'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Enforce the worker IPC credential on dispatch events heartbeats health and administration

## Scope

- `src/vaultspec_a2a/worker/app.py`

## Description

- Require the worker interprocess-communication credential on the worker's
  `/health` endpoint, matching the existing dispatch and administrative-shutdown
  gates, so the whole worker surface is private to the gateway-worker pair.
- Authenticate the gateway's own health probes with the shared worker IPC bearer
  so a worker that now enforces the credential on `/health` still answers its
  paired gateway: add a single `_internal_auth_headers` authority and present it
  on the watchdog/boot health probe and the provenance fetch, and reconcile the
  eviction path onto the same authority.
- Certify the `/health` gate over real HTTP: reject a missing or wrong bearer,
  accept the paired bearer, and leave a DEVELOPMENT worker with no token open.

## Outcome

- Modified: `src/vaultspec_a2a/worker/app.py`,
  `src/vaultspec_a2a/control/worker_management.py`.
- Modified (tests): `src/vaultspec_a2a/worker/tests/test_app.py`.
- Pre-existing vs added: dispatch and administrative shutdown were already gated
  with the worker IPC bearer by the owner's landed IPC auth; this Step extends the
  gate to `/health` and adds the counterpart probe authentication so the gate does
  not regress the watchdog or spawn provenance path.

## Notes

- The probe-authentication change touches the worker-management module because a
  gated worker `/health` is only correct if the gateway's own liveness probes
  present the shared bearer; without it the watchdog would read a paired worker as
  down and crash-loop it. The change is additive and reconciled onto one
  header authority.
- Gates: ruff and ty clean; the worker suite (86 passed) and the control suite
  (97 passed, including the worker-provenance token tests) both pass.
