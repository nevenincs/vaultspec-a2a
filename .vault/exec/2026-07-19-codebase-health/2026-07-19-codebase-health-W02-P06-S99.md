---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:580e7cc0cd596df1849c4824d9f4e6f746c19dcbba004062790420163a6e5ff9'
step_id: 'S99'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove forbidden fields cannot cross the encoded A2A SSE boundary

## Scope

- `tests/streaming`
- `tests/api`

## Description

- Proved exclusion against the ENCODED frame bytes, not the pre-encoding
  dictionary.

## Outcome

Closed. Asserting on the encoded bytes is what distinguishes this from `S27`:
a projection can be correct while an encoder re-adds or re-serialises a field,
and only the bytes a consumer actually receives settle that.

## Notes

Commit `f7e67f04`. Scope paths `tests/streaming` and `tests/api` do not exist;
the tests landed beside the code they exercise.
