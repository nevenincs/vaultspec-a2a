---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-0` `step-1`

Created `ipc/` package and migrated 4 schema types from `api/schemas/internal.py`.

- Created: `src/vaultspec_a2a/ipc/__init__.py`
- Created: `src/vaultspec_a2a/ipc/schemas.py`

## Description

Moved `DispatchRequest`, `DispatchResponse`, `ExecutionStateProjectionPayload`,
`ExecutionTaskProjectionPayload` from `api/schemas/internal.py` to
`ipc/schemas.py`. Dead types `HeartbeatMessage` and `WorkerEventEnvelope` were
dropped (zero importers confirmed via grep). The `DispatchRequest.recursion_limit`
default factory importing `control.config.settings` was preserved.

`ipc/__init__.py` provides public re-exports for all 4 types.

## Tests

No test changes in this step. Types verified importable in subsequent steps.
