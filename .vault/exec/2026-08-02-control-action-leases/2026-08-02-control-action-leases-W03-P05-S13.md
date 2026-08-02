---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:470b5cca5bebf8b60d6481f188dde1882ffb0f7e15821baa475cb8b963d25a42'
step_id: 'S13'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Migrate cancellation dispatch to shared leases

## Scope

- `src/vaultspec_a2a/control/cancel_service.py`

## Description

Migrated cancellation to one thread-resource election regardless of client retry label.

## Outcome

Concurrent cancellation labels share one stable action and dispatch; definite and ambiguous failures follow the common policy.

## Notes

Response compatibility continues to echo the caller label while resource identity stays canonical.
