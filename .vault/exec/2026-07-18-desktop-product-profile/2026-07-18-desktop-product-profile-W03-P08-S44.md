---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S44'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Use only the worker IPC credential for gateway-facing event heartbeat and health traffic

## Scope

- `src/vaultspec_a2a/api/internal.py`

## Description

- Route the internal WebSocket authentication through the one shared worker-IPC
  bearer authority instead of a duplicated inequality check, so every
  gateway-facing internal channel (events, heartbeat, health, and the WebSocket)
  enforces the same worker IPC credential rule.
- Certify over real HTTP that the internal readiness and heartbeat endpoints
  require the worker IPC credential and reject the attach credential, proving the
  two planes are non-interchangeable.

## Outcome

- Modified: `src/vaultspec_a2a/api/internal.py`.
- Created: `src/vaultspec_a2a/api/tests/test_internal_worker_ipc.py`.
- Pre-existing vs added: the HTTP internal endpoints were already gated with the
  worker IPC credential by the owner's landed router dependency; this Step aligns
  the WebSocket onto the same authority and adds the non-interchangeability
  certification.

## Notes

- Gates: ruff and ty clean; the new certification and the existing internal auth
  suite pass (39 passed in the internal-scoped selection).
