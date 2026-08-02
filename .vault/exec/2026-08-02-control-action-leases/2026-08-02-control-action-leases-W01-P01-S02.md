---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:00c2869a6baa53d20ac57ffc1ada7ad77ab32c9ced321bd035466808751ff3d6'
step_id: 'S02'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Implement atomic reserve acquire release and settle operations

## Scope

- `src/vaultspec_a2a/database/permission_repository.py`
- `src/vaultspec_a2a/database/__init__.py`

## Description

Implemented atomic reservation, acquire, renew, release, settle, and exact dispatch-id lookup repository operations.

## Outcome

All control callers share one committed election contract instead of lookup-before-dispatch logic.

## Notes

Concurrent losing inserts required rollback-safe scalar snapshots to avoid expired ORM reads.
