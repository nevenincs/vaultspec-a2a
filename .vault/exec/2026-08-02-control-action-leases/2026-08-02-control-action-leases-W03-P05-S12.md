---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:3dcad9f630c8916c136de73bcb81daad5fcdef50416200509063b21995a65a16'
step_id: 'S12'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Migrate follow-up message dispatch to shared leases

## Scope

- `src/vaultspec_a2a/control/message_service.py`

## Description

Migrated follow-up messages to shared leases and exact internal dispatch-application receipt settlement.

## Outcome

HTTP acknowledgement no longer marks a message applied; the first real graph event emits a private receipt that settles the exact dispatch ID.

## Notes

Unreachable delivery no longer terminalizes the thread and block expiry redrive.
