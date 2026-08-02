---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e2fb8a9582bb853296db55ae348c08bb77d7adc23d2433667ddde621bf6aec1a'
step_id: 'S06'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Add clarification resolution receipts to domain and graph state

## Scope

- `src/vaultspec_a2a/thread`
- `src/vaultspec_a2a/graph/nodes/clarification.py`

## Description

Added canonical clarification-resolution fingerprints and checkpoint receipt state for answer and prompt continuations.

## Outcome

Checkpoint truth now identifies the exact request and accepted resolution without storing prompt text in the receipt.

## Notes

Prompt content remains only in the human message; the receipt carries a digest.
