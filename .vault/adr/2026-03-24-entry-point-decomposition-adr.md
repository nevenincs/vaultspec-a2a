---
tags:
  - '#adr'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-api-module-research]]'
  - '[[2026-03-24-worker-cli-research]]'
  - '[[2026-03-24-cross-import-dependency-map-research]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `entry-point-layer` adr: `layer-2-entry-point-decomposition` | (**status:** `implemented`)

## Problem Statement

Layer 2 entry points are fat. Research across 3 parallel audits found:

- **api/**: Only 39% protocol translation. 43% business logic (2,473 lines),
  18% infrastructure (1,029 lines).
- **worker/executor.py**: 100% business logic (983 lines). Zero protocol
  awareness.
- **cli/_team.py**: 575 of 825 lines are business logic. `_watch_async` alone
  is 348 lines of domain event rendering + permission prompts.
- **3 boundary violations**: `worker/` imports from `api/schemas/internal` and
  `api/event_adapter` — inverted dependency.
- **2 dead IPC types**: `HeartbeatMessage` and `WorkerEventEnvelope` never
  imported.
- **6× duplicated dispatch pattern**: 50-80 lines repeated across REST and WS
  call sites.
- **2× duplicated health endpoint**: `endpoints.py:health()` and
  `app.py:health_endpoint()` overlap significantly.
- **projection.py (491 lines)**: 100% business logic with zero HTTP awareness,
  misplaced in `api/`.

The layer boundary rule ("entry points never import from each other") is
violated by `worker/` → `api/`.

## Considerations

- Phase 0 (shared IPC types) must complete before api/ and worker/ can be
  decomposed independently — both import from `api/schemas/internal.py`
- executor.py (983 lines) is below the 1,000-line split threshold but is 100%
  business logic — its position in worker/ is acceptable since that's its sole
  consumer, but its dependency on api/ types is the architectural violation
- The 3 inline classes in app.py (CircuitBreaker, Spawner, Watchdog) are pure
  infrastructure with zero business logic, zero L1 imports — safe to extract
- projection.py is consumed only by endpoints.py snapshot logic — both are
  business logic that should co-locate in thread/
- cli/ and protocols/ are already clean — no cross-entry-point imports
- internal.py (812 lines) has 72% business logic in 4 event handlers that do
  DB writes and state machine transitions
- The dispatch-to-worker pattern (ensure_worker → pre_dispatch → POST /dispatch
  → record_success/failure → mark_connected → error handling) is repeated at
  6 call sites across endpoints.py and app.py

## Constraints

- Each phase must preserve the test baseline: 992 passed, 425 core
- No backwards-compat re-export shims. Old import paths break loudly.
- Modules over 1,000 lines must be split
- No mocks, stubs, fakes, patches, skips
- Layer 1 (`thread/`, `context/`, `team/`, `graph/`, `streaming/`,
  `lifecycle/`) is NOT touched
- Layer 3 (Docker, Justfile) is NOT touched

## Implementation

Eight architectural decisions for Layer 2 decomposition:

**D-01: Shared IPC types move to `ipc/` package.**

Create `src/vaultspec_a2a/ipc/` as a new Layer 2 infra service module:

```
ipc/
  __init__.py        — public API re-exports
  schemas.py         — DispatchRequest, DispatchResponse,
                       ExecutionStateProjectionPayload,
                       ExecutionTaskProjectionPayload
  serializers.py     — sequenced_to_dict (from api/event_adapter)
```

Delete `api/schemas/internal.py` after updating all consumers. No re-export
shim. Delete dead types `HeartbeatMessage` and `WorkerEventEnvelope`.

Also update `api/schemas/__init__.py` to remove the 6 IPC type re-exports
(lines 54-59) and their `__all__` entries. No re-export shim from the old
`api.schemas` path — consumers must import from `ipc/` directly.

The `DispatchRequest.recursion_limit` default factory imports
`control.config.settings` — this is an L2-IS import, allowed from `ipc/`.

Test files that must update: `worker/tests/test_app.py`,
`worker/tests/test_executor.py`.

**Rationale**: These types define the gateway↔worker contract. Neither `api/`
nor `worker/` owns them. A neutral `ipc/` package makes both entry points
equal consumers of the contract.

---

**D-02: Infrastructure classes extract to `control/`.**

Move the 3 inline classes from `api/app.py` to `control/`:

```
control/
  circuit_breaker.py   — WorkerCircuitBreaker (~80 lines)
  worker_management.py — LazyWorkerSpawner, WorkerWatchdog,
                          _spawn_worker, _shutdown_worker_process,
                          _tcp_port_ready, _check_worker_health,
                          _runtime_dir, _worker_stderr_log_path,
                          _read_log_tail, _build_worker_restart_detail
                          (~450 lines)
```

The HTTPException in `WorkerCircuitBreaker.pre_dispatch()` is a protocol
concern leaked into infrastructure. Refactor: return a result enum/bool and
let the caller raise.

`WorkerWatchdog` writes 9 attributes directly onto FastAPI's `app.state`.
To cleanly extract it, introduce a `WorkerState` dataclass that the watchdog
owns. The caller (`_lifespan`) creates it, passes it to the watchdog, and
also stores it on `app.state` for route handlers to read. This breaks the
direct `app.state` coupling without changing runtime behavior.

Test files that must update: `protocols/mcp/tests/test_server.py` (imports
`LazyWorkerSpawner`, `WorkerCircuitBreaker` from `api.app`).

**Rationale**: These are generic process supervision patterns — circuit
breaker, lazy spawn, crash watchdog. They have zero domain knowledge, zero L1
imports. `control/` already houses infrastructure utilities (config, db, hooks,
doctor, verify). This is their natural home.

---

**D-03: Dispatch orchestration consolidates into `control/dispatch.py`.**

Extract the duplicated dispatch-to-worker pattern from 6 call sites into:

```python
# control/dispatch.py
async def dispatch_to_worker(
    worker_client: httpx.AsyncClient,
    dispatch: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
    spawner: LazyWorkerSpawner,
    *,
    trace_headers: dict[str, str] | None = None,
) -> DispatchResponse:
    """Single dispatch entry point. Handles ensure_worker, pre_dispatch,
    POST, record_success/failure, error handling."""
```

The 6 call sites have semantic differences:
- Cancel bypasses the circuit breaker
- 429 handling differs (create_thread marks FAILED, send_message raises 503)
- Post-dispatch status transitions differ per caller

`dispatch_to_worker()` handles only the common core: `ensure_worker` →
`pre_dispatch` (optional) → HTTP POST → `record_success/failure` → error
handling. Post-dispatch behavior (status transitions, error responses)
remains in callers. This eliminates ~50% of duplication while keeping
caller-specific policy local.

```python
async def dispatch_to_worker(
    worker_client: httpx.AsyncClient,
    dispatch: DispatchRequest,
    circuit_breaker: WorkerCircuitBreaker,
    spawner: LazyWorkerSpawner,
    *,
    bypass_circuit_breaker: bool = False,
    trace_headers: dict[str, str] | None = None,
) -> DispatchResponse:
```

**Rationale**: 300+ lines of duplicated orchestration code across REST and WS
paths. Single source of truth for the transport call eliminates divergence bugs
while keeping domain-specific post-dispatch logic in callers.

---

**D-04: Projection + snapshot business logic moves to `control/`.**

`api/projection.py` and the snapshot functions in `endpoints.py` are 100%
business logic with zero HTTP awareness — but they import from `database.crud`
and `api.schemas.*` (Layer 2), so they CANNOT move to `thread/` (Layer 1)
without first refactoring those dependencies. Moving to `control/` is the
correct Layer 2 infra service destination.

```
control/
  projection.py     — ProjectedInterrupt, CheckpointProjection,
                       ExecutionStateProjection, project_checkpoint_tuple,
                       apply_checkpoint_projection, enrich_snapshot_*
                       (~491 lines, moved from api/projection.py)
  snapshot.py        — _enrich_snapshot_from_state, _MinimalState,
                       _load_checkpoint_history_depth,
                       _finalize_snapshot_replay_status
                       (~240 lines, extracted from endpoints.py)
```

**Rationale**: This code has L2 dependencies (`database.crud`,
`api.schemas.snapshots`) that prevent placement in Layer 1. `control/` is the
correct home for business logic that bridges domain and infrastructure.
Future work may refactor these to accept DB results as parameters (dependency
inversion), enabling a move to Layer 1.

---

**D-05: Internal event handlers extract to `control/event_handlers.py`.**

Move the 4 business-logic handlers from `api/internal.py`:

```
control/
  event_handlers.py  — _handle_terminal_event,
                        _handle_permission_event,
                        _handle_progress_event,
                        _handle_execution_state_event,
                        relay_event() orchestrator
                        (~400 lines)
```

The 3× duplicated relay orchestration sequence (in `_relay_worker_event`,
`receive_worker_event`, `receive_worker_event_batch`) consolidates into a
single `relay_event()` function.

`api/internal.py` retains: route handlers, WS endpoint, validation, auth
verification. Drops from 812 to ~400 lines.

**Rationale**: These handlers do DB writes, state machine transitions,
permission expiry, aggregator GC. That's business logic, not protocol
translation.

---

**D-06: Health assembly consolidates into `control/health.py`.**

Extract shared health logic from both `endpoints.py:health()` and
`app.py:health_endpoint()`:

```
control/
  health.py          — assemble_health_status(), includes DB probe,
                        checkpoint check, worker probe, circuit breaker
                        state, spawner state, restart metadata,
                        repair summary, SQLite diagnostics
                        (~150 lines)
```

Both routes become thin adapters calling `assemble_health_status()`.

**Rationale**: Two health endpoints with overlapping but divergent logic is a
bug waiting to happen. Single source of truth.

---

**D-07: `endpoints.py` splits into per-resource route modules.**

```
api/
  routes/
    __init__.py          — register_routes(app) helper
    health.py            — GET /health (~30 lines)
    threads.py           — POST/GET/DELETE threads, archive,
                            GET /threads/{id}/metadata (~170 lines)
    thread_state.py      — GET /threads/{id}/state (~50 lines)
    messages.py          — POST /threads/{id}/messages (~50 lines)
    cancel.py            — POST /threads/{id}/cancel (~50 lines)
    teams.py             — GET /teams, /team/status, /team/presets (~60 lines)
    permissions.py       — POST /permissions/{id}/respond (~60 lines)
    admin.py             — POST /admin/shutdown (~10 lines)
  dependencies.py        — get_aggregator, get_checkpointer, get_services,
                            etc. (~60 lines)
```

Delete `endpoints.py`. No re-export shim.

FastAPI dependency injection functions move to `dependencies.py`. Each route
module imports from `dependencies.py`. Route registration happens in
`routes/__init__.py` which `app.py` calls.

**Rationale**: 1,883 lines violates the 1,000-line ceiling. Per-resource
splitting is standard FastAPI practice. After D-03 (dispatch) and D-04
(snapshot), each route handler is 10-50 lines of pure protocol translation.

---

**D-08: `app.py` becomes a thin application factory.**

After extracting infrastructure (D-02), dispatch (D-03), health (D-06), and
splitting routes (D-07):

```
api/
  app.py               — create_app(), main(), _lifespan() (~200 lines)
  middleware.py         — _CacheControlMiddleware (~20 lines)
```

The lifespan function retains FastAPI-specific init/shutdown wiring but
delegates domain object composition to extracted modules.

`_classify_missing_ws_thread()` (76 lines of thread state drift
classification, imports from `database.crud`) moves to
`control/diagnostics.py` (not `thread/` — same L1 boundary issue as D-04).

`_ws_mark_failed_and_broadcast()` splits: DB update → `control/` or
`thread/`, WS broadcast → stays in `api/`.

**Rationale**: 1,507 lines violates the 1,000-line ceiling. After extraction,
app.py is a ~200-line factory that wires middleware, routes, and lifespan.

---

---

**D-09: Split `executor.py` into 3 focused modules.**

At 983 lines, executor.py is just below the 1,000-line threshold but is 100%
business logic with 3 distinct responsibilities. After D-01 fixes the api/
dependency, split proactively:

```
worker/
  executor.py          (~400 lines) — Executor class, handle_dispatch,
                         _handle_ingest, _handle_resume, concurrency gating
  graph_lifecycle.py   (~300 lines) — Graph cache, _get_or_compile_graph,
                         _compile_graph, _send_graph_registered,
                         _build_graph_input
  state_projection.py  (~150 lines) — _pre_flight_checkpoint,
                         _normalize_execution_state,
                         _emit_execution_state_projection,
                         _emit_terminal_status
```

The `Executor` class delegates to `GraphLifecycleManager` and
`StateProjector` helpers. Concurrency gating stays in `Executor`.

**Rationale**: Proactive split prevents the file from crossing 1,000 lines
during future work. The 3 responsibilities are cleanly separable with no
shared mutable state between them.

---

**D-10: Extract `cli/_team.py` domain rendering to `cli/_renderers.py`.**

`_watch_async` (348 lines) contains domain event rendering for 10+ event
types, interactive permission prompts with shortcut mapping, and terminal
state detection. The `status` and `list` commands also have ~100 lines of
domain-aware rendering (plan icons, agent state display, permission rendering).

Extract the rendering functions (not the Click commands themselves) to
`cli/_renderers.py`:

```
cli/
  _renderers.py      — render_event(), render_permission_prompt(),
                        render_status_table(), render_thread_list(),
                        _format_elapsed()
                        (~300 lines)
  _team.py           — Click commands only, delegates rendering
                        (~525 lines)
```

The Click/Rich coupling stays — `_renderers.py` uses Rich for formatting.
The separation is by responsibility (command parsing vs domain rendering),
not by framework.

**Rationale**: 825 lines with 575 lines of business logic. Extracting
renderers keeps each file focused and makes the rendering logic independently
testable.

---

**D-11: Fix `cli/_agent.py` filesystem bypass.**

Both commands in `_agent.py` (80 lines) directly access the filesystem to
discover preset TOML files using a hardcoded path that references the old
`core/presets/agents` directory (pre-Layer 1 decomposition). This is a
latent bug.

Fix: Route preset discovery through the API's `/teams` endpoint (which
`_team.py presets` already uses successfully) or call the domain service
`team.team_config.discover_presets()` directly.

**Rationale**: The filesystem path is already broken (references old
`core/` directory). Fix now to avoid user-facing bugs.

---

## Additional Fixes from Review

**R-01: Fix `noqa: B904` comments in `internal.py`.** Lines 646 and 753 have
`# noqa: B904` comments. Per project rules, `noqa` band-aids are forbidden.
Fix by adding `from` clause to the `raise` statements during D-05 extraction.

**R-02: Deduplicate `_trace_headers()`.** Identical function in both
`endpoints.py:137-146` and `app.py:268-272`. Consolidate into
`api/_utils.py` during D-07/D-08.

## Phase Order

| Phase | Decision | Prerequisite | Est. files touched (incl. tests) |
|-------|----------|-------------|----------------------------------|
| 0 | D-01: IPC types to `ipc/` | none | ~10 (+ 2 test files) |
| 1 | D-02: Infrastructure to `control/` | none (parallel with 0) | ~5 (+ 1 test file) |
| 2 | D-03: Dispatch consolidation | D-01, D-02 | ~5 |
| 3 | D-04: Projection to `control/` | none (parallel with 0-2) | ~4 |
| 4 | D-05: Event handlers to `control/` + R-01 noqa fix | none (parallel with 0-3) | ~3 |
| 5 | D-06: Health consolidation | D-02 | ~3 |
| 6 | D-07: Split endpoints.py into routes/ + R-02 trace dedup | D-03, D-04, D-05, D-06 | ~14 |
| 7 | D-08: Slim app.py | D-02, D-03, D-06, D-07 | ~4 |
| 8 | D-09: Split executor.py | D-01 | ~4 |
| 9 | D-10: Extract cli/ renderers | none (parallel with 8) | ~2 |
| 10 | D-11: Fix cli/_agent.py filesystem bypass | none (parallel with 8-9) | ~1 |

Phases 0, 1, 3, 4 can run in parallel. Phases 2, 5 require their
prerequisites. Phase 6 requires most extractions complete. Phase 7 follows 6.
Phases 8, 9, 10 can run in parallel after Phase 0 completes (for D-09) or
independently (for D-10, D-11).

## Validation Criteria

After all phases:

1. Every entry point file < 500 lines
2. Zero business logic in route handlers — protocol translation only
3. No entry point cross-imports (worker ↛ api, cli ↛ worker, etc.)
4. Shared IPC types in neutral `ipc/` package
5. `pytest -m core` stays at 425 passed
6. Full test suite stays at 992 passed
7. No re-export shims, no backwards-compat redirects
8. No `# noqa` comments carried forward
9. `cli/_agent.py` routes through API or domain service (no filesystem bypass)
10. `executor.py` split into 3 modules (none > 500 lines)
