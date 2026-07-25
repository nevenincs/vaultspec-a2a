---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S27'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove progress allowlisting with a real authenticated stream client

## Scope

- `tests/streaming`
- `tests/api`

## Description

- Proved allowlisting through a real authenticated stream client rather than a
  direct call to the projection.

## Outcome

Closed. The proof explicitly sets `allow_unauthenticated_v1_for_testing` to
False and presents a real bearer, so it exercises the authenticated path instead
of the test bypass - which is the difference between proving the boundary and
proving a function.

The assertions check a forbidden field ABSENT and a permitted field PRESENT, so
an empty payload cannot satisfy them.

## Notes

Commit `f7e67f04`. The Step's scope names `tests/streaming` and `tests/api`,
which do not exist; the tests landed beside the code they exercise, where pytest
collects them.
