---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:cef99043cacd0ca047ad8dfc60627ffe77a0ccd125a8eebd7903e33dc1dd7343'
step_id: 'S08'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Add deleting state cleanup-manifest and cleanup-result persistence to the control schema

## Scope

- `src/vaultspec_a2a/database`
- `src/vaultspec_a2a/control/repositories`

## Description

- Added the durable deleting state to the control schema, with the cleanup
  manifest and per-item cleanup results persisted alongside it.
- Added the owning Alembic migration.

## Outcome

Closed. This is the foundation the rest of the phase depends on: deletion scope
becomes a captured, immutable fact rather than something re-derived on each
attempt, which is what `deletion-scope-derives-from-a-duplicated-source-of-truth`
asked for.

## Notes

Commit `fd764ed9`; migration `0010_thread_deletion_saga`. The migration is
covered by the repository's Migration Check job, green on the release commit.
