---
tags:
  - '#exec'
  - '#domain-logic'
date: '2026-03-28'
related:
  - '[[2026-03-27-domain-logic-plan]]'
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-27-domain-logic-extraction-research]]'
  - '[[2026-03-27-domain-logic-rolling-review-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `domain-logic` final summary

Layer 2b domain logic extraction completed across 7 phases (0-6) in 3 waves.
46 files changed, +3,919 / -1,558 lines. All boundary violations eliminated.
All 12 ADR decisions (D-01 through D-12) implemented. Zero regressions.

## Phase-by-phase summary

### Phase 0 — baseline + frozen dataclass fix

Recorded pre-execution test baseline: 1,041 total passed, 425 core, 616
middleware. Fixed frozen dataclass test assertions in
`thread/tests/test_models.py` and `lifecycle/tests/test_reconciliation.py`
where `object.__setattr__()` bypassed frozen guards on `slots=True`
dataclasses in Python 3.13. Switched to direct attribute assignment with
`pytest.raises(AttributeError)`. Committed Layer 2b research, ADR, and plan
artifacts.

- Commit: `1b65e59` — fix: frozen dataclass tests + Layer 2b research/ADR/plan
- Tests: 1,041 passed (baseline established)

### Phase 1 — D-01, D-02, D-11: domain enums + state machine to Layer 1

Created `thread/enums.py` with 6 domain enums (`ThreadStatus`, `RepairStatus`,
`ControlActionType`, `ControlActionResultStatus`, `PermissionRequestStatus`,
`ApprovalStatus`) and `InvalidTransitionError`. Created
`thread/transitions.py` with `_VALID_TRANSITIONS` table and
`validate_transition()`. Rewired all 16+ consumer files to import from
`thread.enums`. Deleted 3 private shadow enums from
`lifecycle/reconciliation.py` (D-11). Updated `database/__init__.py` facade
to re-export all 7 enum types.

- Commit: `b3ef2e8` — refactor: Phase 1 + Phase 5 (Wave 1)
- Tests: all passing, no regressions

### Phase 5 — D-09, D-10: utils cleanup (parallel with Phase 1)

Removed `control.config` runtime imports from `utils/logging.py` and
`utils/trace.py` via `_LoggingSettings` and `_TraceSettings` Protocol types
(dependency inversion). Relocated `AgentState` from `utils/enums.py` to
`graph/enums.py`. Deleted `utils/vowel_counter.py` (dead code). Changed
`utils/tests/conftest.py` marker from `middleware` to `core`.

- Commit: `b3ef2e8` — refactor: Phase 1 + Phase 5 (Wave 1)
- Tests: all passing, no regressions

### Phase 2 — D-03, D-04: boundary enforcement + PlanEntry extraction

Canonicalized enum imports in `control/snapshot.py` and
`control/projection.py` — replaced `api.schemas.enums` imports with
`graph.enums`. Moved `PlanEntry` from `api/schemas/events.py` to
`thread/models.py` as a frozen dataclass with plain `str` fields. Updated
`api/schemas/events.py` to import from `thread.models`. Verified zero
`api.schemas.enums` imports remain in `control/`.

- Commit: `11eccdd` — refactor: Phase 2
- Tests: all passing, no regressions

### Phase 3 — D-05, D-06, D-07, D-12: domain logic extraction + dependency inversion

Created `thread/snapshots.py` (498 lines) containing:

- 3 projection dataclasses (`ProjectedInterrupt`, `CheckpointProjection`,
  `ExecutionStateProjection`) extracted from `control/projection.py`
- 8 Layer 1 snapshot dataclasses (D-12): `ThreadStateData`, `MessageData`,
  `ToolCallData`, `ArtifactData`, `PermissionData`, `PermissionOptionData`,
  `AgentData`, `ExecutionTaskData`
- 6 pure functions extracted from `control/snapshot.py` and
  `control/projection.py`: `classify_message_role`,
  `extract_message_timestamp`, `derive_message_id`, `normalize_plan_entries`,
  `normalize_artifacts`, `finalize_snapshot_replay_status`
- 4 event classification predicates (D-07) extracted from
  `control/event_handlers.py`: `is_terminal_event`, `is_permission_event`,
  `is_progress_event`, `classify_permission_pause_reason`
- 2 shared constants: `PLAN_APPROVAL_PAUSE_CAUSES`, `TERMINAL_STATUS_MAP`

Dependency-inverted `control/projection.py` and `control/snapshot.py` to
return Layer 1 dataclasses instead of Pydantic models. Added thin
`_to_pydantic()` adapter in `api/routes/thread_state.py` for wire
serialization. Created `thread/tests/test_snapshots.py` (396 lines, 39 tests)
and `thread/tests/test_transitions.py` (78 lines, 12 tests). All tests use
real objects — no mocks, no skips, no patches.

- Commit: `2149ff3` — refactor: Phase 3 + Phase 4
- Tests: all passing, no regressions

### Phase 4 — D-08: crud.py split

Split monolithic `database/crud.py` (976 lines) into 4 focused modules:

- `database/crud.py` — 211 lines (shared utilities: `save_model`, `_utcnow`,
  `_UnsetType`/`_UNSET`)
- `database/crud_threads.py` — 359 lines (thread CRUD, status lifecycle,
  repair/approval/execution state, metadata)
- `database/crud_permissions.py` — 299 lines (permission requests, control
  actions)
- `database/crud_artifacts.py` — 126 lines (artifacts, permission logs, cost
  tracking)
- `database/_crud_helpers.py` — 130 lines (shared helper functions)

Updated `database/__init__.py` facade to re-export all 53 public symbols.
No circular imports between sub-modules — shared utilities in
`_crud_helpers.py` form a clean DAG.

- Commit: `2149ff3` — refactor: Phase 3 + Phase 4
- Tests: all passing, no regressions

### Phase 6 — housekeeping + final validation

Updated `control/__init__.py` docstring and `__all__`. Fixed stale lazy-import
comment in `providers/__init__.py`. Updated `src/vaultspec_a2a/README.md`
with new module listings, dependency graph, and Layer 2b CLEAN status. Ran
full boundary validation suite — all checks passed.

- Commit: `d9d0f58` — chore: Phase 6
- Tests: all passing, no regressions

## Final metrics

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Total tests passed | 1,041 | 1,094 | +53 |
| Core tests passed | 425 | 520 | +95 |
| Middleware tests passed | 616 | 574 | -42 (reclassified to core) |
| Files changed | — | 46 | — |
| Lines added | — | 3,919 | — |
| Lines removed | — | 1,558 | — |
| Net delta | — | +2,361 | — |

New files created:

- `thread/enums.py` (83 lines)
- `thread/transitions.py` (95 lines)
- `thread/models.py` (15 lines)
- `thread/snapshots.py` (498 lines)
- `thread/tests/test_snapshots.py` (396 lines)
- `thread/tests/test_transitions.py` (78 lines)
- `database/crud_threads.py` (359 lines)
- `database/crud_permissions.py` (299 lines)
- `database/crud_artifacts.py` (126 lines)
- `database/_crud_helpers.py` (130 lines)

Files deleted:

- `utils/vowel_counter.py`

## Boundary validation results

All four boundary checks return zero violations:

- `control/` -> `api/` imports: **0 matches** (was 17 import statements)
- Domain enums in `database/`: **0 class definitions** (moved to `thread/enums.py`)
- `utils/` -> `control/` imports: **0 matches** (dependency-inverted via Protocols)
- Private shadow enums in `lifecycle/`: **0 copies** (deleted, uses `thread.enums`)

## ADR decision coverage

All 12 decisions from the ADR are implemented:

- **D-01** — Domain enums extracted to `thread/enums.py`
- **D-02** — State machine extracted to `thread/transitions.py`
- **D-03** — `control/` enum imports canonicalized to `graph.enums`
- **D-04** — `PlanEntry` moved to `thread/models.py` as frozen dataclass
- **D-05** — Projection dataclasses and pure functions in `thread/snapshots.py`
- **D-06** — Snapshot pure functions extracted to `thread/snapshots.py`
- **D-07** — Event handler predicates extracted to `thread/snapshots.py`
- **D-08** — `crud.py` split into 4 focused modules (all under 400 lines)
- **D-09** — `utils/logging.py` dependency-inverted via `_LoggingSettings` Protocol
- **D-10** — `utils/trace.py` dependency-inverted via `_TraceSettings` Protocol
- **D-11** — Private lifecycle enum copies deleted, canonical imports used
- **D-12** — 8 Layer 1 snapshot dataclasses with round-trip test coverage

## Audit status

- **Wave 1 rolling review** (Phase 1 + Phase 5): 14 checks, all PASS
- **Wave 2 rolling review** (Phase 2 + Phase 3 + Phase 4): 12 checks, all PASS
- **Test coverage audit**: `test_snapshots.py` (39 tests), `test_transitions.py`
  (12 tests) — no mocks, no skips, no patches
- **D-12 round-trip tests**: 7 tests verifying dataclass-to-Pydantic compatibility
  for all snapshot types

No blockers. No concerns. All rolling reviews passed clean.
