---
tags:
  - "#audit"
  - "#domain-logic"
date: "2026-03-27"
related:
  - "[[2026-03-27-domain-logic-plan]]"
  - "[[2026-03-27-domain-logic-extraction-adr]]"
---

# domain-logic wave 1 rolling review

## scope

Wave 1 commit covering Phase 1 (enum extraction + state machine) and Phase 5
(utils hardening). 28 files changed, +382 / -287 lines.

---

## phase 1 — enum extraction and state machine

### 1. boundary integrity

**PASS** — `grep -rn 'from.*database.crud import.*Status' src/ --include='*.py'`
excluding tests and `__pycache__` returns zero matches. No non-test source file
imports enum types from `database.crud` directly.

### 2. import consistency

**PASS** — All 12 consumer files (`api/routes/cancel.py`, `messages.py`,
`permissions.py`, `thread_state.py`, `threads.py`, `ws_dispatch.py`,
`control/diagnostics.py`, `dispatch.py`, `event_handlers.py`, `snapshot.py`,
`database/reconciliation.py`, `lifecycle/reconciliation.py`) now import enums
from `thread.enums`. The test file `api/tests/test_internal.py` also imports
from `thread.enums`.

### 3. facade correctness

**PASS** — `database/__init__.py` re-exports all 7 types from `thread.enums`:
`ApprovalStatus`, `ControlActionResultStatus`, `ControlActionType`,
`InvalidTransitionError`, `PermissionRequestStatus`, `RepairStatus`,
`ThreadStatus`. All 7 appear in both the import block (lines 10-16) and
`__all__` (lines 46-81).

Note: `database/crud.py` still lists the 7 enum names in its own `__all__`
(lines 39-46). These are importable because crud.py imports them from
`thread.enums` at the module level (line 18). This preserves backwards
compatibility for any code doing `from database.crud import ThreadStatus`.
No concern — the canonical source is `thread.enums`, crud.py merely
re-exports for migration safety.

### 4. state machine extraction

**PASS** — `thread/transitions.py` is a pure Layer 1 module. Its only import
is `from .enums import InvalidTransitionError, ThreadStatus`. The
`_VALID_TRANSITIONS` dict and `validate_transition()` function are
byte-identical to the originals in crud.py. `crud.py:update_thread_status()`
now calls `validate_transition()` (line ~291) instead of inline logic.

### 5. lifecycle/reconciliation cleanup

**PASS** — The three private shadow enums (`_ThreadStatus`, `_RepairStatus`,
`_ControlActionType`) in `lifecycle/reconciliation.py` are deleted (23 lines
removed). The module now imports canonical types from `thread.enums` and
references them directly (e.g. `ThreadStatus.INPUT_REQUIRED.value`). No
behavioral change — all `.value` access is preserved.

### 6. AgentState relocation

**PASS** — `AgentState` moved from `utils/enums` to `graph/enums` (line 26).
Added to `graph/enums.__all__`. `utils/enums.py` no longer exports it.
`utils/tests/test_enums.py` imports from `graph.enums` (line 10). No orphaned
references to `utils.enums.AgentState` found in source.

---

## phase 5 — utils hardening

### 7. protocol design: `_LoggingSettings`

**PASS** — `utils/logging.py:19-29` defines `_LoggingSettings(Protocol)` with
4 attributes: `log_level: str`, `no_color: bool`, `ci: bool`, `is_dev: bool`.
Docstring notes the ty/Pydantic limitation (astral-sh/ty#2403). Call sites in
`test_logging.py` use `# ty: ignore[invalid-argument-type]` comments as
documented.

### 8. protocol design: `_TraceSettings`

**PASS** — `utils/trace.py:22-28` defines `_TraceSettings(Protocol)` with 4
attributes: `langsmith_api_key: str`, `langsmith_tracing: bool`,
`langsmith_project: str`, `langsmith_endpoint: str`. The `settings` parameter
in `print_trace_summary()` is typed as `_TraceSettings | None` and raises
`TypeError` when `None`.

### 9. dead code: vowel_counter.py

**PASS** — `utils/vowel_counter.py` is deleted (confirmed file does not exist
on disk). The only remaining reference is in `src/vaultspec_a2a/README.md`
line 433, which is a pre-existing architectural analysis table describing the
*problem* that was fixed. Not an import or functional reference — no action
needed.

### 10. utils/__init__.py cleanup

**PASS** — `utils/__init__.py` no longer re-exports `AgentState` or
`vowel_counter`. Exports are: `AcpRequestId`, `Environment`, `LogLevel`,
`setup_logging`, `human_delta`, `now_utc`, `parse_iso`. Clean and minimal.

### 11. test marker: utils/tests/conftest.py

**PASS** — `conftest.py` auto-applies `pytest.mark.core` to all tests
collected from the `utils/tests/` directory (line 12). Uses `_PACKAGE_DIR`
path prefix matching — correct approach for marker scoping.

---

## style review

### 12. import ordering

**PASS** — All modified files follow the standard ordering: stdlib, then
third-party, then relative project imports. The new `thread.enums` imports
are placed in alphabetical order within the relative import group, separated
from `database.crud` function imports.

### 13. docstrings and naming

**PASS** — New modules (`thread/enums.py`, `thread/transitions.py`) have
module-level docstrings. All enum classes retain their original docstrings.
`_LoggingSettings` and `_TraceSettings` are underscore-prefixed (private) per
convention for protocol types not intended for external consumption.

### 14. thread/__init__.py facade

**PASS** — Uses explicit `from .enums import X as X` re-export pattern
(PEP 484 compliant). `__all__` is alphabetically sorted and includes all 7
enum types plus all pre-existing error/model/state types.

---

## summary

| Check | Verdict |
|-------|---------|
| Boundary integrity | PASS |
| Import consistency | PASS |
| Facade correctness (database) | PASS |
| State machine extraction | PASS |
| Reconciliation cleanup | PASS |
| AgentState relocation | PASS |
| _LoggingSettings Protocol | PASS |
| _TraceSettings Protocol | PASS |
| Dead code removal | PASS |
| utils/__init__ cleanup | PASS |
| Test marker | PASS |
| Import ordering | PASS |
| Docstrings/naming | PASS |
| thread/__init__ facade | PASS |

**No blockers. No concerns. Wave 1 is clean.**

---

## phase 2 — boundary enforcement

### 15. zero `api.schemas.enums` imports in control/

**PASS** — `grep -rn 'from.*api\.schemas\.enums' control/ --include='*.py'` returns
zero matches. The `control/` directory has no imports from `api.schemas.enums`.

### 16. zero `api.*` imports in control/ (full boundary)

**PASS** — `grep -rn 'from.*api\.' control/ --include='*.py'` returns zero matches.
The entire `control/` package is free of any `api/` layer imports. Clean boundary.

### 17. PlanEntry is a dataclass in thread/models.py

**PASS** — `PlanEntry` at line 19-30 is `@dataclass(frozen=True, slots=True)` with
three plain `str` fields: `content`, `status` (default `"pending"`), `priority`
(default `"medium"`). No wire-protocol enum imports — docstring explicitly notes
values correspond to `PlanEntryStatus` / `PlanEntryPriority` in `api.schemas.enums`
but the domain type uses plain strings. Correct separation.

---

## phase 3 — D-12 dependency inversion

### 18. control/projection.py — zero `api/schemas/snapshots` imports

**PASS** — No `api.schemas` imports of any kind. Imports snapshot types exclusively
from `thread.snapshots` (8 types: `PLAN_APPROVAL_PAUSE_CAUSES`,
`CheckpointProjection`, `ExecutionStateProjection`, `ExecutionTaskData`,
`PermissionData`, `PermissionOptionData`, `ProjectedInterrupt`, `ThreadStateData`).
Graph enums from `graph.enums`. DB functions from `database.crud`. Clean.

### 19. control/snapshot.py — zero `api/schemas` imports

**PASS** — Imports snapshot types from `thread.snapshots` (7 types: `AgentData`,
`ArtifactData`, `MessageData`, `PermissionData`, `PermissionOptionData`,
`ThreadStateData`, `ToolCallData` plus 5 pure functions). Graph enums from
`graph.enums`, aggregator from `streaming.aggregator`. No `api/` imports at all.

### 20. api/routes/thread_state.py — adapter exists and conversion correct

**PASS** — `_to_pydantic()` adapter at line 41-43 converts `ThreadStateData` to
`ThreadStateSnapshot` via `ThreadStateSnapshot.model_validate(asdict(data))`. This
is the correct `dataclass → dict → Pydantic` bridge. The endpoint constructs
`ThreadStateData` (domain), enriches it through control functions, then converts
to Pydantic at the return boundary (line 157). Clean adapter pattern.

### 21. thread/snapshots.py — all 8 D-12 dataclasses present

**PASS** — All 8 Layer 1 dataclasses exist with correct field names and types:

- `MessageData` (line 158): `message_id`, `role`, `content`, `timestamp`, `agent_id`
- `ToolCallData` (line 169): `tool_call_id`, `title`, `kind`, `status`, `locations`, `content`
- `ArtifactData` (line 181): `artifact_id`, `filename`, `content`, `complete`
- `PermissionOptionData` (line 191): `option_id`, `name`, `kind`
- `PermissionData` (line 199): `request_id`, `description`, `options`, `tool_call`
- `AgentData` (line 209): `agent_id`, `node_name`, `state`, `provider`, `model`, `role`, `display_name`, `description`
- `ExecutionTaskData` (line 224): `task_id`, `name`, `path`, `has_error`, `error_type`, `interrupt_ids`, `interrupt_types`, `has_nested_state`, `has_result`
- `ThreadStateData` (line 239): 26 fields covering thread identity, messages, checkpoint, execution, degradation, and repair state

All use `@dataclass(slots=True)`. Module docstring declares Layer 1 with no
`api/` or `control/` imports. Only imports: `langchain_core.messages` (for
classification), `graph.enums.PermissionType`, `.enums.ThreadStatus`, `.models.PlanEntry`.

Also includes 3 projection dataclasses (`ProjectedInterrupt`, `CheckpointProjection`,
`ExecutionStateProjection`), 6 pure functions (`classify_message_role`,
`extract_message_timestamp`, `derive_message_id`, `normalize_plan_entries`,
`normalize_artifacts`, `finalize_snapshot_replay_status`), 4 event classification
predicates, and 2 shared constants (`PLAN_APPROVAL_PAUSE_CAUSES`,
`TERMINAL_STATUS_MAP`).

---

## phase 4 — crud split

### 22. database/__init__.py re-exports ALL symbols

**PASS** — `database/__init__.py` (144 lines) re-exports all public symbols from
all 4 source modules:

- 7 enum types from `thread.enums`
- `save_model` from `crud.py`
- 8 functions from `crud_artifacts`
- 13 functions from `crud_permissions`
- 13 functions from `crud_threads`
- 5 ORM models from `models`
- 6 session utilities from `session`
- `run_migrations` from `migrate`

`__all__` lists 53 public symbols alphabetically. Both `crud.py` and
`__init__.py` serve as facades — `crud.py` re-exports sub-module symbols for
backwards compatibility (`from database.crud import X`), `__init__.py` re-exports
for the canonical path (`from database import X`).

### 23. no file exceeds 400 lines

**PASS** — Line counts: `crud.py` 211, `crud_threads.py` 359,
`crud_permissions.py` 299, `crud_artifacts.py` 126, `_crud_helpers.py` 130.
All under 400. The original monolith has been decomposed into focused modules.

### 24. zero circular imports between crud modules

**PASS** — `grep 'from.*crud_threads\|from.*crud_permissions\|from.*crud_artifacts'`
in `crud_*.py` returns zero matches. The sub-modules do not import from each other.
Shared utilities live in `_crud_helpers.py` which the sub-modules import from,
forming a DAG with no cycles:

```
_crud_helpers.py  ←  crud_threads.py
                  ←  crud_permissions.py
                  ←  crud_artifacts.py
crud.py  →  (re-exports from all above)
```

---

## test coverage

### 25. test_snapshots.py — comprehensive

**PASS** — `thread/tests/test_snapshots.py` (397 lines) covers:

- `classify_message_role` — 4 tests (Human, AI, Tool, unknown)
- `extract_message_timestamp` — 3 tests (datetime, ISO string, fallback)
- `derive_message_id` — 3 tests (stored id, hash fallback, role differentiation)
- `normalize_plan_entries` — 3 tests (dict input, passthrough, skip non-dict)
- `normalize_artifacts` — 2 tests (dict input, skip non-dict)
- `finalize_snapshot_replay_status` — 5 tests (durable, error, best_effort, submitted, gap)
- Event predicates — 7 tests (terminal, permission, progress; true/false paths)
- `classify_permission_pause_reason` — 3 tests (plan_approval, regular, None)
- Constants — 2 tests (PLAN_APPROVAL_PAUSE_CAUSES, TERMINAL_STATUS_MAP)
- **D-12 round-trip tests** — 7 tests verifying `dataclass → asdict → Pydantic model_validate` for all 7 snapshot types (`MessageData`, `ToolCallData`, `ArtifactData`, `PermissionData`, `AgentData`, `ExecutionTaskData`, `ThreadStateData`)

No mocks, no skips, no patches. All tests use real objects. The round-trip tests
are especially valuable — they prove the D-12 dataclass field names are compatible
with the Pydantic wire models.

### 26. test_transitions.py — comprehensive

**PASS** — `thread/tests/test_transitions.py` (79 lines) covers:

- 7 happy-path transition tests (submitted→running, running→completed/cancelled/failed, input_required→running, cancelling→cancelled, completed→archived)
- Same-status noop test
- 3 invalid transition tests with `pytest.raises(InvalidTransitionError)`
- `test_every_status_has_transitions_defined` — exhaustive check that every `ThreadStatus` member appears in `_VALID_TRANSITIONS`
- `test_no_self_loops_in_transition_table` — invariant check
- `test_terminal_states_lead_only_to_archived_or_nothing` — structural constraint

No mocks, no skips. Tests exercise the real transition table.

---

## phase 2-4 summary

| Check | Verdict |
|-------|---------|
| Zero api.schemas.enums in control/ | PASS |
| Zero api.* imports in control/ | PASS |
| PlanEntry is a dataclass | PASS |
| projection.py — no api/schemas imports | PASS |
| snapshot.py — no api/schemas imports | PASS |
| thread_state.py adapter | PASS |
| All 8 D-12 dataclasses exist | PASS |
| database/__init__.py facade complete | PASS |
| No file exceeds 400 lines | PASS |
| Zero circular imports in crud | PASS |
| test_snapshots.py coverage | PASS |
| test_transitions.py coverage | PASS |

**No blockers. No concerns. Phases 2-4 are clean.**
