---
tags:
  - '#adr'
  - '#domain-logic'
date: '2026-03-27'
related:
  - '[[2026-03-27-domain-logic-extraction-research]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
  - '[[2026-03-24-core-layer-boundary-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `domain-logic` adr: `layer-2b-domain-logic-extraction` | (**status:** `proposed`)

## Problem Statement

The Layer 2a decomposition (PR #4) moved business logic from entry points into
`control/`, but left domain types and rules scattered across infrastructure
layers. The 2026-03-27 boundary audit found:

- **Upward dependency:** `control/snapshot.py` and `control/projection.py`
  import from `api/schemas/` — infrastructure services depending on entry
  points, violating the layer boundary rule.
- **Domain enums in data access:** 6 domain enums (42 values), an exception
  class, and a state machine table live in `database/crud.py` instead of
  Layer 1.
- **Domain logic in infrastructure:** 1,257 lines of business rules
  (`projection.py` 85% pure, `snapshot.py` 40% pure, `event_handlers.py` 20%
  pure) are embedded in `control/` alongside infrastructure coordination.
- **Utility layer inversions:** `utils/logging.py` and `utils/trace.py` import
  `Settings` from `control.config` at runtime.
- **Monolithic data access:** `crud.py` (976 lines) covers 11 unrelated
  domains in one file.
- **Dead code and marker drift:** `vowel_counter.py` unused, utils test markers
  wrong.

## Considerations

- Layer 1 already has established packages (`thread/`, `graph/`, `lifecycle/`)
  that serve as natural homes for extracted domain types. Creating a new
  top-level `domain/` package would introduce a competing organizational concept
  with unclear boundaries. Extending existing packages is preferred.
- The snapshot Pydantic models (`ThreadStateSnapshot`, `MessageSnapshot`, etc.)
  are wire-format types for the reconnection protocol. They are constructed by
  `control/` and consumed by `api/routes/thread_state.py`. Moving them to
  Layer 1 would give Layer 1 a Pydantic-heavy API contract concern. Moving
  them to a shared location would change the API layer's internal structure.
  The pragmatic choice is to fix the clear violations (enum imports, `PlanEntry`)
  and accept the snapshot coupling as documented debt.
- `lifecycle/reconciliation.py` (Layer 1.5) already defines private subset
  enums (`_ThreadStatus`, `_RepairStatus`, `_ControlActionType`) to avoid
  importing from `database/crud.py`. Once enums move to Layer 1, these local
  copies become unnecessary.
- `control/projection.py` has 3 dataclasses and 3 pure functions (no `api/`
  type dependencies) that move directly to Layer 1. The remaining 7 functions
  construct `api/schemas` Pydantic models — D-12 dependency-inverts these by
  introducing Layer 1 dataclass equivalents.
- The `database/__init__.py` facade pattern means splitting `crud.py` is
  invisible to external consumers — the public import path remains stable.
- `_PLAN_APPROVAL_PAUSE_CAUSES` is duplicated between `event_handlers.py` and
  `projection.py`. Extraction to a shared Layer 1 location eliminates the
  duplication.

## Constraints

- Test baseline: `pytest -m core` >= 425, `pytest -m middleware` >= 616, total
  >= 1,041. Each phase must preserve a green suite.
- No backwards-compat re-export shims. Old import paths break loudly.
- Modules over 1,000 lines must be split.
- No mocks, stubs, fakes, patches, skips.
- Merge commits only.
- Scope boundary: `control/`, `database/`, `utils/`, `thread/` (receiving
  extracted types), `lifecycle/` (dropping local enum copies),
  `api/routes/thread_state.py` (data conversion adapter only). Does NOT touch
  `api/routes/` handler orchestration logic, Layer 3 infra config, or
  `providers/`.

## Implementation

Twelve decisions organized into 6 phases:

**D-01: Extract domain enums to `thread/enums.py`.**

Create `thread/enums.py` with the 6 domain enums (`ThreadStatus`,
`RepairStatus`, `ControlActionType`, `ControlActionResultStatus`,
`PermissionRequestStatus`, `ApprovalStatus`) and `InvalidTransitionError`.
Update all 16+ consumer files to import from `thread.enums`. Remove definitions
from `database/crud.py`. Update `database/__init__.py` to re-export from
`thread.enums`.

**Rationale**: These are domain concepts (lifecycle states, permission states,
action types). Data access layer should consume them, not define them.

---

**D-02: Extract `_VALID_TRANSITIONS` to `thread/transitions.py`.**

Move the state machine table and the `validate_transition()` logic to
`thread/transitions.py`. This module imports only from `thread/enums.py` —
pure Layer 1. `database/crud.py`'s `update_thread_status()` calls
`validate_transition()` instead of inlining the check.

**Rationale**: The thread lifecycle state machine is a domain rule, not data
access. Co-locating it with the enums it governs makes the thread package
the single authority on thread lifecycle.

---

**D-03: Fix enum imports in `control/snapshot.py` and `control/projection.py`.**

Change both modules to import domain enums from `graph.enums` (their canonical
Layer 1 source) instead of from `api/schemas/enums` (which re-exports them).
This eliminates 5 of the upward `api/` dependencies.

**Rationale**: The re-exports in `api/schemas/enums` exist for API backwards
compatibility. Infrastructure services should import from the canonical source.

---

**D-04: Move `PlanEntry` to `thread/models.py` as a dataclass.**

`PlanEntry` is a domain concept (execution plan entry) that currently lives in
`api/schemas/events.py` as a Pydantic `BaseModel`. Move it to
`thread/models.py` as a `dataclass` alongside the existing `PlanStep` model.
`api/schemas/events.py` re-imports from the new canonical location and wraps
it in a Pydantic schema if needed for wire serialization. Update
`control/snapshot.py` to import from `thread.models`.

**Rationale**: `PlanEntry` is consumed by `control/snapshot.py` for state
enrichment — a domain operation. Converting to dataclass keeps Layer 1 free of
Pydantic `BaseModel` in the `thread/` package (which currently uses only
dataclasses). The API layer can adapt the dataclass to Pydantic at the wire
boundary.

---

**D-05: Extract pure domain logic from `control/projection.py` to
`thread/snapshots.py` (scoped to Layer-1-safe functions only).**

Create `thread/snapshots.py` containing:

- 3 dataclasses: `ProjectedInterrupt`, `CheckpointProjection`,
  `ExecutionStateProjection`
- 3 pure functions with no `api/` type dependencies:
  `project_checkpoint_tuple`, `_parse_checkpoint_created_at`, `_load_json_list`
- Shared constant: `PLAN_APPROVAL_PAUSE_CAUSES`

The following functions construct Pydantic models from `api/schemas/snapshots`
(`_PermissionSnapshot`, `_PermissionOptionSnapshot`, `ExecutionTaskSnapshot`,
`ThreadStateSnapshot`) and therefore **stay in `control/projection.py`**:
`_permission_snapshot_from_model`, `_permission_snapshot_from_interrupt`,
`_coerce_permission_kind`, `apply_checkpoint_projection`,
`project_execution_state_model`, `apply_execution_state_projection`,
`enrich_snapshot_from_durable_state`, `enrich_snapshot_from_execution_state`.

This reduces `control/projection.py` from 491 to ~380 lines and moves the core
checkpoint normalization logic to Layer 1, while accepting that snapshot
assembly (which constructs wire-format Pydantic types) remains in infrastructure.

**Rationale**: Only functions with zero `api/` type dependencies can move to
Layer 1. Moving the dataclasses and checkpoint projection alone is valuable —
it makes the core normalization logic independently testable and establishes
the Layer 1 authority over checkpoint structure. The remaining functions stay
in `control/` because they construct API wire-format types — this is documented
architectural debt that can be resolved later via dependency inversion (return
plain dataclasses, let API layer adapt to Pydantic).

---

**D-06: Extract pure domain logic from `control/snapshot.py`.**

Move `finalize_snapshot_replay_status` to `thread/snapshots.py` — it is pure
classification logic with one enum dependency (`ThreadStatus`, now in
`thread/enums.py`).

Extract the following named pure functions from `enrich_snapshot_from_state`
into `thread/snapshots.py`:

- `classify_message_role(msg) -> str` — HumanMessage/AIMessage/ToolMessage
  discrimination (depends on `langchain_core.messages`, allowed in Layer 1)
- `extract_message_timestamp(msg) -> datetime | None` — response metadata
  timestamp parsing
- `derive_message_id(role, content, stored_id) -> str` — deterministic hash
  fallback for message deduplication
- `normalize_plan_entries(raw: list) -> list` — dict-to-dataclass coercion for
  plan entries (uses `PlanEntry` from D-04)
- `normalize_artifacts(raw: list) -> list` — dict-to-dataclass coercion for
  artifact references

Functions that construct `api/schemas/snapshots` Pydantic models
(`MessageSnapshot`, `ToolCallSnapshot`, `_AgentSnapshot`) **stay in
`control/snapshot.py`**. `enrich_snapshot_from_state` becomes a thinner
orchestrator that calls the Layer 1 pure functions and handles aggregator
state access + Pydantic model construction.

**Rationale**: Decomposing the 150-line mixed function into named pure
functions + thin infra orchestrator improves testability and enforces the
boundary. Only functions with zero `api/` dependencies move.

---

**D-07: Extract domain predicates from `control/event_handlers.py`.**

Move to `thread/snapshots.py` (or `thread/constants.py` if needed):

- `PLAN_APPROVAL_PAUSE_CAUSES` (deduplicate — already in D-05)
- Terminal status mapping constant
- Domain predicates: `is_terminal_event`, `is_permission_event`,
  `is_progress_event`, `classify_permission_pause_reason`

`control/event_handlers.py` retains all 4 handler functions and `relay_event`
— these are infrastructure orchestration (database writes, session management,
aggregator GC).

**Rationale**: Only ~20% of this module is domain logic. Extract the constants
and predicates; keep the orchestration in infrastructure.

---

**D-08: Split `crud.py` into domain-focused modules.**

After D-01 removes enums, split the remaining functions:

- `database/crud.py` (~250L): `save_model`, `_utcnow`, `_UnsetType`/`_UNSET`,
  coercion helpers. Imports enums from `thread/enums.py`.
- `database/crud_threads.py` (~300L): thread CRUD, `update_thread_status` (now
  calls `thread.transitions.validate_transition`), `set_thread_repair_state`,
  `set_thread_approval_state`, execution state, metadata.
- `database/crud_permissions.py` (~300L): permission request lifecycle +
  control action journal.
- `database/crud_artifacts.py` (~150L): artifacts, permission logs, cost
  tracking.

Update `database/__init__.py` facade to import from new modules. External
consumers continue using `from vaultspec_a2a.database import create_thread`.

**Rationale**: 976 lines covering 11 domains. Business-logic grouping (4
modules) balances cohesion with navigability. Thread + repair + approval are
tightly coupled. Permissions + control actions are tightly coupled. Artifacts +
logs + cost are loosely coupled append-only operations.

---

**D-09: Fix `utils/` layer inversions.**

Refactor `utils/logging.py` and `utils/trace.py` to accept settings as
function parameters instead of importing `control.config.settings` at runtime.
Callers pass the settings object when invoking `setup_logging()` and
`print_trace_summary()`.

Move `AgentState` from `utils/enums.py` to the appropriate Layer 1 module
(likely `graph/enums.py` where related lifecycle states live).

**Rationale**: Utils is a leaf layer — it should not import from infrastructure
services. Parameter injection is the simplest fix.

---

**D-10: Clean up dead code and test markers.**

Delete `utils/vowel_counter.py` (zero imports). Change
`utils/tests/conftest.py` marker from `middleware` to `core` — these are pure
enum/utility tests with no infrastructure dependencies.

**Rationale**: Dead code and incorrect markers are maintenance noise.

---

**D-11: Update `lifecycle/reconciliation.py`.**

Drop the 3 private subset enums (`_ThreadStatus`, `_RepairStatus`,
`_ControlActionType`) and import from `thread/enums.py`. These local copies
were a workaround for the Layer 1 → Layer 2 import barrier that D-01 removes.

**Rationale**: With enums in Layer 1, the workaround is unnecessary.

---

**D-12: Dependency-invert snapshot types — eliminate `control/` → `api/`
coupling.**

Define plain dataclasses in `thread/snapshots.py` that mirror the snapshot
Pydantic model shapes:

- `ThreadStateData` (mirrors `ThreadStateSnapshot`)
- `MessageData` (mirrors `MessageSnapshot`)
- `ToolCallData` (mirrors `ToolCallSnapshot`)
- `ArtifactData` (mirrors `ArtifactSnapshot`)
- `PermissionData` (mirrors `_PermissionSnapshot`)
- `PermissionOptionData` (mirrors `_PermissionOptionSnapshot`)
- `AgentData` (mirrors `_AgentSnapshot`)
- `ExecutionTaskData` (mirrors `ExecutionTaskSnapshot`)

Refactor `control/projection.py` and `control/snapshot.py` to construct and
return these dataclasses instead of Pydantic models. Both modules drop all
imports from `api/schemas/snapshots` — eliminating the upward dependency
entirely.

Add a thin adapter in `api/routes/thread_state.py` (~30-50 lines) that
converts the dataclasses to Pydantic models for wire serialization. If field
names align (which they should by design), conversion is
`ThreadStateSnapshot(**dataclasses.asdict(data))` or `model_validate()`.

The scope expansion to `api/routes/thread_state.py` is limited to data
conversion only — no handler orchestration logic changes.

**Rationale**: This eliminates the last `control/` → `api/` boundary violation
completely, rather than carrying it as documented debt. The context and
dependency map are fully loaded from D-03 through D-06; deferring means
rediscovering this context in a future PR. The blast radius is contained:
~8 dataclass definitions, mechanical constructor swaps in 2 control modules,
and a ~40-line adapter in one route handler.

## Phase Order

| Phase | Decisions | Prerequisite | Packages touched |
|-------|-----------|-------------|------------------|
| 1 | D-01, D-02, D-11 | none | `thread/`, `database/`, `lifecycle/` |
| 2 | D-03, D-04 | D-01 | `control/`, `api/schemas/`, `thread/` |
| 3 | D-05, D-06, D-07, D-12 | D-01, D-03, D-04 | `thread/`, `control/`, `api/routes/thread_state.py` |
| 4 | D-08 | D-01 | `database/` |
| 5 | D-09, D-10 | none (parallel with 1-4) | `utils/`, `graph/` |
| 6 | Housekeeping | all above | README, `control/__init__.py` |

Phases 1 and 5 can run in parallel. Phase 2 requires Phase 1 (enum locations
must be settled). Phase 3 requires Phase 2 (import paths must be fixed) and
includes D-12 which eliminates the remaining `control/` → `api/` coupling.
Phase 4 requires Phase 1 only (enum extraction). Phase 6 is final validation.

## Rationale

This ADR extends the layer isolation roadmap (PRs #2, #3, #4) to infrastructure
services. The core principle is the same: domain types and rules belong in
Layer 1; infrastructure services are thin adapters that coordinate I/O and
delegate to Layer 1 for decisions.

Extending existing Layer 1 packages (`thread/`, `graph/`) rather than creating
a new `domain/` package maintains the established architecture. The `thread/`
package naturally owns thread lifecycle enums, state machine, and snapshot
projection logic. The `graph/` package already owns `AgentLifecycleState` and
related domain enums.

D-12 completes the boundary fix by dependency-inverting the snapshot types.
`control/` modules return plain dataclasses defined in Layer 1
(`thread/snapshots.py`); `api/routes/thread_state.py` converts them to
Pydantic for wire serialization. This eliminates all `control/` → `api/`
imports — zero documented debt remains.

## Consequences

- `thread/` grows from ~670 lines to ~1,100 lines with 3 new modules
  (`enums.py`, `transitions.py`, `snapshots.py`). Each module is focused and
  under 300 lines.
- `control/projection.py` shrinks from 491 to ~300 lines. The 3 dataclasses,
  `project_checkpoint_tuple`, and shared constant move to Layer 1. D-12
  converts all remaining functions to return Layer 1 dataclasses instead of
  Pydantic models — eliminating all `api/schemas` imports.
- `control/snapshot.py` shrinks from 293 to ~180 lines. Pure classification
  and normalization functions move to Layer 1. D-12 converts the remaining
  functions to return Layer 1 dataclasses.
- `api/routes/thread_state.py` gains ~40 lines of dataclass-to-Pydantic
  adapter code.
- `control/event_handlers.py` shrinks modestly — ~50 lines of constants and
  predicates extract.
- `crud.py` splits into 4 files totaling ~1,000 lines (slight growth from
  added imports/docstrings).
- `lifecycle/reconciliation.py` drops 22 lines of local enum definitions.
- `utils/logging.py` and `utils/trace.py`: the `settings_override` parameter
  already exists on `setup_logging()`; the fix is to remove the runtime
  `from ..control.config import settings` fallback and require callers to
  pass settings explicitly. 4 call sites in `providers/probes/*.py` to update.
  `print_trace_summary()` needs the same refactor.
- `control/` has zero imports from `api/` after D-12 — no documented debt.
- Test suite must remain at >= 1,041 passed after every phase.
- 5 test files import directly from `database.crud` — the `database/__init__`
  facade must re-export all symbols comprehensively after the split.

## Validation Criteria

After all phases:

- Zero `control/` imports from `api/` (enums use canonical `graph.enums` or
  `thread.enums`; snapshot types use `thread/snapshots.py` dataclasses)
- `PlanEntry` defined in `thread/models.py`, not `api/schemas/events.py`
- Domain enums defined in `thread/enums.py`, not `database/crud.py`
- `_VALID_TRANSITIONS` in `thread/transitions.py`, not `database/crud.py`
- `utils/` has zero imports from `control/`
- No file over 1,000 lines
- `utils/vowel_counter.py` deleted
- `utils/tests/` marked as `core`
- `lifecycle/reconciliation.py` imports from `thread/enums.py`
- `pytest -m core` >= 425 passed
- `pytest -m middleware` >= 616 passed
- Full suite >= 1,041 passed
