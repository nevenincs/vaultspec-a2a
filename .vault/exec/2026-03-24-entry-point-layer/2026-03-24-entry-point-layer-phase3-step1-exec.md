---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase3` `step1`

Relocated `api/projection.py` (491 lines) to `control/projection.py`.

- Deleted: `src/vaultspec_a2a/api/projection.py`
- Created: `src/vaultspec_a2a/control/projection.py`

## Description

Moved the entire contents of `api/projection.py` to `control/projection.py` per D-04. The file contains `ProjectedInterrupt`, `CheckpointProjection`, `ExecutionStateProjection`, `project_checkpoint_tuple`, `apply_checkpoint_projection`, `enrich_snapshot_from_durable_state`, `enrich_snapshot_from_execution_state`, and all helpers.

Adjusted relative imports: `.schemas.enums` and `.schemas.snapshots` became `..api.schemas.enums` and `..api.schemas.snapshots` since the module moved from `api/` to `control/`. Database imports (`..database.crud`) remained unchanged as both packages are siblings under the root package.

No re-export shim was created at the old path.

## Tests

All 6 tests in `api/tests/test_projection.py` pass after import rewiring (Step 3).
