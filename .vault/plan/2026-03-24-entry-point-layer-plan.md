---
tags:
  - '#plan'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-24-api-module-research]]'
  - '[[2026-03-24-worker-cli-research]]'
  - '[[2026-03-24-cross-import-dependency-map-research]]'
  - '[[2026-03-24-entry-point-audit]]'
---

# `entry-point-layer` plan

Layer 2 entry point decomposition: thin adapters for `api/`, `worker/`, `cli/`.
Implements ADR decisions D-01 through D-11 plus review fixes R-01, R-02 across
11 phases in 5 waves. Each phase preserves the test baseline (992 passed, 425
core). No re-export shims. No `# noqa` band-aids carried forward.

## Proposed Changes

The ADR identifies that only 39% of `api/` is protocol translation, with 43%
business logic and 18% infrastructure incorrectly co-located. Three
cross-entry-point import violations exist where `worker/` imports from `api/`.
Two files exceed the 1,000-line ceiling (`api/endpoints.py` at 1,883 lines,
`api/app.py` at 1,507 lines). The dispatch-to-worker pattern is duplicated at
7 call sites. Two health endpoints overlap. Four event handlers in
`api/internal.py` perform DB writes and state machine transitions.

The plan extracts shared IPC types to a neutral `ipc/` package, moves
infrastructure classes to `control/`, consolidates dispatch and health logic,
splits `endpoints.py` into per-resource route modules, slims `app.py` to a
~200-line factory, splits `executor.py` into 3 focused modules, extracts CLI
renderers, and fixes `cli/_agent.py` filesystem bypass.

All review conditions are incorporated: D-04 targets `control/` (not
`thread/`) per CRIT-01, `api/schemas/__init__.py` IPC re-exports are removed
per CRIT-02, test files are enumerated per phase per CRIT-03, D-02 includes
a `WorkerState` dataclass per IMP-02, D-07 explicitly assigns the metadata
endpoint per IMP-03, D-03 scope is narrowed to common-core dispatch per
IMP-04, and `_classify_missing_ws_thread` targets `control/diagnostics.py`
per MIN-03.

## Tasks

### Wave 1 (parallel): Phases 0, 1, 3, 4

- `Phase 0` -- D-01: shared IPC types to `ipc/`
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase0-summary.md`

  1. Create `src/vaultspec_a2a/ipc/__init__.py` and `ipc/schemas.py`. Move
     `DispatchRequest`, `DispatchResponse`, `ExecutionStateProjectionPayload`,
     `ExecutionTaskProjectionPayload` from `api/schemas/internal.py`. Delete
     dead types `HeartbeatMessage` and `WorkerEventEnvelope`.
     - Name: create ipc package and migrate schema types
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase0-step1.md`
     - Executing agent: `vaultspec-high-executor`

  1. Create `ipc/serializers.py`. Move `sequenced_to_dict` from
     `api/event_adapter.py`. Update `api/event_adapter.py` to import from
     `ipc/serializers`.
     - Name: extract sequenced_to_dict serializer
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase0-step2.md`
     - Executing agent: `vaultspec-high-executor`

  1. Update all consumers to import from `ipc/`: `api/app.py`,
     `api/endpoints.py`, `api/internal.py`, `worker/app.py`,
     `worker/executor.py`. Remove the 6 IPC type re-exports from
     `api/schemas/__init__.py` (lines 54-59) and their `__all__` entries.
     Delete `api/schemas/internal.py`. No re-export shim.
     - Name: rewire imports and delete old module
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase0-step3.md`
     - Executing agent: `vaultspec-high-executor`

  1. Update test files: `worker/tests/test_app.py`,
     `worker/tests/test_executor.py`. Verify all imports resolve. Run
     `pytest -m core` (425 passed) and full suite (992 passed).
     - Name: fix test imports and verify baseline
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase0-step4.md`
     - Executing agent: `vaultspec-high-executor`

- `Phase 1` -- D-02: infrastructure classes to `control/`
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase1-summary.md`

  1. Create `control/circuit_breaker.py`. Move `WorkerCircuitBreaker` from
     `api/app.py`. Refactor `pre_dispatch()` to return a result instead of
     raising `HTTPException` -- let callers raise.
     - Name: extract circuit breaker with protocol decoupling
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase1-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Create `control/worker_management.py`. Move `LazyWorkerSpawner`,
     `WorkerWatchdog`, and all helper functions (`_spawn_worker`,
     `_shutdown_worker_process`, `_tcp_port_ready`, `_check_worker_health`,
     `_runtime_dir`, `_worker_stderr_log_path`, `_read_log_tail`,
     `_build_worker_restart_detail`). Introduce a `WorkerState` dataclass
     that the watchdog owns instead of writing directly to `app.state`.
     The caller (`_lifespan`) creates it, passes it to the watchdog, and
     stores it on `app.state` for route handlers to read.
     - Name: extract worker management with WorkerState dataclass
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase1-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Update `api/app.py` imports to reference `control/circuit_breaker` and
     `control/worker_management`. Update test file imports:
     `protocols/mcp/tests/test_server.py`, `api/tests/conftest.py`,
     `api/tests/test_app.py` (imports 8 symbols: `LazyWorkerSpawner`,
     `WorkerCircuitBreaker`, `WorkerWatchdog`, `_build_worker_restart_detail`,
     `_worker_stderr_log_path` — remaining symbols move in later phases).
     Run test suite.
     - Name: rewire imports and verify
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase1-step3.md`
     - Executing agent: `vaultspec-standard-executor`

- `Phase 3` -- D-04: projection and snapshot to `control/`
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase3-summary.md`

  1. Create `control/projection.py`. Move the entire contents of
     `api/projection.py` (`ProjectedInterrupt`, `CheckpointProjection`,
     `ExecutionStateProjection`, `project_checkpoint_tuple`,
     `apply_checkpoint_projection`, `enrich_snapshot_*` -- ~491 lines).
     Delete `api/projection.py`. No re-export shim.
     - Name: relocate projection module to control
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase3-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Create `control/snapshot.py`. Extract `_enrich_snapshot_from_state`,
     `_MinimalState`, `_load_checkpoint_history_depth`,
     `_finalize_snapshot_replay_status` from `api/endpoints.py` (~240 lines).
     - Name: extract snapshot business logic from endpoints
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase3-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Update imports in `api/endpoints.py` and `api/tests/test_projection.py`.
     Run test suite.
     - Name: rewire imports and verify
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase3-step3.md`
     - Executing agent: `vaultspec-standard-executor`

- `Phase 4` -- D-05 + R-01: event handlers to `control/`, noqa fix
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase4-summary.md`

  1. Create `control/event_handlers.py`. Move `_handle_terminal_event`,
     `_handle_permission_event`, `_handle_progress_event`,
     `_handle_execution_state_event` from `api/internal.py`. Consolidate
     the 3x duplicated relay orchestration sequence into a single
     `relay_event()` function (~400 lines total).
     - Name: extract event handlers and consolidate relay
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase4-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Fix the 2 `# noqa: B904` comments at `internal.py` lines 646 and 723
     (post-extraction line numbers will differ) by adding `from e` to the
     `raise` statements. No `noqa` comments carried forward.
     - Name: fix bare raise chain violations
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase4-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Update `api/internal.py` routes to call `relay_event()` from
     `control/event_handlers`. Verify `internal.py` drops to ~400 lines.
     Run test suite.
     - Name: rewire internal routes and verify
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase4-step3.md`
     - Executing agent: `vaultspec-standard-executor`

### Wave 2 (sequential, after Wave 1): Phases 2, 5

- `Phase 2` -- D-03: dispatch consolidation (requires D-01, D-02)
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase2-summary.md`

  1. Create `control/dispatch.py`. Implement `dispatch_to_worker()` handling
     the common core: `ensure_worker` -> `pre_dispatch` (optional via
     `bypass_circuit_breaker` flag) -> HTTP POST `/dispatch` ->
     `record_success/failure` -> error handling. Post-dispatch policy
     (status transitions, error responses, WS broadcasts) stays in callers.
     - Name: implement consolidated dispatch function
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase2-step1.md`
     - Executing agent: `vaultspec-high-executor`

  1. Refactor all 7 dispatch call sites to use `dispatch_to_worker()`:
     `create_thread_endpoint` (CB pre_dispatch, 429->503+FAILED),
     `send_message_endpoint` (CB pre_dispatch, 429->503, post-dispatch
     RUNNING), `respond_to_permission_endpoint` (CB pre_dispatch, silent
     failure flag), `cancel_thread_endpoint` (bypasses CB),
     `_dispatch_message` WS (CB pre_dispatch, failure->broadcast),
     `_dispatch_control` WS (bypasses CB, raw dict),
     `_redispatch_reconciling` background task (manual CB check, silent
     continue). Each caller retains its post-dispatch policy.
     - Name: refactor all dispatch sites to use consolidated function
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase2-step2.md`
     - Executing agent: `vaultspec-high-executor`

  1. Run test suite. Verify dispatch behavior is preserved for all 7 sites.
     - Name: verify dispatch consolidation
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase2-step3.md`
     - Executing agent: `vaultspec-high-executor`

- `Phase 5` -- D-06: health consolidation (requires D-02)
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase5-summary.md`

  1. Create `control/health.py`. Extract shared health assembly logic into
     `assemble_health_status()`. Includes DB probe, checkpoint check, worker
     probe, circuit breaker state, spawner state, restart metadata, repair
     summary, SQLite diagnostics. Move `_build_sqlite_fallback_diagnostics`
     from `api/app.py`.
     - Name: consolidate health assembly logic
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase5-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Refactor both `endpoints.py:health()` and `app.py:health_endpoint()` to
     call `assemble_health_status()`. Each route adds only its own unique
     fields. Run test suite.
     - Name: wire health routes to consolidated function
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase5-step2.md`
     - Executing agent: `vaultspec-standard-executor`

### Wave 3 (after Wave 2): Phase 6

- `Phase 6` -- D-07 + R-02: split endpoints.py into routes/, deduplicate trace headers
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase6-summary.md`

  1. Create `api/dependencies.py`. Move FastAPI dependency injection functions
     (`get_aggregator`, `get_checkpointer`, `get_worker_client`,
     `get_circuit_breaker`, `get_worker_spawner`, `get_services`) from
     `endpoints.py` (~60 lines).
     - Name: extract FastAPI dependencies
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase6-step1.md`
     - Executing agent: `vaultspec-high-executor`

  1. Create `api/_utils.py`. Consolidate the duplicated `_trace_headers()`
     from `endpoints.py:137-146` and `app.py:268-272` into a single
     definition. Also move `_mark_worker_connected()`. Both callers import
     from this shared utility.
     - Name: deduplicate trace headers (R-02)
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase6-step2.md`
     - Executing agent: `vaultspec-high-executor`

  1. Create `api/routes/` package with `__init__.py` containing a
     `register_routes(app)` helper. Create per-resource route modules:
     `health.py` (~30 lines), `threads.py` (~170 lines, includes
     `GET /threads/{thread_id}/metadata` per IMP-03), `thread_state.py`
     (~50 lines), `messages.py` (~50 lines), `cancel.py` (~50 lines),
     `teams.py` (~60 lines), `permissions.py` (~60 lines), `admin.py`
     (~10 lines). Each module imports from `api/dependencies.py`.
     - Name: split endpoints into per-resource route modules
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase6-step3.md`
     - Executing agent: `vaultspec-high-executor`

  1. Delete `endpoints.py`. No re-export shim. Update `api/app.py` to call
     `register_routes(app)` instead of `app.include_router(router)`. Run
     test suite.
     - Name: delete endpoints.py and rewire app
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase6-step4.md`
     - Executing agent: `vaultspec-high-executor`

### Wave 4 (after Wave 3): Phase 7

- `Phase 7` -- D-08: slim app.py
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase7-summary.md`

  1. Create `api/middleware.py`. Move `_CacheControlMiddleware` from
     `api/app.py` (~20 lines).
     - Name: extract middleware
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase7-step1.md`
     - Executing agent: `vaultspec-high-executor`

  1. Create `control/diagnostics.py`. Move `_classify_missing_ws_thread`
     from `api/app.py` (~76 lines). This function does DB queries and
     checkpoint lookups so it cannot go to Layer 1 `thread/`.
     - Name: extract WS thread diagnostics to control
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase7-step2.md`
     - Executing agent: `vaultspec-high-executor`

  1. Split `_ws_mark_failed_and_broadcast`: DB status update logic moves to
     `control/` helper, WS broadcast stays in `api/app.py`. Assign
     `_process_metadata()` to `routes/threads.py` as a route-local helper
     (44 lines, mixed business/protocol — candidate for future extraction).
     Slim `_lifespan()` to delegate domain object composition to extracted
     modules. Update remaining `api/tests/test_app.py` imports for symbols
     that move in this phase (`_build_sqlite_fallback_diagnostics`,
     `_classify_missing_ws_thread`, `_create_dispatch_message_handler`).
     Verify `app.py` is under 500 lines: `create_app()`, `main()`,
     `_lifespan()`.
     - Name: slim app.py to factory
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase7-step3.md`
     - Executing agent: `vaultspec-high-executor`

  1. Run test suite. Verify `app.py` is under 500 lines.
     - Name: verify app.py slimming
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase7-step4.md`
     - Executing agent: `vaultspec-high-executor`

### Wave 5 (parallel, after Phase 0): Phases 8, 9, 10

- `Phase 8` -- D-09: split executor.py
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase8-summary.md`

  1. Create `worker/graph_lifecycle.py` (~300 lines). Extract
     `_get_or_compile_graph`, `_compile_graph`, `_send_graph_registered`,
     `_build_graph_input` into a `GraphLifecycleManager` class. The
     `Executor` delegates to it.
     - Name: extract graph lifecycle manager
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase8-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Create `worker/state_projection.py` (~150 lines). Extract
     `_pre_flight_checkpoint`, `_normalize_execution_state`,
     `_emit_execution_state_projection`, `_emit_terminal_status` into a
     `StateProjector` class. The `Executor` delegates to it.
     - Name: extract state projector
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase8-step2.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Verify `executor.py` retains `Executor` class with `handle_dispatch`,
     `_handle_ingest`, `_handle_resume`, concurrency gating (~400 lines).
     No module exceeds 500 lines. Run test suite.
     - Name: verify executor split
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase8-step3.md`
     - Executing agent: `vaultspec-standard-executor`

- `Phase 9` -- D-10: extract cli/ renderers
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase9-summary.md`

  1. Create `cli/_renderers.py` (~300 lines). Extract rendering functions
     from `cli/_team.py`: event rendering from `_watch_async` (10+ event
     type handlers), `render_permission_prompt()` (shortcut mapping),
     `render_status_table()` (plan icons, agent state, permissions),
     `render_thread_list()` (summary dashboard), `_format_elapsed()`.
     The Rich coupling stays in `_renderers.py`.
     - Name: extract CLI renderers
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase9-step1.md`
     - Executing agent: `vaultspec-standard-executor`

  1. Refactor `cli/_team.py` to import from `_renderers.py`. Verify
     `_team.py` retains only Click command definitions and delegates all
     rendering (~525 lines). Run test suite.
     - Name: rewire team commands to renderers
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase9-step2.md`
     - Executing agent: `vaultspec-standard-executor`

- `Phase 10` -- D-11: fix cli/_agent.py filesystem bypass
  - Phase summary: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase10-summary.md`

  1. Refactor `cli/_agent.py` to route preset discovery through the API's
     `/teams` endpoint (which `cli/_team.py presets` already uses) or call
     `team.team_config.discover_presets()` directly. Remove the hardcoded
     `Path(...) / "core" / "presets" / "agents"` filesystem path that
     references the old pre-Layer-1 `core/` directory. Run test suite.
     - Name: fix agent preset discovery
     - Step record: `.vault/exec/2026-03-24-entry-point-layer/2026-03-24-entry-point-layer-phase10-step1.md`
     - Executing agent: `vaultspec-standard-executor`

## Parallelization

The 11 phases are organized into 5 dependency waves:

- **Wave 1**: Phases 0, 1, 3, 4 run in parallel (no interdependencies).
  Phase 0 creates `ipc/`, Phase 1 extracts infrastructure, Phase 3 moves
  projection, Phase 4 moves event handlers. Each touches distinct files.

- **Wave 2**: Phase 2 (dispatch consolidation) requires Phases 0 and 1.
  Phase 5 (health consolidation) requires Phase 1. Phase 2 must complete
  before Phase 5 starts (dispatch may affect health endpoint wiring).

- **Wave 3**: Phase 6 (route split) requires Phases 2, 3, 4, 5 -- all
  business logic must be extracted before routes can be split into thin
  adapters.

- **Wave 4**: Phase 7 (slim app.py) requires Phase 6 -- routes must be
  split before app.py can be reduced to a factory.

- **Wave 5**: Phases 8, 9, 10 run in parallel. Phase 8 requires Phase 0
  (IPC types must exist for executor imports). Phases 9 and 10 have no
  prerequisites beyond main branch state. Wave 5 can run concurrently
  with Waves 2-4.

Maximum parallelism: 4 agents in Wave 1, 3 agents in Wave 5.

## Verification

Success criteria -- all must pass after all 11 phases complete:

- Every entry point file (`api/app.py`, `api/routes/*.py`,
  `api/internal.py`, `worker/app.py`, `worker/executor.py`,
  `worker/graph_lifecycle.py`, `worker/state_projection.py`,
  `cli/_team.py`, `cli/_agent.py`, `cli/_renderers.py`) is under
  500 lines

- Zero business logic in route handlers -- each route module in
  `api/routes/` contains only protocol translation (request parsing,
  dependency injection, response formatting, error mapping)

- No entry point cross-imports: `worker/` does not import from `api/`,
  `cli/` does not import from `worker/`, no entry point imports from
  another entry point. Verify with
  `grep -r "from.*\.api\." src/vaultspec_a2a/worker/` (zero matches) and
  similar for all entry point pairs

- Shared IPC types live in neutral `ipc/` package. Both `api/` and
  `worker/` import `DispatchRequest` etc. from `ipc/schemas`

- `pytest -m core` stays at 425 passed (Layer 1 isolation preserved)

- Full test suite stays at 992 passed (run with standard exclusions for
  migration, factory, compiler tests and non-live/non-jaeger markers)

- No re-export shims anywhere. `api/schemas/internal.py` is deleted.
  `api/endpoints.py` is deleted. Old import paths break loudly

- No `# noqa` comments carried forward. The 2 `noqa: B904` in
  `internal.py` are fixed with `from e` during Phase 4

- `cli/_agent.py` routes preset discovery through the API or domain
  service. No filesystem path to old `core/` directory

- `executor.py` split into 3 modules: `executor.py` (~400 lines),
  `graph_lifecycle.py` (~300 lines), `state_projection.py` (~150 lines).
  None exceeds 500 lines

- `control/__init__.py` docstring and `__all__` updated to reflect the new
  dual nature: production runtime (circuit breaker, dispatch, health, etc.)
  and dev-tooling (db, doctor, hooks, verify)

- `_process_metadata()` explicitly assigned to `routes/threads.py` as a
  route-local helper

Per-phase verification gate: after each phase commit, run the full test
suite and `pytest -m core`. Both must match or exceed the baseline. If a
phase introduces a regression, fix it before proceeding to the next phase.
