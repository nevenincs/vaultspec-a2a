---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:7b3c53dec500e205bb6e14505e53a5afbf09525c66430364b8b0e42f246fd349'
step_id: 'S14'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove deletion retries crash recovery hidden-state behavior and finalization against real control and checkpoint stores

## Scope

- `tests/control`
- `tests/api`

## Description

- Proved retry, crash recovery, hidden-state, and finalization behaviour against
  real control and checkpoint stores.

## Outcome

Closed. The proofs run against real stores rather than a substitute, which is
the only way the durability claims mean anything - a saga that is resumable
against an in-memory stand-in has proven nothing about crash recovery.

## Notes

Commit `f40bf075`.

The Step's scope names `tests/control` and `tests/api`, but there is no `tests/`
directory at the repository root and `pyproject.toml` sets
`testpaths = ["src/vaultspec_a2a"]`. The tests landed beside the code they
exercise instead, which is where pytest collects them. Several later Steps carry
the same stale scope paths and will need the same judgement.
