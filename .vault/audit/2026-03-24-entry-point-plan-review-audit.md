---
tags:
  - '#audit'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

# `entry-point-layer` audit: `plan-review`

Boundary audit of the Layer 2 Entry Point Decomposition plan against the
three-layer architecture. All claims verified against source code.

---

## 1. Verdict

**APPROVE WITH CONDITIONS**

The plan is well-structured, the ADR review conditions (CRIT-01 through
CRIT-03, IMP-02 through IMP-04, MIN-03, MIN-04) are all incorporated, and
the phased approach with wave-based parallelization is sound. However, 2
critical gaps, 3 important gaps, and several minor observations must be
addressed before or during execution.

---

## 2. Layer 1 Integrity Assessment

**Will the library remain clean? YES -- with one caveat.**

- No decision (D-01 through D-11) moves code INTO Layer 1 modules
  (`thread/`, `context/`, `team/`, `graph/`, `streaming/`, `lifecycle/`).
  The prior ADR review caught that D-04 originally targeted `thread/`;
  the plan correctly redirects to `control/projection.py` and
  `control/snapshot.py`.

- Verified: `thread/`, `context/`, `team/`, `graph/` imports are clean.
  `thread/__init__.py` imports only from its own submodules.
  `context/metadata.py` imports only from `thread/errors`. `graph/compiler.py`
  imports from `context/`, `thread/`, `team/`, `domain_config` -- all Layer 1.
  No Layer 2 imports anywhere in Layer 1.

- The plan does not add new imports to any Layer 1 module. `pytest -m core`
  (425 tests) will continue to pass in isolation.

- **Caveat**: D-08 mentions `_ws_mark_failed_and_broadcast` DB update logic
  could move to `thread/`. The plan says "or inlined into the caller with
  a `control/` helper." The executor must NOT choose `thread/` -- the DB
  update imports `database.crud` which is Layer 2 IS. The plan wording is
  ambiguous but the `control/` option is the correct one.

---

## 3. Layer 2 Integrity Assessment

**Will entry points be thin after execution? YES -- mostly.**

### Route Handlers (D-07)

Verified 13 route decorators in `endpoints.py`:

1. `GET /health` (line 229)
2. `POST /threads` (line 378)
3. `GET /threads` (line 612)
4. `GET /threads/{thread_id}/metadata` (line 678)
5. `GET /threads/{thread_id}/state` (line 953)
6. `POST /threads/{thread_id}/messages` (line 1078)
7. `GET /team/status` (line 1278)
8. `GET /teams` (line 1342)
9. `POST /permissions/{id}/respond` (line 1377)
10. `POST /threads/{thread_id}/cancel` (line 1662)
11. `DELETE /threads/{thread_id}` (line 1816)
12. `POST /threads/{thread_id}/archive` (line 1842)
13. `POST /admin/shutdown` (line 1876)

The plan's D-07 route module list assigns all 13 routes (IMP-03 fixed:
metadata endpoint goes to `routes/threads.py`). No route is missed.

### Business Logic Accounting

After D-03 (dispatch), D-04 (projection/snapshot), D-05 (event handlers),
D-06 (health), and D-07 (route split), the route handlers should contain
only protocol translation. However:

**`_process_metadata()` (lines 332-375) is NOT accounted for in any
decision.** This function does workspace validation, context ref discovery,
nickname generation, and team config loading. It is called by
`create_thread_endpoint` (line 409). It raises `HTTPException(422)` for
invalid workspace roots, which makes it partially protocol-aware. The
plan does not extract it and does not mention it in the route split.

This is a minor gap because `_process_metadata` is 44 lines and has
some protocol coupling (HTTPException). It could stay in `routes/threads.py`
as a route-local helper, or the HTTPException could be replaced with a
domain error and the function moved to `control/`. Either way, the plan
should explicitly assign it. See CRIT-02 below.

### Entry Point Cross-Imports

After D-01, all `worker/ -> api/` imports will be eliminated:
- `worker/app.py:34` imports `DispatchRequest`, `DispatchResponse` from
  `api.schemas.internal` -- moves to `ipc/schemas`
- `worker/executor.py:24-29` imports `DispatchRequest`,
  `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload` from
  `api.schemas.internal` -- moves to `ipc/schemas`
- `worker/executor.py:24` imports `sequenced_to_dict` from
  `api.event_adapter` -- moves to `ipc/serializers`

No additional cross-imports were found. `cli/` and `protocols/` are already
clean.

### Executor Split (D-09)

The proposed 3-way split is clean. Verified:
- `_build_graph_input` (static method, line 850) has no shared mutable state
- `_compile_graph`, `_get_or_compile_graph` reference `self._graph_cache`
  and `self._thread_to_cache_key` -- these are owned by `Executor` and
  passed to `GraphLifecycleManager` via constructor
- `_normalize_execution_state`, `_emit_execution_state_projection` reference
  only `self._bridge` and `self._checkpointer` -- clean delegation
- `_pre_flight_checkpoint` references `self._checkpointer` only

The `Executor.__init__` wires `self._aggregator.add_broadcast_hook` with
a closure over `sequenced_to_dict` and `bridge.send_event`. This stays
in `Executor` and is unaffected by the split.

### CLI Thinness (D-10)

`cli/_team.py` at 825 lines with 575 lines of business logic. The plan
extracts renderers to `_renderers.py` (~300 lines). This leaves `_team.py`
at ~525 lines. The `_watch_async` function (348 lines) has its rendering
extracted but retains WebSocket client protocol (connect, subscribe, event
loop). The WebSocket client protocol is protocol translation (CLI-to-WS
bridge), so this is correct.

### CLI Filesystem Bypass (D-11)

Verified at `cli/_agent.py:27`:
```python
presets_dir = Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"
```
This references `core/presets/agents` which was the pre-Layer 1 location.
After Layer 1, presets live at `team/presets/`. This is a latent bug.
The plan correctly identifies this and fixes it via API or domain service
call.

---

## 4. Layer 3 Integrity Assessment

**Is infrastructure untouched? YES.**

The plan explicitly states "Layer 3 (Docker, Justfile) is NOT touched" as
a constraint. No decision touches Docker, compose files, or Justfile. No
new `control/` module introduces Docker or infrastructure dependencies.

---

## 5. `control/` Bloat Assessment

### Current State

`control/` has 2,432 lines across 5 Python files (excluding `__init__.py`):

| Module | Lines | Character |
|--------|------:|-----------|
| `config.py` | 632 | Production runtime (InfraConfig + Settings facade) |
| `verify.py` | 894 | Dev-tooling (schema consistency) |
| `doctor.py` | 383 | Dev-tooling (system health checks) |
| `db.py` | 312 | Dev-tooling (DB lifecycle) |
| `hooks.py` | 191 | Dev-tooling (pre-commit) |

The `__init__.py` docstring explicitly says "dev-tooling modules invoked
via `python -m`." Only `config.py` is production runtime; the other 4 are
dev-tooling.

### After Plan Execution

The plan adds ~1,280 lines of **production runtime** code:

| New Module | Lines | Character |
|-----------|------:|-----------|
| `circuit_breaker.py` | ~80 | Production runtime |
| `worker_management.py` | ~450 | Production runtime |
| `dispatch.py` | ~200 | Production runtime |
| `projection.py` | ~491 | Production runtime |
| `snapshot.py` | ~240 | Production runtime |
| `event_handlers.py` | ~400 | Production runtime |
| `health.py` | ~150 | Production runtime |
| `diagnostics.py` | ~76 | Production runtime |

This brings `control/` to ~3,712 lines with a fundamental character
change: from "dev-tooling only" to "mixed dev-tooling + production
runtime." The production runtime code (2,087 lines) would outweigh the
dev-tooling code (1,780 lines).

### Assessment

`control/` becomes **incoherent**. It mixes two unrelated responsibilities:
- Dev-time CLI tools (db, doctor, hooks, verify)
- Production gateway runtime infrastructure (circuit breaker, dispatch,
  event handling, health, projection, snapshot, diagnostics, worker
  management)

The `__init__.py` docstring will be wrong. The module will need to be
imported at gateway startup (production code) despite being documented as
"dev-tooling modules invoked via `python -m`."

### Recommendation

Accept the bloat for now but with two actions:

1. **Update `control/__init__.py` docstring** to reflect the new dual
   nature: "Infrastructure services: production runtime (circuit breaker,
   dispatch, health, etc.) and dev-tooling (db, doctor, hooks, verify)."

2. **Track a follow-up ticket** to evaluate splitting `control/` into
   `control/` (dev-tooling) and `runtime/` or `infra/` (production
   services) if the package grows further. This is not blocking for the
   current plan.

The alternative -- creating a new `gateway/` or `runtime/` package now --
would add scope and delay. The ADR review raised this as IMP-01 and the
team acknowledged it. Proceeding with `control/` as-is is the pragmatic
choice.

---

## 6. Test Coverage Gaps

### Test Files Requiring Import Updates

The plan enumerates test files for Phase 0 (D-01) and Phase 1 (D-02).
Verified these plus additional files:

| Test File | Current Import | Breaks In | Plan Accounts? |
|-----------|---------------|-----------|----------------|
| `worker/tests/test_app.py:9` | `...api.schemas.internal.DispatchRequest` | Phase 0 | YES |
| `worker/tests/test_executor.py:22` | `...api.schemas.internal.DispatchRequest` | Phase 0 | YES |
| `protocols/mcp/tests/test_server.py:39` | `....api.app.LazyWorkerSpawner, WorkerCircuitBreaker, create_app` | Phase 1 | YES |
| `api/tests/conftest.py:36` | `..app.LazyWorkerSpawner, WorkerCircuitBreaker, create_app` | Phase 1 | **NO** |
| `api/tests/test_app.py:16-25` | `..app.LazyWorkerSpawner, WorkerCircuitBreaker, WorkerWatchdog, _build_sqlite_fallback_diagnostics, _build_worker_restart_detail, _classify_missing_ws_thread, _create_dispatch_message_handler, _worker_stderr_log_path` | Phases 1, 7 | **NO** |
| `api/tests/test_projection.py:14-22` | `..projection.CheckpointProjection, ...` | Phase 3 | **NO** |

### CRIT-01: `api/tests/test_app.py` Imports 8 Symbols from `api/app.py`

This test file imports `LazyWorkerSpawner`, `WorkerCircuitBreaker`,
`WorkerWatchdog` (Phase 1/D-02), `_build_sqlite_fallback_diagnostics`
(Phase 7/D-08), `_build_worker_restart_detail` (Phase 1/D-02),
`_classify_missing_ws_thread` (Phase 7/D-08),
`_create_dispatch_message_handler` (Phase 2/D-03 or Phase 7/D-08), and
`_worker_stderr_log_path` (Phase 1/D-02).

These imports break across multiple phases. The plan does NOT mention
`api/tests/test_app.py` in any phase's test update task. This will cause
test failures at Phase 1.

### CRIT-02: `api/tests/test_projection.py` Imports from Moving Module

This test file imports 7 symbols from `api/projection`:
`CheckpointProjection`, `ProjectedInterrupt`,
`apply_checkpoint_projection`, `apply_execution_state_projection`,
`enrich_snapshot_from_execution_state`, `project_checkpoint_tuple`,
`project_execution_state_model`.

After Phase 3 (D-04), `api/projection.py` is deleted and its contents
move to `control/projection.py`. The plan says "Update imports in
`api/endpoints.py` and any test files (`api/tests/test_projection.py`
if it exists)." The conditional "if it exists" is concerning -- it DOES
exist (verified), and the plan should unconditionally include it.

### `api/tests/conftest.py` Imports from Moving Paths

`conftest.py:36` imports `LazyWorkerSpawner`, `WorkerCircuitBreaker`,
`create_app` from `..app`. After Phase 1 (D-02), the first two move to
`control/`. The plan does not mention this file. Since `conftest.py` is
used by ALL api tests, this breakage is high-impact.

### Test Files That Test Extracted Code

`api/tests/test_app.py` tests `WorkerCircuitBreaker`, `WorkerWatchdog`,
`LazyWorkerSpawner`, `_classify_missing_ws_thread`,
`_build_sqlite_fallback_diagnostics`,
`_create_dispatch_message_handler`, and other functions that are being
extracted. The tests should move with the code:

- Circuit breaker tests -> `control/tests/test_circuit_breaker.py`
- Worker management tests -> `control/tests/test_worker_management.py`
- Diagnostics tests -> `control/tests/test_diagnostics.py`
- Dispatch handler tests -> `control/tests/test_dispatch.py` or stay in
  `api/tests/` if they test the route-level behavior

The plan does not account for test relocation at all. This will cause
organizational debt if tests stay in `api/tests/test_app.py` but test
code that lives in `control/`.

---

## 7. Critical Findings (would cause plan failure)

### CRIT-01: `api/tests/test_app.py` and `api/tests/conftest.py` Not in Any Phase's Test Update List

`api/tests/test_app.py` imports 8 symbols that move across Phases 1, 2,
and 7. `api/tests/conftest.py` imports `LazyWorkerSpawner` and
`WorkerCircuitBreaker` that move in Phase 1. Neither file is listed in
any phase task.

**Impact**: Phase 1 execution will produce immediate test failures that
block the verification gate.

**Fix**: Add `api/tests/test_app.py` and `api/tests/conftest.py` to
Phase 1 step 3 ("rewire imports and verify"). Add `api/tests/test_app.py`
to Phase 7 step 3 for the remaining symbols that move in Phase 7.

### CRIT-02: `_process_metadata()` Not Assigned to Any Decision

`_process_metadata()` at `endpoints.py:332-375` is 44 lines of mixed
business logic (workspace validation, context ref discovery, nickname
generation, team config loading) and protocol code (HTTPException). It is
called by `create_thread_endpoint`.

The research audit classified it as "business logic -> `thread/creation.py`
or `thread/creation.py`" but the ADR and plan do not account for it. When
D-07 splits `endpoints.py` into route modules, `_process_metadata` will
end up in `routes/threads.py` by default. This is acceptable since it has
HTTP coupling (raises HTTPException), but it should be explicitly assigned.

**Impact**: Not a blocker but an untracked ~44 lines of business logic
that will persist in the route layer.

**Fix**: Explicitly assign `_process_metadata` to `routes/threads.py` as
a route-local helper in the D-07 route split. Note that it mixes business
logic with protocol (HTTPException) and is a candidate for future
extraction with dependency inversion.

---

## 8. Important Findings (would cause rework)

### IMP-01: D-08 `_ws_mark_failed_and_broadcast` Destination Is Ambiguous

The plan says: "DB status update logic moves to `control/` (or inlined
into the caller with a `control/` helper)." The ADR says: "DB update ->
`thread/lifecycle.py`." The ADR option violates Layer 1 boundaries since
the DB update calls `database.crud.update_thread_status`. The plan
partially corrects this with the `control/` option but leaves "or" in
the text.

**Fix**: Remove the ambiguity. The DB update goes to `control/`, not
`thread/`. Delete the `thread/lifecycle.py` option from Phase 7.

### IMP-02: Dispatch Site Count Discrepancy

The ADR says "6 call sites" throughout. The plan says "7 dispatch call
sites" and adds `_redispatch_reconciling` (in `_lifespan`, line 1221 of
`app.py`). This 7th site is structurally different from the other 6:
- It iterates over multiple threads in a loop
- It does a manual `circuit_breaker.state == "open"` check instead of
  calling `pre_dispatch()`
- It uses `continue` on failure instead of raising or marking FAILED

The plan's D-03 step 2 lists it as one of 7 sites to refactor. The
consolidated `dispatch_to_worker()` function needs to accommodate this
loop pattern. The function signature in the ADR (`async def dispatch_to_worker(...)
-> DispatchResponse`) returns a single response, which is correct for
the loop body.

**Impact**: Minor. The function can handle this case if `bypass_circuit_breaker`
is extended or if the caller does its own CB check. The plan already
mentions "manual CB check, silent continue" for this site.

### IMP-03: `control/__init__.py` Docstring Must Be Updated

The current docstring says "dev-tooling modules invoked via `python -m`"
and lists only `db`, `doctor`, `verify`, `hooks`. After the plan executes,
`control/` will contain 8+ new production runtime modules. The docstring
and `__all__` will be stale.

**Fix**: Add a task to update `control/__init__.py` docstring and `__all__`
after the final phase completes.

---

## 9. Minor Observations

### MIN-01: `api/schemas/__init__.py` Cleanup Is Correctly Planned

Phase 0 step 3 says: "Remove the 6 IPC type re-exports from
`api/schemas/__init__.py` (lines 54-59) and their `__all__` entries."
Verified lines 54-59 contain exactly the 6 IPC type re-exports. The
`__all__` list contains all 6 names (lines 94, 95, 98, 99, 102, 143).
This is correct.

### MIN-02: `noqa: B904` Locations Are Verified

The plan says `internal.py` lines 646 and 723 have `# noqa: B904`. Verified:
- Line 646: `raise HTTPException(  # noqa: B904` -- in `receive_worker_event`
- Line 723: `raise HTTPException(  # noqa: B904` -- in `receive_worker_event_batch`

Both are `except ValueError: raise HTTPException` patterns where `from e`
is missing. The fix is trivial. Phase 4 step 2 correctly handles this.

### MIN-03: `_trace_headers()` Duplication Is Verified

Verified identical function at:
- `endpoints.py:137-146` (6 lines with docstring)
- `app.py:268-272` (5 lines with docstring)

Both inject OTel carrier. Phase 6 step 2 (R-02) correctly deduplicates
into `api/_utils.py`.

### MIN-04: `_CacheControlMiddleware` Is Tiny

`app.py` `_CacheControlMiddleware` at lines 242-260 is 19 lines. Phase 7
step 1 moves it to `api/middleware.py`. This is a clean, self-contained
extraction.

### MIN-05: app.py ~200 Line Target

After extracting infrastructure (D-02, ~530 lines), dispatch handlers
(D-03, ~135+69=204 lines), health (D-06, ~115 lines), middleware (D-08,
~19 lines), diagnostics (D-08, ~76 lines), reconciliation dispatch
(part of D-03/D-08), and with routes moved to `routes/` (D-07), the
remaining `app.py` would contain: `create_app()` factory, `_lifespan()`,
`main()`, WS route wiring. Estimated ~300-400 lines, not ~200.

The `_lifespan()` function alone is ~210 lines (lines 1097-1304). Even
after delegating domain object composition, the init/shutdown sequence
has substantial wiring. The 200-line target is optimistic.

**Recommendation**: Set the target to "under 500 lines" which the
verification criteria already state, rather than claiming ~200 in the
task descriptions.

---

## 10. Verified Claims

| Check | Claim | Source | Result |
|-------|-------|--------|--------|
| D-01 V-01 | `worker/app.py` imports from `api.schemas.internal` | `worker/app.py:34` | CONFIRMED |
| D-01 V-02 | `worker/executor.py` imports from `api.schemas.internal` | `executor.py:25-29` | CONFIRMED |
| D-01 V-03 | `worker/executor.py` imports `sequenced_to_dict` from `api.event_adapter` | `executor.py:24` | CONFIRMED |
| D-01 | `HeartbeatMessage` is dead code | Grep across codebase | CONFIRMED: only in `schemas/__init__.py` re-export |
| D-01 | `WorkerEventEnvelope` is dead code | Grep across codebase | CONFIRMED: only in `schemas/__init__.py` re-export |
| D-02 | 3 inline classes are pure infrastructure | Read `app.py:159-1089` | CONFIRMED: zero L1 imports, zero domain logic |
| D-03 | 7 dispatch sites exist | Read all sites | CONFIRMED: 4 in `endpoints.py`, 2 in `app.py` (dispatch factories), 1 in `app.py` (`_redispatch_reconciling`) |
| D-03 | Cancel bypasses circuit breaker | `endpoints.py:1746` | CONFIRMED: no `pre_dispatch()` call |
| D-03 | 429 handling differs per site | Read all 7 sites | CONFIRMED: create marks FAILED, send raises 503, WS raises rejected, control ignores, reconciling continues |
| D-04 | `projection.py` imports from `database.crud` | `projection.py:10-13` | CONFIRMED |
| D-04 | `projection.py` imports from `api.schemas.*` | `projection.py:25-31` | CONFIRMED |
| D-04 | Target is `control/` (not `thread/`) | Plan Phase 3 step 1 | CONFIRMED: correctly targets `control/projection.py` |
| D-05 | 3x duplicated relay sequence | `internal.py:509-550`, `664-698`, `765-788` | CONFIRMED: identical handler call sequence |
| D-05 | Relay is NOT identical -- subtle differences | Read all 3 relay paths | PARTIALLY TRUE: WS path has early-return for `execution_state_projection` (line 502-508), HTTP single has same early-return (line 656-662), batch inlines it in the loop (line 758-764). The remaining sequence is identical. |
| D-07 | 13 routes in `endpoints.py` | Grep for `@router` decorators | CONFIRMED: 13 routes |
| D-07 | All routes assigned to modules | Plan Phase 6 step 3 | CONFIRMED (incl. metadata per IMP-03) |
| D-08 | `_classify_missing_ws_thread` targets `control/diagnostics.py` | Plan Phase 7 step 2 | CONFIRMED (correctly avoids `thread/`) |
| D-09 | No shared mutable state between 3 pieces | Read `executor.py:60-140` | CONFIRMED: graph cache, thread map, aggregator, bridge, ingest lock all owned by `Executor` and passed to delegates |
| D-11 | Filesystem bypass references old `core/` path | `cli/_agent.py:27` | CONFIRMED: `core/presets/agents` |
| Layer 1 | No plan decision adds imports to Layer 1 | Read all decisions | CONFIRMED |
| Baseline | Line counts match plan | `wc -l` on all files | CONFIRMED: endpoints.py=1883, app.py=1507, internal.py=812, executor.py=983, _team.py=825 |

---

## 11. Recommendations

### Must-Fix (before execution)

1. **Add `api/tests/test_app.py` and `api/tests/conftest.py` to Phase 1
   step 3.** These files import `LazyWorkerSpawner`, `WorkerCircuitBreaker`
   from `..app` and will break when D-02 moves them to `control/`.

2. **Add `api/tests/test_projection.py` unconditionally to Phase 3
   step 3.** Remove the "if it exists" qualifier -- it exists.

3. **Remove `thread/lifecycle.py` option from D-08.** The DB update in
   `_ws_mark_failed_and_broadcast` MUST go to `control/`, not `thread/`.

### Should-Fix (during execution)

4. **Assign `_process_metadata()` explicitly.** State that it stays in
   `routes/threads.py` as a route-local helper. Note it for future
   extraction.

5. **Plan test relocation for `api/tests/test_app.py`.** After Phase 1,
   the circuit breaker and worker management tests in this file test code
   that lives in `control/`. Consider creating `control/tests/` and
   splitting the test file. At minimum, track it as follow-up debt.

6. **Update `control/__init__.py` docstring** after the final phase.

7. **Adjust app.py target from ~200 to "under 500 lines"** in task
   descriptions to match the verification criteria.

### Nice-to-Have (follow-up)

8. **Track `control/` package split** as a future task if the package
   grows beyond ~4,000 lines. Consider `control/dev/` (db, doctor, hooks,
   verify) vs `control/` root (production runtime).

9. **Consider extracting `_process_metadata()` business logic** with
   dependency inversion (return domain error instead of HTTPException) in
   a future pass.
