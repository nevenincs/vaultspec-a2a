# Layer 2b Domain Logic Extraction — Handover

**GitHub Issue:** wgergely/vaultspec-a2a#8
**Date:** 2026-03-27
**Prerequisite:** PRs #2, #3, #4 all merged to `main`.

## History

This is the fourth PR in the layer isolation roadmap:

| PR | Layer | What it did | Status |
|----|-------|-------------|--------|
| #2 | Control layer | CLI/Justfile separation, `control/` package, `doctor`, `verify`, `hooks` | MERGED 2026-03-23 |
| #3 | Layer 1 (core) | Decomposed monolithic `core/` into `thread/`, `context/`, `team/`, `graph/`, `streaming/`, `lifecycle/`. 425 isolated tests. | MERGED 2026-03-24 |
| #4 | Layer 2a (entry points) | Split `endpoints.py` (1,883L) into 8 route modules. Split `executor.py` into 3. Extracted `ipc/`, `control/` runtime modules. CLI renderers. | MERGED 2026-03-26 |
| #8 | **Layer 2b (this)** | Extract domain logic from infrastructure services back to Layer 1. Split `crud.py`. Fix boundary violations. | **NOT STARTED** |

The binding ADR is `docs/adrs/040-layer-boundary-enforcement.md`. The
living architecture document is `src/vaultspec_a2a/README.md`.

## What Layer 2a delivered

Layer 2a split the fat entry points into thin protocol adapters. Route
handlers in `api/routes/` now delegate to `control/` for dispatch,
projection, health, and event handling. The worker was split into
`executor.py`, `graph_lifecycle.py`, and `state_projection.py`. Shared
IPC types moved to `ipc/`. CLI renderers extracted to `_renderers.py`.

However, the Layer 2a PR intentionally deferred infrastructure service
cleanup. The 2026-03-27 boundary audit found that the extraction
created a new problem: `control/` modules now import from `api/schemas/`,
meaning infrastructure services depend on entry points — a layer
boundary violation.

## The problem: domain logic in infrastructure

### Boundary violation: `control/` imports from `api/`

Two modules in `control/` import types from `api/schemas/`, which is an
entry-point package. Infrastructure services must never import from
entry points.

```text
control/snapshot.py:12-27  → imports 11 types from api/schemas/
control/projection.py:25-31 → imports 4 types from api/schemas/
```

The root cause: `api/schemas/` defines domain types (enums, snapshot
models) that should live in a shared Layer 1 location. When
`endpoints.py` was split and logic moved to `control/`, the types
stayed in `api/schemas/`, creating an upward dependency.

### Misplaced domain logic in `control/` (1,257 lines)

Three modules contain business rules that belong in Layer 1:

| Module | Lines | What it does | Why it's misplaced |
|--------|-------|-------------|-------------------|
| `control/event_handlers.py` | 473 | Thread lifecycle state machine, permission status transitions, progress-based inference | Domain rules about state transitions |
| `control/projection.py` | 491 | Checkpoint projection, permission snapshot construction, freshness classification, approval inference | Business rules about state enrichment |
| `control/snapshot.py` | 293 | State enrichment, message/plan/artifact extraction, replay status classification | Docstring literally says "business logic extracted from endpoints" |

### Domain enums in `database/crud.py`

Six domain enums are defined in `database/crud.py` (lines 31-101)
instead of in Layer 1:

- `ThreadStatus` (10 values) — thread lifecycle states
- `RepairStatus` (7 values) — repair/readiness classification
- `ControlActionType` (10 values) — journaled control action types
- `ControlActionResultStatus` (5 values) — control action outcomes
- `PermissionRequestStatus` (6 values) — permission request lifecycle
- `ApprovalStatus` (4 values) — plan approval lifecycle

Additionally, `_VALID_TRANSITIONS` (lines 345-413) encodes the thread
state machine — a domain rule, not data access.

### `crud.py` is a monolith (977 lines, 11 domains)

One file handles: thread CRUD, thread status/lifecycle, thread repair
state, thread approval state, execution state, thread metadata, control
action journal, permission requests, artifacts, permission logs, and
cost tracking.

### `utils/` layer inversions

- `utils/logging.py` imports from `control.config` (line 111)
- `utils/trace.py` imports from `control.config` (line 42)
- `utils/enums.py` mixes domain enum (`AgentState`) with infra enums
- Dead code: `vowel_counter.py` (10L), `asyncio_compat.py` (15L, no-op)

### `control/` package incoherence (4,954 lines)

Three unrelated concerns share one package:

| Concern | Lines | Modules |
|---------|-------|---------|
| Production runtime | 1,917 | `config`, `circuit_breaker`, `diagnostics`, `dispatch`, `health`, `worker_management` |
| Dev-tooling | 1,780 | `db`, `doctor`, `hooks`, `verify` |
| Misplaced domain logic | 1,257 | `event_handlers`, `projection`, `snapshot` |

## Mandatory reading before starting

1. `docs/adrs/040-layer-boundary-enforcement.md` — Binding layer model
2. `src/vaultspec_a2a/README.md` — Living architecture doc (sections:
   Layer Boundary Rules, Boundary Audit Status, Dependency Graph)
3. `.vault/audit/2026-03-24-core-layer-boundary-audit.md` — Layer 1
   audit findings
4. `docs/core-layer/handover-layer2.md` — Layer 2a handover (completed)
   for methodology reference

## Rules (non-negotiable, learned from PRs #2-#4)

- **No backwards-compat shims.** When moving code, update all consumers.
  Old import paths break loudly.
- **No deferral.** If the plan says decompose a module, decompose it.
  Do not move it as-is and call it done.
- **Stay in scope.** This PR touches `control/`, `database/`, `utils/`,
  and `thread/` (receiving extracted types). It does NOT touch
  `api/routes/` handler logic, Layer 3 infra config, or `providers/`.
- **Modules over 1,000 lines must be split** into focused sub-modules.
- **No re-export shims.** One canonical import path per symbol.
- **Test for each phase.** Each phase must preserve a green test suite.
- **No mocks, stubs, fakes, patches, skips.** Real tests only.
- **Commit after every phase.** Push to the feature branch continuously.
- **Merge commits only.** Squash merge and rebase merge are disabled on
  this repo. Do not override.

## Work plan

### Phase 0: Baseline

Record the current test pass counts:

```bash
pytest -m core -q --tb=no
pytest -m middleware -q --tb=no
pytest -q --tb=no
```

Fix the 4 frozen dataclass test bugs (`test_frozen_immutability` in
`thread/tests/test_models.py` and `lifecycle/tests/test_reconciliation.py`)
before starting. These use `object.__setattr__()` which bypasses frozen
guards on `slots=True` dataclasses in Python 3.13. Switch to direct
attribute assignment.

### Phase 1: Extract domain enums from `database/crud.py` to Layer 1

Move the 6 domain enums and `InvalidTransitionError` to a new file
`thread/enums.py` (or extend `thread/errors.py`). Move
`_VALID_TRANSITIONS` table to `thread/lifecycle.py` or similar.

Update all consumers: `database/crud.py`, `control/event_handlers.py`,
`api/routes/*.py`, `api/schemas/enums.py`, `worker/*.py`.

Verification: `pytest -m core` passes. `grep` confirms enums no longer
defined in `database/`.

### Phase 2: Extract shared schema types from `api/schemas/`

The types that `control/snapshot.py` and `control/projection.py` import
from `api/schemas/` are domain types (snapshot models, enums). Move
them to a shared Layer 1 location — either extend existing Layer 1
modules or create a new `thread/snapshots.py`.

After this phase, `control/` must have zero imports from `api/`.

Verification: `grep -rn 'from.*api\.' src/vaultspec_a2a/control/
--include='*.py' | grep -v tests/ | grep -v __pycache__` returns zero.

### Phase 3: Dependency-invert domain logic in `control/`

Apply the Protocol pattern (like `ProviderFactoryProtocol` and
`TelemetryHook`) to the three domain-logic modules:

- `event_handlers.py` — extract the domain rules (state transitions,
  permission lifecycle) into Layer 1 functions/classes. Keep the
  infrastructure coordination (HTTP relay, database writes) in
  `control/`.
- `projection.py` — extract business rules (freshness classification,
  approval inference) to Layer 1. Keep checkpoint I/O in `control/`.
- `snapshot.py` — extract state enrichment logic to Layer 1. Keep
  database/checkpoint access in `control/`.

The goal: each `control/` module becomes a thin adapter that calls
Layer 1 domain functions and handles infrastructure I/O.

### Phase 4: Split `crud.py` by domain

Split the remaining `crud.py` (after enum extraction) into focused
modules:

- `database/thread_crud.py` — thread CRUD, status, repair, approval,
  metadata
- `database/permission_crud.py` — permission request lifecycle
- `database/control_journal.py` — control action CRUD
- `database/execution_state_crud.py` — execution state projection
- `database/cost_crud.py` — cost tracking + artifacts

Each file should be under 300 lines. Update `database/__init__.py` to
re-export the public API.

### Phase 5: Fix `utils/` layer inversions

- `logging.py` and `trace.py` import `Settings` from `control.config`.
  Refactor so config is passed in as arguments, not imported at module
  level.
- Move `AgentState` from `utils/enums.py` to the appropriate Layer 1
  module.
- Delete dead code: `vowel_counter.py`, `asyncio_compat.py`.
- Fix `utils/tests/conftest.py` marker from `middleware` to `core` +
  `unit`.

### Phase 6: Housekeeping

- Update `control/__init__.py` — add `hooks` to `__all__`, update
  docstring.
- Update stale lazy-import comment in `providers/__init__.py` (still
  references deleted `core/` package).
- Update `src/vaultspec_a2a/README.md` boundary audit status section.
- Verify no regressions: full test suite must match or exceed baseline.

## Test baseline targets

After all phases:

```text
pytest -m core        → ≥ 425 (all pass, frozen dataclass bugs fixed)
pytest -m middleware  → ≥ 616 (zero regressions)
pytest                → ≥ 1,041 (total)
```

New boundary validation:

```bash
# control/ must not import from api/ (zero matches expected)
grep -rn 'from.*api\.' src/vaultspec_a2a/control/ --include='*.py' \
  | grep -v tests/ | grep -v __pycache__

# Domain enums must not be defined in database/ (zero matches expected)
grep -rn 'class ThreadStatus\|class RepairStatus\|class ControlActionType' \
  src/vaultspec_a2a/database/ --include='*.py'

# utils/ must not import from control/ (zero matches expected)
grep -rn 'from.*control\.' src/vaultspec_a2a/utils/ --include='*.py' \
  | grep -v tests/ | grep -v __pycache__
```

## Scope boundary

This PR touches: `control/`, `database/`, `utils/`, `thread/`
(receiving extracted domain types), `lifecycle/` (receiving transition
rules).

This PR does NOT touch:

- `api/routes/` handler orchestration logic (future PR — handler
  extraction)
- Layer 3 infrastructure config (future PR — Docker password fix,
  compose consolidation)
- `providers/`, `telemetry/`, `workspace/` (already clean)
- `graph/`, `context/`, `team/`, `streaming/` (Layer 1, stable)

If you find issues outside this scope during work, note them in a
separate `.vault/research/` document. Do not fix them in this PR.

## After this PR

The remaining work in the layer isolation roadmap:

1. **Layer 2a handler extraction** — move duplicated orchestration logic
   from `api/routes/` handlers (idempotency, dispatch, state mutations)
   into a service layer. Five handlers are 100-256 lines of business
   logic each.
2. **Layer 3 infrastructure config** — fix hardcoded `POSTGRES_PASSWORD`
   in `docker-compose.prod.postgres.yml`, consolidate competing postgres
   overlays, parameterize Jaeger ports.
3. **Backend readiness tracks** — observability pivot (`#88` log/trace
   correlation, `#89` runtime authority ADR, `#87` verifier diagnostics,
   `#86` Docker provider certification).
