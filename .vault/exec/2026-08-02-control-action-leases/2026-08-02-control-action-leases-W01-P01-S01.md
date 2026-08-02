---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:6625299c5cf26caff3bf0a3de34a20aab070b7bd46225871fff3249a1dfb423c'
step_id: 'S01'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Add generic dispatch lease fields and migration

## Scope

- `src/vaultspec_a2a/database/models.py`
- `src/vaultspec_a2a/database/migrations/versions/0012_control_action_leases.py`

## Description

Added nullable lease identity fields and the globally unique dispatch-id index; added upgrade and downgrade migration coverage.

## Outcome

The control journal now persists stable dispatch identity, ownership token, and lease expiry. Migration tests and the complete database suite passed.

## Notes

The initial review found missing dispatch-id uniqueness; the model and migration now enforce it while allowing historical nulls.
