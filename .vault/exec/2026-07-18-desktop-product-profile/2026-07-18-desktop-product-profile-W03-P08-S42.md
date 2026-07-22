---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S42'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Require both authenticated runtime control and receipt ownership for administrative shutdown

## Scope

- `src/vaultspec_a2a/api/routes/admin.py`

## Description

- Require both the attach credential and the receipt-bound lifecycle ownership
  capability on the administrative shutdown route, so a foreign attachment that
  can reach the product surface still cannot stop the gateway.
- Certify the two rejection paths over real HTTP: no attach is a 401, and a valid
  attach without (or with a wrong) lifecycle capability is a redacted 403.

## Outcome

- Modified: `src/vaultspec_a2a/api/routes/admin.py`.
- Created: `src/vaultspec_a2a/api/tests/test_admin_shutdown_auth.py`.
- Pre-existing vs added: attach on the admin router is inherited from the product
  gating; this Step adds the explicit receipt-ownership requirement and states
  both dependencies at the route for a security-critical endpoint.

## Notes

- The authorized 202 path terminates the process (it signals the running
  interpreter), so it is not exercised in-process; the two rejection paths fully
  prove the conjunction of attach and lifecycle capability.
- Gates: ruff and ty clean; the three real-HTTP rejection cases pass.
