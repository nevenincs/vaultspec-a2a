---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:5039782c3a58c7eb924c324ea288c72438681e2d29f99997791c5f2e948d022c'
step_id: 'S14'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Migrate verdict resume ownership to shared leases

## Scope

- `src/vaultspec_a2a/control/verdict_subscriber.py`

## Description

Replaced verdict metadata claims with the shared durable lease and stable dispatch identity.

## Outcome

Verdict resumes now conflict, replay, redrive, and settle atomically with permission state.

## Notes

Expired verdict leases are eligible for redrive without whole-metadata multiwriter races.
