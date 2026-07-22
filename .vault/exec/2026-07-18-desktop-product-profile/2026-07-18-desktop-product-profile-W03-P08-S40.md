---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S40'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Require attach authentication on dashboard product APIs while leaving minimal liveness ungated

## Scope

- `src/vaultspec_a2a/api/routes/__init__.py`

## Description

- Apply the attach gate to every dashboard product router in the route
  registration helper, leaving the aggregate readiness probe ungated as the
  minimal-liveness surface.
- Certify over real HTTP that a product API rejects an unauthenticated caller
  and that the minimal top-level liveness probe answers without a credential.

## Outcome

- Modified: `src/vaultspec_a2a/api/routes/__init__.py`.
- Created: `src/vaultspec_a2a/api/tests/test_product_api_auth.py`.
- Pre-existing vs added: this follows the owner's precedent of gating the
  versioned edge with the same attach dependency; here it is extended to the
  product surface. Existing product-API tests run through the test-only bypass
  and are unaffected (full `api` suite green).

## Notes

- The minimal liveness surface is the top-level liveness probe, which stays
  ungated; the aggregate readiness probe requires live service state and its
  authenticated split is refined in a later readiness Step.
- Gates: ruff clean; the focused product-auth suite and the full
  `src/vaultspec_a2a/api` suite (308 passed) both pass.
