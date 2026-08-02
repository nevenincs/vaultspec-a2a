---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e7b66688d193016a7c926c4e99020cdc9727553aff6555d6c7bb7949f509a393'
step_id: 'S10'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Migrate permission response reservation and dispatch to shared leases

## Scope

- `src/vaultspec_a2a/control/permission_service.py`

## Description

Migrated permission responses to request-level leases independent of client retry labels and committed projections before network I/O.

## Outcome

Identical retries share one action; competing option or notes conflict; stable dispatch survives redrive.

## Notes

Ambiguous unreachable delivery retains ownership; definite non-delivery releases it.
