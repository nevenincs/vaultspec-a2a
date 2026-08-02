---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0d335d00ff7c4abdb14d84380ab9f81ef0b3960bb2eb03b6e761963f153e493a'
step_id: 'S07'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Implement leased clarification orchestration service

## Scope

- `src/vaultspec_a2a/control/clarification_service.py`

## Description

Implemented committed clarification action leasing, payload conflict detection, stable dispatch, replay, receipt settlement, and definite-failure release.

## Outcome

Concurrent submissions elect one winner; identical retries replay durable state; competing bodies return conflict.

## Notes

A live retry exposed rollback-expired thread reads; required thread fields are now snapshotted before lease election.
