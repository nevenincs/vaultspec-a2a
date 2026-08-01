---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:b1126de95a52b2416d37a9c1154d2a0866e878bdd9a611ac05a8aa4446e85a5a'
step_id: 'S108'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Implement the idempotent repository operation that claims one deletion saga

## Scope

- `src/vaultspec_a2a/control/repositories`

## Description

- Added `claim_deletion_saga`, stamping ownership exactly once.
- Claiming an absent saga returns nothing rather than raising.

## Outcome

Closed. Claim-once is what prevents two workers executing the same manifest
concurrently, which would turn independent cleanup into duplicated deletion.

## Notes

Commit `37f2b4c0`. Covered by `test_claim_stamps_ownership_once` and
`test_claim_absent_saga_returns_none` against a real store.
