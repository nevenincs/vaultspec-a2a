---
tags:
  - '#audit'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
---

# `entry-point-layer` audit: `wave-1-2-code-review`

Consolidated code review of Phases 0-5 (Waves 1+2). Each phase reviewed by
an independent agent against the ADR and plan.

---

## Overall Verdict: ALL 6 PHASES APPROVED

| Phase | Decision | Verdict | Critical | High | Medium | Low |
|-------|----------|---------|----------|------|--------|-----|
| 0 | D-01: IPC to `ipc/` | APPROVED | 0 | 0 | 0 | 0 |
| 1 | D-02: Infrastructure to `control/` | APPROVED | 0 | 0 | 0 | 1 |
| 2 | D-03: Dispatch consolidation | APPROVED | 0 | 0 | 0 | 2 |
| 3 | D-04: Projection to `control/` | APPROVED | 0 | 0 | 0 | 1 |
| 4 | D-05+R-01: Event handlers + noqa | APPROVED | 0 | 0 | 0 | 0 |
| 5 | D-06: Health consolidation | APPROVED | 0 | 0 | 0 | 0 |
| **Total** | | **ALL PASS** | **0** | **0** | **0** | **4** |

---

## Phase 0 (D-01): IPC Types to `ipc/`

**Verdict: APPROVED — 10/10 checks pass**

- `ipc/__init__.py`, `ipc/schemas.py`, `ipc/serializers.py` created
- `api/schemas/internal.py` DELETED, no re-export shim
- `HeartbeatMessage` and `WorkerEventEnvelope` dead code not migrated
- `DispatchRequest.recursion_limit` default factory preserved
- 6 IPC re-exports removed from `api/schemas/__init__.py`
- All consumer imports rewired: `worker/executor.py`, `worker/app.py`,
  `api/app.py`, `api/endpoints.py`, `api/internal.py`
- Test files updated: `worker/tests/test_app.py`, `worker/tests/test_executor.py`
- Zero remaining imports from `api.schemas.internal` across codebase
- Layer boundary: `ipc/` imports only `control.config` (L2 IS, allowed)
- No circular dependencies

**Issues: None**

---

## Phase 1 (D-02): Infrastructure Classes to `control/`

**Verdict: APPROVED — all checks pass, 1 LOW (deferred)**

- `control/circuit_breaker.py`: `WorkerCircuitBreaker` extracted
  - `pre_dispatch()` returns `bool`, NOT HTTPException
  - `rejection_detail` property provides error message for callers
  - Zero FastAPI imports in module
- `control/worker_management.py`: `LazyWorkerSpawner`, `WorkerWatchdog`,
  8 helper functions extracted (~480 lines)
  - `WorkerState` dataclass with all 9 attributes (clean, no FastAPI deps)
  - Watchdog writes to `WorkerState`, NOT `app.state`
  - `asyncio.Lock` double-check pattern preserved in spawner
- `api/app.py` dropped from 1,507 to 880 lines
- All callers check bool return and raise HTTPException themselves
- Test imports updated: `conftest.py`, `test_app.py`, `test_server.py`
- `control/__init__.py` docstring reflects dual nature (runtime + dev-tooling)

**Issues:**
- **LOW**: `_trace_headers()` duplication remains (deferred to Phase 6/R-02)

---

## Phase 2 (D-03): Dispatch Consolidation

**Verdict: APPROVED — all ADR criteria met, 2 LOW**

- `control/dispatch.py` created (~145 lines)
  - `dispatch_to_worker()`: protocol-agnostic, no FastAPI imports
  - 3 domain error types: `WorkerCircuitOpenError`, `WorkerAtCapacityError`,
    `WorkerUnreachableError`
  - `bypass_circuit_breaker` flag for cancel endpoints
- All 7 dispatch sites consolidated:
  1. `create_thread_endpoint` — CB, 429→FAILED+503
  2. `send_message_endpoint` — CB, 429→503
  3. `respond_to_permission_endpoint` — CB, silent failure
  4. `cancel_thread_endpoint` — bypass CB
  5. `_dispatch_message` WS — CB, failure→broadcast
  6. `_dispatch_control` WS — bypass CB, now uses `DispatchRequest`
  7. `_redispatch_reconciling` — loop with error handling
- Zero remaining inline `worker_client.post("/dispatch")` calls
- Post-dispatch policy stays in callers (status transitions, error responses)
- Cancel bypass working correctly (PROD-066)

**Issues:**
- **LOW**: Inline `worker_last_heartbeat_ts` updates in `app.py` at 3 sites
  instead of using `_mark_worker_connected()` helper (behavior correct, style)
- **LOW**: Only 429 explicitly handled as domain error; other status codes
  pass through (by design per ADR — callers decide policy)

---

## Phase 3 (D-04): Projection and Snapshot to `control/`

**Verdict: APPROVED — 9 critical checks pass, 1 LOW**

- `api/projection.py` DELETED, no re-export shim
- `control/projection.py` contains ALL original functions: `ProjectedInterrupt`,
  `CheckpointProjection`, `ExecutionStateProjection`, `project_checkpoint_tuple`,
  `apply_checkpoint_projection`, `enrich_snapshot_*`, and all helpers
- `control/snapshot.py` created (~286 lines): `enrich_snapshot_from_state`,
  `MinimalState`, `load_checkpoint_history_depth`,
  `finalize_snapshot_replay_status`
- `endpoints.py` dropped from 1,883 to 1,624 lines (-259)
- Layer boundary correct: `control/projection.py` imports from `database.crud`
  and `api.schemas.*` (L2 IS, allowed). NOT placed in `thread/` (Layer 1)
- Test file imports updated in `api/tests/test_projection.py`
- No circular dependencies

**Issues:**
- **LOW**: Functions dropped leading underscores when becoming public module
  exports. Acceptable — they are now public API in `control/`.

---

## Phase 4 (D-05 + R-01): Event Handlers + noqa Fix

**Verdict: APPROVED — all checks pass, 0 issues**

- `control/event_handlers.py` created (~472 lines)
  - 4 handlers extracted: `_handle_terminal_event`,
    `_handle_permission_event`, `_handle_progress_event`,
    `_handle_execution_state_event`
  - `relay_event()` consolidates 3× duplicated relay sequence
  - Supporting constants: `_PLAN_APPROVAL_PAUSE_CAUSES`, `_TERMINAL_STATUS_MAP`
- Zero FastAPI imports in module (pure business logic)
- `internal.py` dropped from 812 to 369 lines (-443, 56% reduction)
- R-01: Both `# noqa: B904` comments fixed with `raise ... from e`
- Zero `# noqa` comments remain in `internal.py`
- All 3 call sites use `relay_event()`: `_relay_worker_event`,
  `receive_worker_event`, `receive_worker_event_batch`
- Subtle relay differences handled correctly: early-return for
  `execution_state_projection` delegated to callers per docstring

**Issues: None**

---

## Phase 5 (D-06): Health Consolidation

**Verdict: APPROVED — all checks pass, 0 issues**

- `control/health.py` created (~170 lines)
  - `assemble_health_status()`: single source of truth for shared health data
  - `build_sqlite_fallback_diagnostics()` moved from `app.py`
  - Zero FastAPI imports (dependencies injected via `app_state` parameter)
- Both health endpoints call `assemble_health_status()`:
  - `/api/health` (`endpoints.py`): adds granular per-subsystem checks
  - `/health` (`app.py`): adds `ready`, `service`, `production_certifying`
- All shared fields consolidated: worker connected, CB state, spawner state,
  restart metadata, repair summary, SQLite diagnostics
- Defensive null-handling with `getattr(app_state, "key", default)` pattern
- No remaining duplicated health assembly logic

**Issues: None**

---

## Cross-Phase Observations

### Line Count Progress

| File | Start | After W1+2 | Reduction |
|------|-------|-----------|-----------|
| `api/endpoints.py` | 1,883 | 1,517 | -366 (19%) |
| `api/app.py` | 1,507 | 753 | -754 (50%) |
| `api/internal.py` | 812 | 369 | -443 (55%) |
| `worker/executor.py` | 983 | 983 | Phase 8 |
| `cli/_team.py` | 825 | 825 | Phase 9 |

### New Modules Created

| Module | Lines | Character |
|--------|-------|-----------|
| `ipc/schemas.py` | 86 | IPC contract types |
| `ipc/serializers.py` | 19 | Event serialization |
| `control/circuit_breaker.py` | 98 | Circuit breaker (protocol-free) |
| `control/worker_management.py` | 480 | Spawner, watchdog, WorkerState |
| `control/dispatch.py` | 145 | Consolidated dispatch + domain errors |
| `control/projection.py` | 491 | Checkpoint/state projection |
| `control/snapshot.py` | 286 | Snapshot assembly |
| `control/event_handlers.py` | 472 | Event handlers + relay |
| `control/health.py` | 170 | Health assembly |

### Remaining Work (Phases 6-10)

- **Phase 6** (D-07+R-02): Split `endpoints.py` into `routes/`, dedup `_trace_headers`
- **Phase 7** (D-08): Slim `app.py` to <500 lines
- **Phase 8** (D-09): Split `executor.py` into 3 modules
- **Phase 9** (D-10): Extract `cli/_renderers.py`
- **Phase 10** (D-11): Fix `cli/_agent.py` filesystem bypass

### Test Baseline

- Core gate: **425 passed** (preserved)
- Full suite: **1,026+ passed** (pre-existing failures in `test_factory.py` unchanged)

---
---

## Wave 3-5 Review: Phases 6, 7, 8, 9, 10

### Overall Verdict: ALL 5 PHASES APPROVED

| Phase | Decision | Verdict | Critical | High | Medium | Low |
|-------|----------|---------|----------|------|--------|-----|
| 6 | D-07+R-02: Route split + trace dedup | APPROVED | 0 | 0 | 0 | 0 |
| 7 | D-08: Slim app.py | APPROVED | 0 | 0 | 0 | 0 |
| 8 | D-09: Executor split | APPROVED | 0 | 0 | 0 | 0 |
| 9 | D-10: CLI renderers | APPROVED | 0 | 0 | 0 | 0 |
| 10 | D-11: Agent preset fix | APPROVED | 0 | 0 | 0 | 0 |
| **Total** | | **ALL PASS** | **0** | **0** | **1** | **0** |

---

## Phase 6 (D-07+R-02): Route Split + Trace Dedup

**Verdict: APPROVED**

- `endpoints.py` DELETED — no re-export shim
- 8 route modules created, all under 500 lines (largest: `threads.py` at 425)
- All 13 routes accounted for across route files
- `register_routes(app)` in `routes/__init__.py` preserves `/api` prefix
- `dependencies.py` (79 lines): all FastAPI DI providers extracted
- `_utils.py` (42 lines): `trace_headers()` consolidated (R-02), `mark_worker_connected()` shared
- `_process_metadata()` stays in `routes/threads.py` as route-local helper
- No business logic in route handlers — all delegated to `control/`
- 6 call sites import `trace_headers` from `_utils` (no duplication)

---

## Phase 7 (D-08): Slim app.py

**Verdict: APPROVED**

- `app.py` dropped from 751 to 312 lines (target: <500)
- Contains only: `create_app()`, `main()`, `_lifespan()`
- `middleware.py` (40 lines): `CacheControlMiddleware` extracted
- `ws_dispatch.py` (282 lines): WS dispatch handler factories
- `control/diagnostics.py` (150 lines): `classify_missing_ws_thread`,
  `mark_thread_failed`
  - Returns `MissingThreadClassification` dataclass (NOT WebSocket error)
  - Zero `api/` imports — clean layer boundary
- `_ws_mark_failed_and_broadcast` split: DB update in `control/diagnostics`,
  WS broadcast in `api/ws_dispatch.py`
- `redispatch_reconciling_threads()` extracted to `control/dispatch.py`

---

## Phase 8 (D-09): Executor Split

**Verdict: APPROVED**

- `executor.py`: 490 lines — `Executor` class, dispatch, concurrency gating
- `graph_lifecycle.py`: 317 lines — `GraphLifecycleManager`, graph cache,
  compilation, input construction
- `state_projection.py`: 297 lines — `StateProjector`, checkpoint
  inspection, state normalization, terminal events
- All 3 under 500 lines
- No shared mutable state between pieces — graph cache owned by lifecycle
  manager, aggregator owned by executor, bridge passed as constructor arg
- `__all__` defined in both new modules
- `Executor` delegates cleanly via `_graph_lifecycle` and `_state_projector`

---

## Phase 9 (D-10): CLI Renderers

**Verdict: APPROVED**

- `_renderers.py` (442 lines): `format_elapsed()`, 9 event renderers,
  `render_event()` dispatcher, `handle_permission_prompt()`,
  `render_status_display()`, `render_thread_list()`
- `_team.py` dropped from 825 to 493 lines
- `_team.py` retains only Click command definitions
- Rich/Click coupling stays in `_renderers.py` (acceptable — CLI layer)

---

## Phase 10 (D-11): Agent Preset Fix

**Verdict: APPROVED**

- `_agent.py` (74 lines): both commands route through `team.team_config`
- `discover_agent_preset_ids()` added to `team_config.py`
- Zero `Path(...) / "core" / "presets"` filesystem paths remain
- Old broken path to pre-Layer-1 `core/` directory eliminated

---

## Cross-Cutting Verification

- Zero imports from `api.endpoints` anywhere (module deleted)
- Zero imports from `api.schemas.internal` anywhere (module deleted)
- Zero `# noqa` comments in modified files
- `control/__init__.py` docstring current (runtime + dev-tooling)
- No entry point cross-imports: `worker/` ↛ `api/`, `cli/` ↛ `worker/`
- Core gate: **425 passed**

## One MEDIUM Finding

**`control/worker_management.py` at 557 lines** — marginally exceeds the
500-line target. Contains `LazyWorkerSpawner`, `WorkerWatchdog`,
`WorkerState`, and 8 helper functions. All tightly coupled process
supervision infrastructure. Splitting further would fragment a single
responsibility. Acceptable as infrastructure-tier code. Monitor if it
grows beyond 600 lines.

---

## Complete Decomposition Summary (All 11 Phases)

### ADR Validation Criteria — All 10 Met

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Every entry point file < 500 lines | PASS |
| 2 | Zero business logic in route handlers | PASS |
| 3 | No entry point cross-imports | PASS |
| 4 | Shared IPC types in neutral `ipc/` | PASS |
| 5 | `pytest -m core` stays at 425 | PASS |
| 6 | Full suite at 1,026+ | PASS |
| 7 | No re-export shims | PASS |
| 8 | No `# noqa` comments | PASS |
| 9 | `cli/_agent.py` through domain service | PASS |
| 10 | `executor.py` split into 3 modules | PASS |

### Total Issues Across All 11 Phases

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 (`worker_management.py` at 557 lines) |
| LOW | 4 (all acceptable/deferred) |
