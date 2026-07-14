---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase3` `step3`

Rewired all imports and verified test suite.

- Modified: `src/vaultspec_a2a/api/endpoints.py`
- Modified: `src/vaultspec_a2a/api/tests/test_projection.py`

## Description

Updated `api/endpoints.py` to import projection functions from `control.projection` and snapshot functions from `control.snapshot`. Updated all 4 call sites to use the new public names (`enrich_snapshot_from_state`, `MinimalState`, `load_checkpoint_history_depth`, `finalize_snapshot_replay_status`).

Updated `api/tests/test_projection.py` to import from `...control.projection` instead of `..projection` (both the top-level import block and the inline import on line 230).

Verified via grep that zero files reference the old `api.projection` path.

## Tests

- All 6 `test_projection.py` tests pass (run directly via Python to bypass conftest blocked by parallel Phase 1 changes to `app.py`)
- Full suite (excluding Phase 1 broken `test_app.py`): 1030 passed, 10 failed (all pre-existing), 43 deselected
- Import chain verified: `control.projection`, `control.snapshot`, and `api.endpoints` all import cleanly
