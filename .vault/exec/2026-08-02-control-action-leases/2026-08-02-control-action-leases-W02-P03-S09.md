---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:a3199da4453d70a519f9c8ac1a5968bd8fee1a3c2295767712683a14a2e9427e'
step_id: 'S09'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Reconcile parked and applied clarification leases after restart

## Scope

- `src/vaultspec_a2a/lifecycle/reconciliation.py`
- `src/vaultspec_a2a/database/reconciliation.py`

## Description

Classified parked clarification actions during startup and redrove expired committed leases through the production worker path.

## Outcome

Restart recovery resumes a genuinely parked file-backed graph and a second pass settles without redispatch.

## Notes

Startup redrive runs only after normal worker dependencies are available.
