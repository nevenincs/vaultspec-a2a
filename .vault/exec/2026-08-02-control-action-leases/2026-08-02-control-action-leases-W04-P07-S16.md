---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:cfa5f038f478c84d0e1e56272488110c423b207b2de43e8e9d3c431c214848be'
step_id: 'S16'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Prove identical and competing concurrent clarification submissions

## Scope

- `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`

## Description

Exercised simultaneous identical and competing clarification submissions through real HTTP, SQLite, worker, and graph boundaries.

## Outcome

Exactly one competing continuation wins; replays remain HTTP 200 under concurrent receipt settlement and the accepted prompt appears once.

## Notes

The deterministic regression issues six concurrent replays during real Executor application.
