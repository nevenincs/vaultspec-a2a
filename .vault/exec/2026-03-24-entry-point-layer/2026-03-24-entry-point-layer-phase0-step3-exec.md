---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase-0` `step-3`

Rewired all consumer imports to `ipc/` and deleted `api/schemas/internal.py`.

- Modified: `src/vaultspec_a2a/api/app.py`
- Modified: `src/vaultspec_a2a/api/endpoints.py`
- Modified: `src/vaultspec_a2a/api/internal.py`
- Modified: `src/vaultspec_a2a/worker/app.py`
- Modified: `src/vaultspec_a2a/worker/executor.py`
- Modified: `src/vaultspec_a2a/control/event_handlers.py`
- Modified: `src/vaultspec_a2a/api/schemas/__init__.py`
- Deleted: `src/vaultspec_a2a/api/schemas/internal.py`

## Description

Updated 6 consumer modules to import IPC types from `ipc.schemas` and
`sequenced_to_dict` from `ipc.serializers`. Removed the 6 IPC re-exports
(lines 54-59) and their `__all__` entries from `api/schemas/__init__.py`.
Deleted `api/schemas/internal.py` with no re-export shim. Also caught
`control/event_handlers.py` which imported `ExecutionStateProjectionPayload`
from the old path.

## Tests

Verified zero remaining references to `schemas.internal` in `src/` via grep.
