---
tags:
  - '#audit'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-03-24-api-module-research]]'
  - '[[2026-03-24-worker-cli-research]]'
  - '[[2026-03-24-cross-import-dependency-map-research]]'
---

# `entry-point-layer` audit: `adr-review`

---

## 1. Verdict

**APPROVE WITH CONDITIONS**

The ADR is well-researched, the decomposition direction is correct, and most
claims are verified against the source code. However, there are 3 critical gaps
that will cause execution failure if not addressed, 4 important gaps that will
cause rework, and several minor observations.

---

## 2. Critical Gaps (would cause the plan to fail)

### CRIT-01: D-04 moves `projection.py` to Layer 1 (`thread/`) but it imports from Layer 2

The ADR claims projection.py is "100% business logic with zero HTTP awareness"
and proposes moving it to `thread/projection.py`. This is **partially false**.

Verified at `api/projection.py:10-31`:
```python
from ..database.crud import (
    get_pending_permission_requests,
    get_thread_execution_state,
)
from .schemas.enums import PermissionOptionKind, PermissionType
from .schemas.snapshots import (
    ExecutionTaskSnapshot,
    ThreadStateSnapshot,
    _PermissionOptionSnapshot,
    _PermissionSnapshot,
)
```

**Problem:** `projection.py` imports from `database.crud` (Layer 2 infra
service) and `api.schemas.*` (Layer 2 entry point). Moving it to `thread/`
(Layer 1) would violate the Layer 1 boundary rule: "Layer 1 imports NOTHING
from Layer 1.5, 2, or 3."

**The ADR simultaneously says** `thread/` is Layer 1 (in README.md and Layer 1
ADR) **and** proposes putting Layer-2-dependent code there. This is a
contradiction.

**Fix options:**
1. Move `projection.py` to `control/projection.py` instead (Layer 2 infra
   service -- allowed to import from database and api schemas).
2. Move it to a new `thread/projection.py` BUT refactor it to accept
   database results as parameters (dependency inversion), and replace
   api.schemas imports with domain-level types. This is significant extra
   work not accounted for in the phase estimates.
3. Keep it in `api/` under `api/projection.py` -- it is business logic but
   its consumers are all in `api/`, and its dependencies are in `api/schemas`
   and `database/`.

The same issue applies to the proposed `thread/snapshot.py` (extracted from
endpoints.py), which also does DB queries and uses api schema types.

### CRIT-02: `api/schemas/__init__.py` re-exports IPC types -- deletion of `internal.py` breaks `api.schemas` public API

The ADR says "Delete `api/schemas/internal.py` after updating all consumers.
No re-export shim." But `api/schemas/__init__.py` (lines 54-59) re-exports
all 6 types from `internal.py`:

```python
from .internal import DispatchRequest as DispatchRequest
from .internal import DispatchResponse as DispatchResponse
from .internal import ExecutionStateProjectionPayload as ExecutionStateProjectionPayload
from .internal import ExecutionTaskProjectionPayload as ExecutionTaskProjectionPayload
from .internal import HeartbeatMessage as HeartbeatMessage
from .internal import WorkerEventEnvelope as WorkerEventEnvelope
```

These are in `__all__`. Any external consumer importing
`from vaultspec_a2a.api.schemas import DispatchRequest` will break. The ADR
must explicitly update `api/schemas/__init__.py` to either:
- Remove the IPC type re-exports entirely, OR
- Re-export from the new `ipc/` location

The "no re-export shim" rule means the first option. But that changes the
`api.schemas` public API, which may have consumers the ADR hasn't audited
(test files, external tools).

### CRIT-03: Test files that import from moving paths are not accounted for

Verified test file imports that will break:

| File | Import | Breaks in phase |
|------|--------|-----------------|
| `worker/tests/test_app.py:9` | `from ...api.schemas.internal import DispatchRequest` | D-01 |
| `worker/tests/test_executor.py:22` | `from ...api.schemas.internal import DispatchRequest` | D-01 |
| `protocols/mcp/tests/test_server.py:39` | `from ....api.app import LazyWorkerSpawner, WorkerCircuitBreaker, create_app` | D-02 |

The ADR says D-01 touches "~8 files" and D-02 touches "~3 files". These
test files are not counted. The `test_server.py` import is especially
dangerous because it imports `LazyWorkerSpawner` and `WorkerCircuitBreaker`
directly from `api.app` -- after D-02 moves them to `control/`, this import
must change.

**Fix:** Add explicit test file update tasks to each phase. The phase
estimate table must account for test files.

---

## 3. Important Gaps (would cause rework or tech debt)

### IMP-01: `control/` bloat -- will become 4,000+ lines after D-02, D-03, D-05, D-06

`control/` currently has 2,504 lines across 7 files (including tests). The
ADR proposes adding:

| Decision | Lines added | New files |
|----------|------------|-----------|
| D-02 | ~530 | circuit_breaker.py, worker_management.py |
| D-03 | ~200 | dispatch.py |
| D-05 | ~400 | event_handlers.py |
| D-06 | ~150 | health.py |

Total addition: ~1,280 lines, bringing `control/` to ~3,784 lines.

`control/` was designed as "dev-tooling modules invoked via `python -m`"
(per its `__init__.py` docstring). Adding runtime production code
(circuit breaker, dispatch, event handlers, health) fundamentally changes
its character. It becomes the new monolith -- a grab bag of unrelated
infrastructure.

**Recommendation:** Consider `gateway/` as the home for D-02, D-03, D-06
(gateway-specific infrastructure). Reserve `control/` for dev-tooling.
Or accept the bloat but update the `control/__init__.py` docstring and
add a clear internal directory structure.

### IMP-02: `WorkerWatchdog.app_state` coupling is understated

The ADR says extracting the 3 inline classes is "safe." Verified at
`app.py:927-950`, `WorkerWatchdog.__init__` writes 9 attributes directly
onto `app.state`:

```python
self._app_state.worker_status = "pending"
self._app_state.worker_restart_count = 0
self._app_state.worker_last_restart_reason = None
# ... 6 more attributes
```

This `app.state` is the FastAPI `State` object -- it is tied to the
running application instance. After extraction to `control/worker_management.py`,
the `WorkerWatchdog` will still need a reference to this mutable state
object. The ADR acknowledges this ("should use a dedicated state object")
but does not plan a state object refactor. This means `control/` code
will depend on `fastapi.State` semantics, which leaks protocol concerns
into the infrastructure layer.

**Fix:** Either plan the state object refactor as part of D-02, or
explicitly document that `WorkerWatchdog` accepts `Any` for `app_state`
and the caller is responsible for providing it.

### IMP-03: D-07 route split is missing `GET /threads/{thread_id}/metadata`

The ADR's proposed route split lists:
- `health.py`, `threads.py`, `thread_state.py`, `messages.py`, `cancel.py`,
  `teams.py`, `permissions.py`, `admin.py`

But `endpoints.py` has 13 routes (verified via grep):
1. `GET /health`
2. `POST /threads`
3. `GET /threads`
4. `GET /threads/{thread_id}/metadata`  <-- MISSING from D-07
5. `GET /threads/{thread_id}/state`
6. `POST /threads/{thread_id}/messages`
7. `GET /team/status`
8. `GET /teams`
9. `POST /permissions/{id}/respond`
10. `POST /threads/{thread_id}/cancel`
11. `DELETE /threads/{thread_id}`
12. `POST /threads/{thread_id}/archive`
13. `POST /admin/shutdown`

The metadata endpoint (`GET /threads/{thread_id}/metadata`) is not mentioned
in D-07's file list. It's only 15 lines so it likely goes in `threads.py`,
but it should be explicitly assigned.

### IMP-04: D-03 dispatch consolidation is not trivial -- the 6 sites have semantic differences

The ADR claims all 6 dispatch sites follow the same pattern. Verified this
is only partially true. Key differences:

1. **Cancel bypasses circuit breaker** (`endpoints.py:1746`: "Cancel must
   bypass the circuit breaker"). The consolidated function must support an
   `bypass_circuit_breaker` parameter.

2. **429 handling differs**: `create_thread` marks the thread as FAILED on
   429. `send_message` raises 503 without marking FAILED. The control
   handler ignores 429 entirely.

3. **Post-dispatch status transitions differ**: `create_thread` sets
   `RUNNING` + `HEALTHY`. `send_message` sets `RUNNING` + `HEALTHY` with
   different `last_applied_action`. `cancel` sets `CANCELLING`. Permission
   response sets `RUNNING` with conditional `approval_status`.

4. **WS dispatch** (`app.py:486-521`) marks failed threads and broadcasts
   via WS. REST dispatch raises `HTTPException`.

A single `dispatch_to_worker()` function that handles all these cases
will need multiple conditional branches or callbacks for post-dispatch
behavior. The ADR presents this as a simple extraction but it is
effectively a strategy pattern that needs careful design.

**Fix:** Acknowledge the semantic differences in the ADR. Consider
whether `dispatch_to_worker()` handles only the HTTP call + CB
coordination, with post-dispatch behavior (status transitions, error
responses) remaining in the callers. This would still eliminate ~50% of
the duplication while keeping caller-specific policy in the callers.

---

## 4. Minor Observations

### MIN-01: `sequenced_to_dict` destination should be `ipc/serializers.py`, not `ipc/` root

The ADR says `ipc/serializers.py` which is correct, but `sequenced_to_dict`
imports `SequencedEvent` from `streaming/`. This means `ipc/` would import
from Layer 1.5 (`streaming/`). This is fine architecturally (L2-IS can
import from L1.5) but the dependency should be documented.

### MIN-02: `_trace_headers()` duplication is noted but not assigned to a decision

The ADR mentions `_trace_headers()` duplication in the problem statement
(it appears in both `endpoints.py:137-146` and `app.py:268-272`) but does
not assign its consolidation to any specific decision. It will naturally
resolve during D-07/D-08 but should be explicitly assigned.

### MIN-03: D-08 proposes `thread/diagnostics.py` for `_classify_missing_ws_thread`

This function (76 lines, `app.py:275-350`) does DB queries and checkpoint
lookups. Moving it to `thread/` (Layer 1) would violate the same boundary
as CRIT-01. It should go to `control/diagnostics.py` or stay in `api/`.

### MIN-04: No `noqa` policy compliance

`internal.py:646` and `internal.py:753` have `# noqa: B904` comments.
Per project rules, `noqa` band-aids are forbidden. These should be fixed
(add `from` clause to the `raise`) during the extraction, not carried
forward.

### MIN-05: ADR-040 referenced but does not exist

The README.md references `docs/adrs/040-layer-boundary-enforcement.md` as
the "Binding ADR." This file does not exist on disk. The layer boundary
rules are effectively defined by the Layer 1 ADR and README.md, but the
binding ADR gap means there is no single authoritative source for what
constitutes a layer violation.

---

## 5. Verified Claims

| Decision | Claim | Verification | Result |
|----------|-------|-------------|--------|
| D-01 | `worker/executor.py` imports from `api/schemas/internal` | Read `executor.py:24-29` | CONFIRMED: imports `DispatchRequest`, `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload` |
| D-01 | `worker/executor.py` imports from `api/event_adapter` | Read `executor.py:24` | CONFIRMED: imports `sequenced_to_dict` |
| D-01 | `worker/app.py` imports from `api/schemas/internal` | Read `worker/app.py:34` | CONFIRMED: imports `DispatchRequest`, `DispatchResponse` |
| D-01 | `HeartbeatMessage` is dead code | Grep for imports across codebase | CONFIRMED: zero importers outside `__init__.py` re-export |
| D-01 | `WorkerEventEnvelope` is dead code | Grep for imports across codebase | CONFIRMED: zero importers outside `__init__.py` re-export |
| D-02 | 3 inline classes in `app.py` are pure infrastructure | Read `app.py:159-234` (CB), `app.py:804-908` (Spawner), `app.py:915-964` (Watchdog) | CONFIRMED: zero L1 imports, zero domain logic |
| D-02 | `HTTPException` in `pre_dispatch()` is a protocol leak | Read `app.py:194` | CONFIRMED: `from fastapi import HTTPException` inside method |
| D-03 | 6 dispatch duplication sites | Verified sites at `endpoints.py:527-578`, `endpoints.py:1199-1249`, `endpoints.py:1588-1615`, `endpoints.py:1745-1771`, `app.py:486-521`, `app.py:570-593` | CONFIRMED: all 6 sites exist with the described pattern |
| D-04 | `projection.py` is 100% business logic | Read `projection.py:1-50` | PARTIALLY FALSE: zero HTTP awareness but imports from `database.crud` and `api.schemas.*` (see CRIT-01) |
| D-05 | `internal.py` has 4 business logic handlers | Read `internal.py:53-60` (`_handle_terminal_event`), verified existence of all 4 | CONFIRMED |
| D-05 | 3x duplicated relay orchestration | Read `internal.py:509-550`, `internal.py:664-698`, `internal.py:765-788` | CONFIRMED: identical handler call sequence in all 3 |
| D-07 | `endpoints.py` has routes that map to the proposed split | Grep for `@router.*` decorators | CONFIRMED with gap: 13 routes found, D-07 lists only 12 (missing metadata endpoint) |

---

## 6. Cross-Cutting Gap Analysis

### `__init__.py` exports
`api/schemas/__init__.py` re-exports all IPC types from `internal.py`
(lines 54-59). These must be removed when `internal.py` is deleted. See
CRIT-02.

### Circular dependency risk
No new circular dependencies identified. The proposed `ipc/` package is a
leaf -- both `api/` and `worker/` import from it, neither exports to it.
`control/` additions (dispatch, event handlers) import from `ipc/`,
`database/`, and L1 -- all allowed by the layer model.

### Thread-safety / concurrency
`WorkerCircuitBreaker` uses no locks (state mutation is single-threaded in
asyncio). `LazyWorkerSpawner` uses `asyncio.Lock` for double-checked
locking. `WorkerWatchdog` mutates `app.state` freely (single writer in
asyncio). All are safe to extract -- the concurrency model doesn't change.

### Import chains
`ipc/` as L2-IS is correct. `api/` and `worker/` both importing from
`ipc/` creates no cycle. `control/` importing from `ipc/` is fine.

---

## 7. Recommendations

1. **[CRIT-01] Fix D-04 destination**: Change `thread/projection.py` to
   `control/projection.py`. Or if the team insists on `thread/`, add a
   phase to refactor projection.py to remove its `database.crud` and
   `api.schemas` imports first. This is not optional -- it violates the
   binding Layer 1 boundary rule.

2. **[CRIT-02] Update `api/schemas/__init__.py`**: Add an explicit task
   to D-01 to remove the 6 IPC type re-exports from
   `api/schemas/__init__.py` and `api/schemas/__all__`.

3. **[CRIT-03] Enumerate test files per phase**: Add a "test file updates"
   column to the phase order table. At minimum:
   - D-01: `worker/tests/test_app.py`, `worker/tests/test_executor.py`
   - D-02: `protocols/mcp/tests/test_server.py`

4. **[IMP-01] Reconsider `control/` as the dump target**: Either create
   `gateway/` for runtime infrastructure, or explicitly update `control/`
   docstring and accept the character change.

5. **[IMP-03] Add metadata endpoint to D-07**: Assign
   `GET /threads/{thread_id}/metadata` to `routes/threads.py`.

6. **[IMP-04] Narrow D-03 scope**: Have `dispatch_to_worker()` handle
   only: `ensure_worker` + `pre_dispatch` + HTTP POST + `record_success/failure`.
   Keep post-dispatch status transitions and error responses in callers.

7. **[MIN-03] Fix D-08 `_classify_missing_ws_thread` destination**: Change
   from `thread/diagnostics.py` to `control/diagnostics.py` (same Layer 1
   violation as CRIT-01).

8. **[MIN-04] Fix `noqa` comments**: Plan to resolve the 2 `noqa: B904`
   comments in `internal.py` during D-05 extraction.
