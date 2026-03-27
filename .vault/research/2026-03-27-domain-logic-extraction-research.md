---
tags:
  - '#research'
  - '#domain-logic'
date: '2026-03-27'
related:
  - '[[2026-03-24-core-layer-boundary-audit]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

# `domain-logic` research: layer 2b boundary violations and extraction targets

Research into the current state of layer boundary violations across `control/`,
`database/crud.py`, `utils/`, and `api/schemas/` to inform the Layer 2b domain
logic extraction (issue #8).

## Findings

### 1. `control/` imports from `api/` — boundary violation

Two modules in `control/` import from `api/schemas/`, violating the rule that
infrastructure services never import from entry points.

**`control/snapshot.py` (lines 12-27):** imports 11 types from `api/schemas/`:

- 4 domain enums re-exported via `api/schemas/enums`: `AgentLifecycleState`,
  `PermissionOptionKind`, `ToolCallStatus`, `ToolKind` — canonical source is
  `graph/enums.py` (Layer 1). Fix: import directly from `graph.enums`.
- 1 hybrid type from `api/schemas/events`: `PlanEntry` — domain concept used
  for state enrichment. Fix: move to `thread/models.py` alongside `PlanStep`.
- 6 snapshot Pydantic models from `api/schemas/snapshots`: `ArtifactSnapshot`,
  `MessageSnapshot`, `ThreadStateSnapshot`, `ToolCallSnapshot`,
  `_AgentSnapshot`, `_PermissionOptionSnapshot`, `_PermissionSnapshot` — these
  are wire-format types that `control/snapshot.py` constructs and returns.

**`control/projection.py` (lines 25-31):** imports 6 types from `api/schemas/`:

- 2 domain enums re-exported via `api/schemas/enums`: `PermissionOptionKind`,
  `PermissionType` — canonical source is `graph/enums.py`. Fix: import from
  `graph.enums`.
- 4 snapshot Pydantic models from `api/schemas/snapshots`:
  `ExecutionTaskSnapshot`, `ThreadStateSnapshot`, `_PermissionOptionSnapshot`,
  `_PermissionSnapshot`.

**Classification of snapshot types:** The 8 unique Pydantic snapshot models
(`MessageSnapshot`, `ToolCallSnapshot`, `ArtifactSnapshot`,
`_PermissionSnapshot`, `_PermissionOptionSnapshot`, `_AgentSnapshot`,
`ExecutionTaskSnapshot`, `ThreadStateSnapshot`) are wire-format types for the
reconnection protocol. `control/snapshot.py` and `control/projection.py`
construct these as their return values — consumed by
`api/routes/thread_state.py`. These are true API types that should stay in
`api/schemas/snapshots.py`.

**Problem:** If snapshot types stay in `api/schemas/`, then `control/` still
imports from `api/`, violating the boundary. Two options:

- **Option A:** Move snapshot types to a shared location (e.g.,
  `thread/snapshots.py`) — large blast radius, changes the API layer.
- **Option B:** Apply dependency inversion — `control/` modules define a
  Protocol or return plain dicts/dataclasses, and the API layer adapts them
  into Pydantic models.
- **Option C:** Accept the coupling as architectural debt, fix only the enum
  imports (which are the clear violations), and defer snapshot relocation. The
  snapshot types are consumed by exactly one route handler
  (`api/routes/thread_state.py`) and two control modules — a narrow surface.

### 2. Domain enums in `database/crud.py`

Six domain enums defined in `database/crud.py` (lines 31-101):

| Enum | Values | Consumers (files) |
|------|--------|-------------------|
| `ThreadStatus` | 10 | 16 files |
| `RepairStatus` | 7 | 10 files |
| `ControlActionType` | 10 | 8 files |
| `ControlActionResultStatus` | 5 | 6 files |
| `PermissionRequestStatus` | 6 | 4 files |
| `ApprovalStatus` | 4 | 4 files |

Plus `InvalidTransitionError` (line 341-342) and `_VALID_TRANSITIONS` state
machine (lines 345-413).

**Current export pattern:** Only `ThreadStatus` and `InvalidTransitionError`
are re-exported from `database/__init__.py`. Other enums are imported directly
from `database.crud` by consumers.

**Notable:** `lifecycle/reconciliation.py` (Layer 1.5) defines private subset
enums (`_ThreadStatus`, `_RepairStatus`, `_ControlActionType`) as narrow views
of the crud enums. This is a safe pattern — they're intentionally scoped
subsets for reconciliation decisions. Once the canonical enums move to Layer 1,
`lifecycle/reconciliation.py` can import from the canonical source and drop the
local copies.

**Consumer hotspots:** `control/event_handlers.py` imports all 6 enums plus
`InvalidTransitionError`. `api/routes/` modules import 4-5 enums each.

### 3. `_VALID_TRANSITIONS` state machine

Location: `database/crud.py:345-413`. Maps `ThreadStatus` to `frozenset` of
valid next states. Consumed only by `update_thread_status()` (line 433) and
database tests.

This is a domain rule — thread lifecycle state machine — not data access. It
belongs in Layer 1 alongside the `ThreadStatus` enum.

### 4. `crud.py` monolith structure (976 lines, 11 domains)

Function inventory by domain:

| Domain | Functions | Lines |
|--------|-----------|-------|
| Thread CRUD | 5 | ~95 |
| Thread status/lifecycle | 2 + state machine | ~100 |
| Thread repair state | 1 | ~35 |
| Thread approval state | 1 | ~30 |
| Execution state | 3 | ~90 |
| Thread metadata | 2 | ~20 |
| Control action journal | 6 | ~100 |
| Permission requests | 7 | ~155 |
| Artifacts | 3 | ~35 |
| Permission logs | 2 | ~30 |
| Cost tracking | 3 | ~40 |
| Utilities (save_model, coercions) | 8 | ~90 |
| Enums + exceptions | 7 | ~115 |

**Recommended split (Option B — business-logic grouping):**

- `crud.py` (~250L): enums, exceptions, utilities, `save_model`, coercion
  helpers
- `crud_threads.py` (~300L): thread CRUD + status + repair + approval +
  execution state + metadata + `_VALID_TRANSITIONS`
- `crud_permissions.py` (~300L): permission requests + control action journal
- `crud_artifacts.py` (~150L): artifacts + permission logs + cost tracking

Key dependencies: thread repair/approval tightly coupled to thread table.
Permission requests tightly coupled to control actions. Artifacts/logs/cost are
loosely coupled append-only operations.

The `database/__init__.py` facade shields all external consumers — the public
import path (`from vaultspec_a2a.database import create_thread`) remains stable.

### 5. Domain logic in `control/` — function-level classification

**`control/projection.py` (491L):** ~85% pure domain logic.

- 10 functions are pure transformations (no I/O): `project_checkpoint_tuple`,
  `apply_checkpoint_projection`, `project_execution_state_model`,
  `apply_execution_state_projection`, `_permission_snapshot_from_model`,
  `_permission_snapshot_from_interrupt`, `_coerce_permission_kind`,
  `_parse_checkpoint_created_at`, `_load_json_list`.
- 3 dataclasses are domain value objects: `ProjectedInterrupt`,
  `CheckpointProjection`, `ExecutionStateProjection`.
- 2 functions are infra adapters (async DB queries):
  `enrich_snapshot_from_durable_state`, `enrich_snapshot_from_execution_state`.
- Constant `_PLAN_APPROVAL_PAUSE_CAUSES` duplicated in `event_handlers.py`.

**`control/snapshot.py` (293L):** ~40% domain, 60% infra.

- `finalize_snapshot_replay_status` — pure classification logic (domain).
- `enrich_snapshot_from_state` — mixed: message classification logic (domain)
  + aggregator state access (infra). Contains extractable pure functions:
  message role classification, timestamp extraction, ID derivation, plan entry
  normalization, artifact normalization, tool call deduplication.
- `MinimalState` — infra adapter.
- `load_checkpoint_history_depth` — infra I/O.

**`control/event_handlers.py` (473L):** ~20% domain, 80% infra.

- `relay_event` — pure orchestrator (infra).
- 4 handler functions are heavily infra (database writes, session management).
- Extractable domain constants: `_TERMINAL_STATUS_MAP`,
  `_PLAN_APPROVAL_PAUSE_CAUSES`, permission type predicates.
- Extractable domain predicates: `is_terminal_event`, `is_permission_event`,
  `is_progress_event`, `classify_permission_pause_reason`.

**Consumers:** All three modules are consumed primarily by
`api/routes/thread_state.py` (projection + snapshot) and `api/internal.py`
(event_handlers). Tests in `api/tests/`.

### 6. `utils/` layer inversions

**Runtime imports from `control.config`:**

- `utils/logging.py:111` — `from ..control.config import settings as
  core_settings` inside `setup_logging()`. Accesses `log_level`, `no_color`,
  `ci`, `is_dev`.
- `utils/trace.py:42` — `from ..control.config import settings` inside
  `print_trace_summary()`. Accesses `langsmith_api_key`,
  `langsmith_tracing`, `langsmith_project`, `langsmith_endpoint`.

Fix: Accept settings as function parameters instead of importing at call site.

**Enum classification in `utils/enums.py`:**

| Enum | Classification |
|------|----------------|
| `AgentState` | Domain (process lifecycle: init/ready/running/error/done) |
| `LogLevel` | Infrastructure |
| `Environment` | Infrastructure |
| `AcpRequestId` | Infrastructure |

`AgentState` consumers: only `utils/tests/test_enums.py` and
`utils/__init__.py` re-export. Minimal blast radius if moved to Layer 1.

**Dead code:**

- `utils/vowel_counter.py` (11L) — zero imports anywhere in source code.
- `utils/asyncio_compat.py` (15L) — NOT dead. Imported by `worker/app.py:39`
  and `api/app.py:53`. No-op stub with rationale docstring.

**Test markers:** `utils/tests/conftest.py` marks all utils tests as
`middleware`. Since `AgentState`, `LogLevel`, `Environment` are pure enums
with no infra deps, these tests should be `core`.

### 7. `api/schemas/` type classification

**42 types across 6 files.** Classification:

- **Pure API types (38):** All types in `base.py`, `commands.py`, `rest.py`,
  all event classes in `events.py`, all snapshot models in `snapshots.py`,
  and 5 API-only enums in `enums.py` (`ServerEventType`, `ClientCommandType`,
  `AgentControlAction`, `PlanEntryStatus`, `PlanEntryPriority`).
- **Domain re-exports (5):** `AgentLifecycleState`, `ToolKind`,
  `ToolCallStatus`, `PermissionOptionKind`, `PermissionType` — re-exported
  from `graph/enums.py` for backwards compatibility. Correct pattern.
- **Hybrid/domain candidate (1):** `PlanEntry` — used by
  `control/snapshot.py` for state enrichment. Similar to `PlanStep` in
  `thread/models.py`. Should move to Layer 1.

### 8. Revised scope assessment

The handover document's Phase 3 (dependency-invert domain logic in `control/`)
is the highest-risk phase. The research reveals:

- `projection.py` has the cleanest extraction path — 85% pure domain, 10 pure
  functions + 3 dataclasses can move wholesale.
- `event_handlers.py` has the lowest domain ratio — only constants and
  predicates extract; the handlers themselves are infrastructure orchestration.
- `snapshot.py` requires careful decomposition — `enrich_snapshot_from_state`
  is a 150-line function with interleaved domain and infra concerns.

The handover suggests creating a new `domain/` package. An alternative is to
extend existing Layer 1 packages: `thread/` for snapshot/projection types and
lifecycle enums, `lifecycle/` for transition rules.

**Recommendation:** Extend existing Layer 1 packages rather than create a new
top-level `domain/` package. This aligns with the established architecture
(`thread/`, `graph/`, `lifecycle/` already serve this role) and avoids
introducing a new organizational concept.

Proposed Layer 1 targets:

- `thread/enums.py` (new): 6 domain enums + `InvalidTransitionError`
- `thread/transitions.py` (new): `_VALID_TRANSITIONS` + transition validation
- `thread/snapshots.py` (new): `PlanEntry`, projection dataclasses,
  pure projection/snapshot functions
- `lifecycle/reconciliation.py` (existing): drop private enum subsets, import
  from `thread/enums.py`
