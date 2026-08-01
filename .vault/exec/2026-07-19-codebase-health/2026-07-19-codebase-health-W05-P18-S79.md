---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:164185b4c349a4b6b57f3a1572d743b2a27bb3673bad43c18fafb95583b3fc2f'
step_id: 'S79'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Certify progress reconnection ordering bounded token deltas and forbidden-content exclusion

## Scope

- `tests/acceptance/test_dashboard_stream.py`

## Description

- Certified terminal replay across reconnects, and that the progress stream
  excludes forbidden content while still carrying its permitted fields.

## Outcome

Closed. Reconnection is certified as idempotent and reconciling rather than
merely non-crashing, which is the property a consumer depends on when a stream
drops mid-run.

The exclusion assertions check a forbidden field ABSENT and a permitted field
PRESENT, so an empty or truncated payload cannot satisfy them - the failure mode
that makes exclusion tests worthless.
