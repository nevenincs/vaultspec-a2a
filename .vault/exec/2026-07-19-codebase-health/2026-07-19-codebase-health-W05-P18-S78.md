---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:5080ca8c18d5fc64a88aa7753c06de1152f060873e6098985075b3dec0c12de6'
step_id: 'S78'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Certify authenticated prepare behavior through the supported public surface

## Scope

- `tests/acceptance/test_dashboard_contract.py`

## Description

- Certified that an authenticated prepare reserves capacity without minting a
  run or a token.

## Outcome

Closed. Prepare is certified through the versioned public surface with a real
bearer against a real gateway, not through an internal call, so what is proven
is the contract a consumer actually meets.

## Notes

The certification disables the test-only unauthenticated bypass explicitly
rather than relying on it being off, so the authenticated path is what runs.
