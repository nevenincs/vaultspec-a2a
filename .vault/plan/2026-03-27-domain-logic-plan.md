---
tags:
  - '#plan'
  - '#domain-logic'
date: '2026-03-27'
related:
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-27-domain-logic-extraction-research]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-24-core-layer-boundary-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `domain-logic` plan

Layer 2b domain logic extraction: move misplaced domain types, rules, and pure
functions from infrastructure services back to Layer 1. Split monolithic
`crud.py`. Fix layer boundary violations. Eliminate all `control/` -> `api/`
imports via dependency inversion. Implements ADR decisions D-01 through D-12
across 7 phases (0-6) in 3 waves. Each phase preserves the test baseline
(>= 1,041 passed, >= 425 core). No re-export shims. No mocks.

## Proposed Changes

The ADR identifies 6 categories of boundary violation in the current
infrastructure layer: upward `control/` -> `api/` imports (17 import
statements across 2 modules), domain enums in `database/crud.py` (6 enums,
42 values, 16+ consumer files), pure domain logic embedded in `control/`
(1,257 lines across 3 modules), `utils/` importing from `control.config`,
monolithic `crud.py` (976 lines, 11 domains), and dead code + marker drift.

The plan moves domain types to `thread/enums.py`, state machine to
`thread/transitions.py`, pure functions and dataclasses to
`thread/snapshots.py`, dependency-inverts snapshot Pydantic types to Layer 1
dataclasses, splits `crud.py` into 4 focused modules, fixes `utils/` layer
inversions, and cleans up dead code. After all phases, `control/` has zero
imports from `api/`.

## Tasks

<!-- IMPORTANT: This document must be updated between execution runs to
     track progress. -->

### Phase 0 — baseline + frozen dataclass fix ✅ DONE

- Phase summary: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase0-summary.md`

  1. Record test baseline: `pytest -m core -q --tb=no`, `pytest -m middleware
     -q --tb=no`, `pytest -q --tb=no`. Save pass counts.
     - Name: record test baseline
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase0-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Fix frozen dataclass test bugs in `thread/tests/test_models.py` and
     `lifecycle/tests/test_reconciliation.py`. The `object.__setattr__()`
     pattern bypasses frozen guards on `slots=True` dataclasses in Python
     3.13. Switch to direct attribute assignment wrapped in
     `pytest.raises(AttributeError)`.
     - Name: fix frozen dataclass test assertions
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase0-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Verify baseline passes after fix. Commit.
     - Name: verify and commit baseline
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase0-step3.md`
     - Executing agent: `vaultspec-standard-executor`

### Wave 1 (parallel): Phase 1, Phase 5

- `Phase 1` — D-01, D-02, D-11: domain enums + state machine to Layer 1 ✅ DONE
  - Phase summary: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase1-summary.md`

  1. Create `thread/enums.py`. Move the 6 domain enums (`ThreadStatus`,
     `RepairStatus`, `ControlActionType`, `ControlActionResultStatus`,
     `PermissionRequestStatus`, `ApprovalStatus`) and `InvalidTransitionError`
     from `database/crud.py`. Add to `thread/__init__.py` exports.
     - Name: create thread/enums.py with domain enums
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase1-step1.md`
     - Executing agent: `vaultspec-high-executor`

  1. Create `thread/transitions.py`. Move `_VALID_TRANSITIONS` table and the
     transition validation logic from `database/crud.py`. Expose a
     `validate_transition(current, target)` function that raises
     `InvalidTransitionError`. Imports only from `thread/enums.py`.
     - Name: create thread/transitions.py with state machine
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase1-step2.md`
     - Executing agent: `vaultspec-high-executor`

  1. Update all consumers of the moved enums. Use exhaustive grep
     (`grep -rn "from.*database.crud import" src/ --include='*.py'`) to find
     every consumer — research indicates 16+ files for `ThreadStatus` alone.
     Known files include: `database/crud.py`, `database/__init__.py`,
     `database/reconciliation.py`, `control/event_handlers.py`,
     `control/snapshot.py`, `control/projection.py`, `control/dispatch.py`,
     `control/diagnostics.py`, `api/routes/threads.py`,
     `api/routes/messages.py`, `api/routes/permissions.py`,
     `api/routes/cancel.py`, `api/routes/thread_state.py`,
     `api/ws_dispatch.py`, `lifecycle/reconciliation.py`. Also update
     `database/crud.py`'s `update_thread_status()` to call
     `thread.transitions.validate_transition()`. Verify zero orphaned imports
     with grep after all rewiring.
     - Name: rewire all enum consumers to thread.enums
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase1-step3.md`
     - Executing agent: `vaultspec-high-executor`

  1. Update `lifecycle/reconciliation.py` (D-11): drop the 3 private subset
     enums (`_ThreadStatus`, `_RepairStatus`, `_ControlActionType`) and import
     from `thread.enums`. Update its tests accordingly.
     - Name: drop lifecycle private enum copies
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase1-step4.md`
     - Executing agent: `vaultspec-high-executor`

  1. Remove coercion helpers from `database/crud.py` that are no longer needed
     (if any became orphaned). Run `pytest -m core` and full suite. Commit.
     - Name: clean up crud.py and verify
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase1-step5.md`
     - Executing agent: `vaultspec-high-executor`

- `Phase 5` — D-09, D-10: utils cleanup (parallel with Phase 1) ✅ DONE
  - Phase summary: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase5-summary.md`

  1. Refactor `utils/logging.py`: remove the runtime
     `from ..control.config import settings` fallback inside `setup_logging()`.
     The existing `settings_override` parameter becomes the sole settings
     source. Update the 4 callers in `providers/probes/*.py` and any other
     call sites to pass settings explicitly.
     - Name: fix logging.py layer inversion
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase5-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Refactor `utils/trace.py`: remove the runtime
     `from ..control.config import settings` import inside
     `print_trace_summary()`. Accept settings as a parameter. Update callers.
     - Name: fix trace.py layer inversion
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase5-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Move `AgentState` from `utils/enums.py` to `graph/enums.py` (where
     related lifecycle states like `AgentLifecycleState` live). Update
     `utils/__init__.py` and any consumers.
     - Name: relocate AgentState to graph/enums
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase5-step3.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Delete `utils/vowel_counter.py`. Change `utils/tests/conftest.py` marker
     from `middleware` to `core` for pure enum/utility tests. Verify the
     marker change doesn't break test collection. Run full suite. Commit.
     - Name: delete dead code and fix test markers
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase5-step4.md`
     - Executing agent: `vaultspec-standard-executor`

### Wave 2 (sequential, after Phase 1): Phase 2, Phase 3, Phase 4

- `Phase 2` — D-03, D-04: fix upward enum imports + move PlanEntry ✅ DONE
  - Phase summary: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase2-summary.md`

  1. In `control/snapshot.py`, change enum imports from
     `..api.schemas.enums` to `..graph.enums` for `AgentLifecycleState`,
     `PermissionOptionKind`, `ToolCallStatus`, `ToolKind`. In
     `control/projection.py`, change imports from `..api.schemas.enums` to
     `..graph.enums` for `PermissionOptionKind`, `PermissionType`.
     - Name: canonicalize enum imports in control/
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase2-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Move `PlanEntry` from `api/schemas/events.py` to `thread/models.py` as a
     dataclass with matching field names. In `api/schemas/events.py`, replace
     the old Pydantic `PlanEntry` class with a Pydantic model that inherits
     the field structure (e.g., `class PlanEntrySchema(BaseModel)` with
     identical fields) or re-export the dataclass if Pydantic can serialize it
     directly. The wire contract must remain backwards-compatible —
     `PlanUpdateEvent.entries` must still serialize correctly. Update
     `control/snapshot.py` to import `PlanEntry` from `thread.models`. Update
     `thread/__init__.py` exports. Verify API event serialization still works.
     - Name: move PlanEntry to thread/models.py
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase2-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Verify zero `from.*api\.schemas\.enums` imports remain in `control/`.
     Run full suite. Commit.
     - Name: verify enum imports and commit
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase2-step3.md`
     - Executing agent: `vaultspec-standard-executor`

- `Phase 3` — D-05, D-06, D-07, D-12: domain logic extraction + dependency inversion ✅ DONE
  - Phase summary: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-summary.md`

  1. Create `thread/snapshots.py`. Move from `control/projection.py`: the 3
     dataclasses (`ProjectedInterrupt`, `CheckpointProjection`,
     `ExecutionStateProjection`), the 3 pure functions
     (`project_checkpoint_tuple`, `_parse_checkpoint_created_at`,
     `_load_json_list`), and the `PLAN_APPROVAL_PAUSE_CAUSES` constant.
     Note: `ExecutionStateProjection` currently has a
     `list[ExecutionTaskSnapshot]` field — temporarily type it as
     `list[Any]` or forward-ref until Step 4 defines `ExecutionTaskData`.
     Update `control/projection.py` to import from `thread.snapshots`.
     Remove the duplicate `_PLAN_APPROVAL_PAUSE_CAUSES` from
     `control/event_handlers.py`. Add `thread/snapshots.py` exports to
     `thread/__init__.py`.
     - Name: extract projection dataclasses and pure functions to Layer 1
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step1.md`
     - Executing agent: `vaultspec-high-executor`

  1. Move `finalize_snapshot_replay_status` from `control/snapshot.py` to
     `thread/snapshots.py`. Extract the 5 named pure functions from
     `enrich_snapshot_from_state`: `classify_message_role`,
     `extract_message_timestamp`, `derive_message_id`,
     `normalize_plan_entries`, `normalize_artifacts`. Place them in
     `thread/snapshots.py`. Refactor `control/snapshot.py`'s
     `enrich_snapshot_from_state` to call these Layer 1 functions.
     - Name: extract snapshot pure functions to Layer 1
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step2.md`
     - Executing agent: `vaultspec-high-executor`

  1. Extract domain predicates from `control/event_handlers.py` (D-07).
     This is a 2-stage refactor: first extract the inlined classification
     logic into named functions within `event_handlers.py` itself
     (`is_terminal_event`, `is_permission_event`, `is_progress_event`,
     `classify_permission_pause_reason`), then move the named functions
     and constants (terminal status mapping) to `thread/snapshots.py`.
     Update `control/event_handlers.py` to import from `thread.snapshots`.
     - Name: extract event handler predicates to Layer 1
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step3.md`
     - Executing agent: `vaultspec-high-executor`

  1. Define 8 Layer 1 snapshot dataclasses in `thread/snapshots.py` (D-12):
     `ThreadStateData`, `MessageData`, `ToolCallData`, `ArtifactData`,
     `PermissionData`, `PermissionOptionData`, `AgentData`,
     `ExecutionTaskData`. Field names must mirror the corresponding Pydantic
     models in `api/schemas/snapshots.py` for trivial conversion.
     - Name: define Layer 1 snapshot dataclasses
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step4.md`
     - Executing agent: `vaultspec-high-executor`

  1. Refactor `control/projection.py` to construct and return the Layer 1
     dataclasses instead of Pydantic models. Drop all imports from
     `api/schemas/snapshots`. Functions like
     `_permission_snapshot_from_model` now return `PermissionData`,
     `project_execution_state_model` returns `ExecutionStateProjection`
     containing `ExecutionTaskData`, etc.
     - Name: dependency-invert projection.py to return dataclasses
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step5.md`
     - Executing agent: `vaultspec-high-executor`

  1. Refactor `control/snapshot.py` to construct and return Layer 1
     dataclasses instead of Pydantic models. Drop all imports from
     `api/schemas/snapshots` and `api/schemas/events`. Functions like
     `enrich_snapshot_from_state` now return `ThreadStateData` populated
     with `MessageData`, `ToolCallData`, etc.
     - Name: dependency-invert snapshot.py to return dataclasses
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step6.md`
     - Executing agent: `vaultspec-high-executor`

  1. Add a thin adapter in `api/routes/thread_state.py` that converts the
     Layer 1 dataclasses returned by `control/` into the Pydantic models
     from `api/schemas/snapshots` for wire serialization. The handler
     orchestration logic does not change — only the final conversion step
     is added.
     - Name: add dataclass-to-Pydantic adapter in thread_state route
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step7.md`
     - Executing agent: `vaultspec-high-executor`

  1. Verify zero `from.*api\.` imports in `control/` (excluding tests).
     Ensure `thread/tests/test_snapshots.py` exists with tests for the
     extracted pure functions and dataclasses (especially round-trip
     dataclass-to-Pydantic conversion for D-12 types). Ensure
     `thread/tests/test_transitions.py` exists with tests for
     `validate_transition`. Run full suite. Commit.
     - Name: verify boundary, test coverage, and commit
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase3-step8.md`
     - Executing agent: `vaultspec-high-executor`

- `Phase 4` — D-08: split crud.py ✅ DONE
  - Phase summary: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase4-summary.md`

  1. Create `database/crud_threads.py`. Move thread CRUD functions
     (`create_thread`, `get_thread`, `list_threads`,
     `list_non_terminal_threads`, `delete_thread`), status lifecycle
     (`update_thread_status` — now calls `thread.transitions.validate_transition`),
     repair state (`set_thread_repair_state`), approval state
     (`set_thread_approval_state`), execution state
     (`record_thread_execution_state`, `get_thread_execution_state`,
     `delete_thread_execution_state`), and metadata
     (`update_thread_metadata`, `get_thread_metadata`).
     - Name: create crud_threads.py
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase4-step1.md`
     - Executing agent: `vaultspec-high-executor`

  1. Create `database/crud_permissions.py`. Move permission request functions
     (`record_permission_request`, `get_permission_request`,
     `get_pending_permission_requests`,
     `record_permission_response_submission`,
     `mark_permission_request_applied`, `supersede_permission_requests`,
     `expire_pending_permission_requests`) and control action functions
     (`create_control_action`, `get_control_action_by_idempotency_key`,
     `get_latest_control_action`, `mark_control_action_applied`,
     `mark_control_action_duplicate`, `mark_control_action_superseded`).
     - Name: create crud_permissions.py
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase4-step2.md`
     - Executing agent: `vaultspec-high-executor`

  1. Create `database/crud_artifacts.py`. Move artifact functions
     (`create_artifact`, `get_artifact`, `get_artifacts_by_thread`),
     permission log functions (`append_permission_log`,
     `get_permission_logs_by_thread`), and cost tracking functions
     (`append_cost_record`, `sum_cost_by_thread`, `sum_cost_by_agent`).
     - Name: create crud_artifacts.py
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase4-step3.md`
     - Executing agent: `vaultspec-high-executor`

  1. Update `database/__init__.py` facade to import from the 3 new modules.
     Audit the current `__all__` list (currently ~30 symbols; will grow after
     Phase 1 adds enum re-exports). Verify every public symbol is re-exported
     by running `python -c "from vaultspec_a2a.database import *"`.
     `crud.py` retains only `save_model`, `_utcnow`, `_UnsetType`/`_UNSET`,
     and coercion helpers.
     - Name: update database facade
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase4-step4.md`
     - Executing agent: `vaultspec-high-executor`

  1. Verify no file exceeds 300 lines. Verify the 5 test files that import
     directly from `database.crud` still resolve. Run full suite. Commit.
     - Name: verify split and commit
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase4-step5.md`
     - Executing agent: `vaultspec-high-executor`

### Wave 3 (after all above): Phase 6

- `Phase 6` — housekeeping + final validation ✅ DONE
  - Phase summary: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase6-summary.md`

  1. Update `control/__init__.py`: update docstring and `__all__` to reflect
     that domain logic has been extracted. Add `hooks` to `__all__` if missing.
     - Name: update control package metadata
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase6-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Update stale lazy-import comment in `providers/__init__.py` that still
     references the deleted `core/` package.
     - Name: fix stale providers comment
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase6-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Update `src/vaultspec_a2a/README.md`: boundary audit status section to
     reflect Layer 2b is CLEAN. Update the dependency graph and file tree to
     show new modules (`thread/enums.py`, `thread/transitions.py`,
     `thread/snapshots.py`, `database/crud_threads.py`,
     `database/crud_permissions.py`, `database/crud_artifacts.py`).
     - Name: update living architecture document
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase6-step3.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Run the full boundary validation suite:
     - `grep -rn 'from.*api\.' src/vaultspec_a2a/control/ --include='*.py'`
       (excluding tests/) must return zero matches
     - `grep -rn 'class ThreadStatus\|class RepairStatus\|class ControlActionType'
       src/vaultspec_a2a/database/ --include='*.py'` must return zero
     - `grep -rn 'from.*control\.' src/vaultspec_a2a/utils/ --include='*.py'`
       (excluding tests/) must return zero
     - `pytest -m core` >= 425, `pytest -m middleware` >= 616, total >= 1,041
     - Name: final boundary validation
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase6-step4.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Commit final housekeeping. Tag the branch for PR creation.
     - Name: final commit
     - Step record: `.vault/exec/2026-03-27-domain-logic/2026-03-27-domain-logic-phase6-step5.md`
     - Executing agent: `vaultspec-standard-executor`

## Parallelization

The 7 phases are organized into 3 dependency waves:

- **Wave 1**: Phase 1 and Phase 5 run in parallel. Phase 1 moves enums and
  state machine to `thread/`. Phase 5 fixes `utils/` inversions and dead code.
  These touch disjoint files.

- **Wave 2**: Phase 2 requires Phase 1 (enum locations must be settled before
  fixing `control/` imports). Phase 3 requires Phase 2 (import paths must be
  canonical before extracting pure functions and dependency-inverting). Phase 4
  requires Phase 1 only (enums must be extracted before splitting `crud.py`).
  Phase 4 can run in parallel with Phases 2 and 3.

- **Wave 3**: Phase 6 requires all previous phases. Final validation and
  documentation.

Phase 0 (baseline) must complete before any wave starts.

Maximum parallelism: 2 agents in Wave 1 (Phase 1 + Phase 5). Phase 4 can
overlap with Phases 2-3 in Wave 2 (touching `database/` while Phases 2-3
touch `control/` + `thread/`).

## Verification

Success criteria — all must pass after Phase 6 completes:

- Zero `control/` imports from `api/` — verified via grep across all
  `control/*.py` source files (excluding tests)

- Domain enums (`ThreadStatus`, `RepairStatus`, `ControlActionType`,
  `ControlActionResultStatus`, `PermissionRequestStatus`, `ApprovalStatus`)
  defined in `thread/enums.py`, not `database/crud.py`

- `_VALID_TRANSITIONS` state machine in `thread/transitions.py`, not
  `database/crud.py`

- `PlanEntry` defined as a dataclass in `thread/models.py`, not as a
  Pydantic model in `api/schemas/events.py`

- `control/projection.py` and `control/snapshot.py` return Layer 1
  dataclasses from `thread/snapshots.py`, not Pydantic models from
  `api/schemas/snapshots`

- `api/routes/thread_state.py` contains a thin adapter converting
  Layer 1 dataclasses to Pydantic wire-format models

- `utils/` has zero runtime imports from `control/` — verified via grep

- `lifecycle/reconciliation.py` imports enums from `thread/enums.py`,
  no private subset copies remain

- `crud.py` split into 4 files: `crud.py` (~250L), `crud_threads.py`
  (~300L), `crud_permissions.py` (~300L), `crud_artifacts.py` (~150L).
  No file exceeds 400 lines. `database/__init__.py` facade re-exports
  all 46 public symbols

- `utils/vowel_counter.py` deleted

- `utils/tests/` pure enum/utility tests marked as `core`

- `AgentState` lives in `graph/enums.py`, not `utils/enums.py`

- No file in the touched scope exceeds 1,000 lines

- `pytest -m core` >= 425 passed

- `pytest -m middleware` >= 616 passed

- Full suite >= 1,041 passed

- Pre-commit hooks pass on all modified files

Per-phase verification gate: after each phase commit, run the full test suite
and `pytest -m core`. Both must match or exceed the baseline. If a phase
introduces a regression, fix it before proceeding.
