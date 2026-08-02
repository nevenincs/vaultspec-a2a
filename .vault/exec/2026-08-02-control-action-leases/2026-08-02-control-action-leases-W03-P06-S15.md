---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:09dc114749bc4669e701e577e512b12879651a8216b330b0f569ec8b6f914ffc'
step_id: 'S15'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Remove obsolete metadata claim helpers and ratchet single ownership

## Scope

- `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`

## Description

Removed obsolete verdict metadata claim helpers and added focused lease ownership tests.

## Outcome

The verdict subscriber suite passed with 24 tests after the shared rollback-snapshot fix.

## Notes

No metadata claim compatibility path remains.
