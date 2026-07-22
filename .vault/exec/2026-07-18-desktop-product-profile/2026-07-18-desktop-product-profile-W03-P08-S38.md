---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S38'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Implement constant-time attach and lifecycle capability dependencies with redacted failures

## Scope

- `src/vaultspec_a2a/api/dependencies.py`

## Description

- Re-export the pre-existing attach-control gate through `api/dependencies.py`
  as `require_attach`, giving route modules one import surface for authentication
  without a second attach implementation.
- Add `require_lifecycle_capability`: a constant-time (`hmac.compare_digest`)
  dependency that requires the receipt-bound ownership capability header on top of
  attach, failing closed with a redacted 403 on mismatch and 503 when the runtime
  capability is unconfigured; honours the explicit test-only bypass.
- Certify both dependencies over real HTTP against a live app instance.

## Outcome

- Modified: `src/vaultspec_a2a/api/dependencies.py`.
- Created: `src/vaultspec_a2a/api/tests/test_lifecycle_capability_dependency.py`.
- Pre-existing vs added: attach authentication is the owner's landed
  constant-time bearer gate, reused verbatim; only the distinct lifecycle-capability
  gate and its header constant are added here.

## Notes

- The lifecycle capability travels in a distinct header from the attach bearer so
  the two planes never alias; loopback-only exposure keeps the raw value off any
  shared transport.
- Gates: ruff and ty clean; the six real-HTTP dependency cases pass.
