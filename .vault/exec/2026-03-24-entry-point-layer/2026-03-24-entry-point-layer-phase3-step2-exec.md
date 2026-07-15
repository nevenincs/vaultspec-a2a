---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase3` `step2`

Extracted snapshot business logic from `api/endpoints.py` to `control/snapshot.py` (286 lines).

- Created: `src/vaultspec_a2a/control/snapshot.py`
- Modified: `src/vaultspec_a2a/api/endpoints.py`

## Description

Extracted 4 functions from `api/endpoints.py` into `control/snapshot.py`:

- `_enrich_snapshot_from_state` -> `enrich_snapshot_from_state` (200 lines, maps LangGraph state to snapshot)
- `_MinimalState` -> `MinimalState` (adapter class for state reuse)
- `_load_checkpoint_history_depth` -> `load_checkpoint_history_depth` (checkpoint listing)
- `_finalize_snapshot_replay_status` -> `finalize_snapshot_replay_status` (replay contract)

Dropped the leading underscore from all names since they are now public module-level exports rather than file-private helpers. `endpoints.py` reduced from 1883 to 1627 lines.

Removed now-unused imports from `endpoints.py`: `contextlib`, `hashlib` (still used elsewhere), `StateSnapshot`, `classify_tool_kind`, `PlanEntry`, `ArtifactSnapshot`, `MessageSnapshot`, `ToolCallSnapshot`, `_AgentSnapshot`, `_PermissionOptionSnapshot`, `_PermissionSnapshot`, `PermissionOptionKind`, `ToolCallStatus`, `ToolKind`. Retained `AgentLifecycleState` as it is still used in the team status endpoint.

## Tests

Snapshot functions are exercised indirectly through the `get_thread_state_endpoint` route. Direct unit tests are not present in the baseline for these helpers. All 1030 non-Phase-1-blocked tests pass.
