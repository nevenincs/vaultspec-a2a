---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S13'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Resume the same deletion saga when the delete endpoint receives a replayed request

## Scope

- `src/vaultspec_a2a/api/routes/threads.py`
- `src/vaultspec_a2a/control/thread_service.py`

## Description

- Made a replayed DELETE resume the existing saga instead of starting a second
  one or reporting a spurious conflict.

## Outcome

Closed. Replay is the normal case, not the exceptional one - a client that times
out and retries must not fork the deletion. Resuming the same saga is what keeps
the manifest the single source of scope across attempts.

## Notes

Commit `5e90d584`.
