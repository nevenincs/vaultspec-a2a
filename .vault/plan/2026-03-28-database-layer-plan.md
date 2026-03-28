---
tags:
  - '#plan'
  - '#database-layer'
date: '2026-03-28'
related:
  - '[[2026-03-28-database-layer-adr]]'
  - '[[2026-03-28-database-layer-research]]'
  - '[[2026-03-28-post-layer2b-boundary-audit]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `database-layer` `phase-1` plan

Layer 2c: database layer rework + route handler extraction. Implements ADR
decisions D-01 through D-07 across 6 phases. Track A renames database
modules to repository convention and eliminates the CRUD re-export hub.
Track B extracts route handler orchestration to `control/` service
functions. Track C fixes IPC schemas configuration coupling.

## Proposed Changes

Per the ADR, this plan delivers three tracks:

- **Track A (D-01, D-02):** Rename `crud_*.py` modules to repository
  convention, delete the `crud.py` re-export hub, update
  `database/__init__.py` facade and all 16 consumer files.
- **Track B (D-03, D-04, D-05, D-07):** Add terminal status constants to
  `thread/enums.py`, extract dispatch helper, extract repair-state
  transition functions, extract 4 service functions to `control/`, thin
  route handlers.
- **Track C (D-06):** Remove `control.config.settings` import from
  `ipc/schemas.py`, update 7 production call sites.

## Tasks

- **Phase 1: Database module renaming (D-01, D-02)** — status: `pending`
  1. Rename `database/crud_threads.py` to `database/thread_repository.py`
  1. Rename `database/crud_permissions.py` to `database/permission_repository.py`
  1. Rename `database/crud_artifacts.py` to `database/artifact_repository.py`
  1. Rename `database/_crud_helpers.py` to `database/_helpers.py`
  1. Update internal cross-references within database package: each renamed
     repository module imports from `._crud_helpers` — change to `._helpers`.
     Also update any cross-imports between repository modules.
  1. Update `database/__init__.py` facade to import from renamed modules.
     The `__all__` list and public symbols remain unchanged — only the
     internal import statements change.
  1. Delete `database/crud.py`
  1. Update all 16 consumer files to import from `database` (facade) or
     specific repository modules — not `database.crud`:
     - `api/routes/threads.py`
     - `api/routes/permissions.py`
     - `api/routes/messages.py`
     - `api/routes/cancel.py`
     - `api/routes/teams.py`
     - `api/routes/thread_state.py`
     - `api/ws_dispatch.py`
     - `control/dispatch.py`
     - `control/event_handlers.py`
     - `control/diagnostics.py`
     - `control/projection.py`
     - `api/tests/test_endpoints.py`
     - `api/tests/test_internal.py`
     - `api/tests/test_projection.py`
     - `protocols/mcp/tests/test_server.py`
     - `database/tests/test_database.py`
  1. Update module docstrings in renamed files to reflect domain-oriented
     names (e.g., "Thread persistence operations" not "CRUD thread
     operations")
  1. Verify no remaining `from.*database\.crud import` anywhere in codebase
  1. Run full test suite — must pass at baseline
  1. Commit

- **Phase 2: Terminal status constants (D-03)** — status: `pending`
  1. Add to `thread/enums.py`:
     - `TERMINAL_STATUSES = frozenset({ThreadStatus.COMPLETED, ThreadStatus.FAILED, ThreadStatus.CANCELLED})`
       — thread execution has stopped; used for "can this thread accept new work" guards
     - `NON_ACTIVE_STATUSES = TERMINAL_STATUSES | frozenset({ThreadStatus.ARCHIVED})`
       — extends terminal with post-terminal archival; used for "should this
       thread be treated as inactive" guards
  1. Update `api/routes/permissions.py` to use `TERMINAL_STATUSES` (it
     currently checks `{COMPLETED, FAILED, CANCELLED}` — correct, no ARCHIVED)
  1. Update `api/routes/messages.py` to use `NON_ACTIVE_STATUSES` (it
     currently includes ARCHIVED in its terminal check)
  1. Update `api/routes/cancel.py` to use `NON_ACTIVE_STATUSES` (it
     currently includes ARCHIVED)
  1. Update `api/routes/threads.py` to use `TERMINAL_STATUSES` where
     applicable (archive guard checks `{COMPLETED, FAILED, CANCELLED}`)
  1. Grep for other inline `ThreadStatus` set-literal comparisons across
     the codebase and update any found
  1. Run full test suite
  1. Commit

- **Phase 3: IPC schemas fix (D-06)** — status: `pending`
  1. Remove `from ..control.config import settings` from `ipc/schemas.py`
  1. Change `recursion_limit` field on `DispatchRequest` from
     `Field(default_factory=lambda: settings.graph_recursion_limit)` to a
     plain field with no default
  1. Update all 7 production call sites to pass
     `recursion_limit=settings.graph_recursion_limit` explicitly:
     - `api/routes/threads.py` (already provides it — verify)
     - `api/routes/permissions.py`
     - `api/routes/messages.py`
     - `api/routes/cancel.py`
     - `api/ws_dispatch.py` (2 DispatchRequest constructions)
     - `control/dispatch.py` (`redispatch_reconciling_threads()`)
  1. Update test call sites in `worker/tests/test_executor.py` and
     `worker/tests/test_app.py` that construct `DispatchRequest` without
     providing `recursion_limit`
  1. Run full test suite
  1. Commit

- **Phase 4: Repair-state transition functions (D-07)** — status: `pending`
  1. Create `control/repair_transitions.py` with named functions matching
     the exact repair-state patterns found in route handlers:
     - `mark_ingest_requested(db, thread_id)` — sets HEALTHY /
       last_requested_action=INGEST (used before dispatch in threads.py)
     - `mark_ingest_applied(db, thread_id)` — sets HEALTHY /
       last_applied_action=INGEST (used after successful dispatch)
     - `mark_permission_response_requested(db, thread_id)` — sets
       PAUSED_RESUMABLE / last_requested_action=PERMISSION_RESPONSE_SUBMITTED
     - `mark_permission_response_applied(db, thread_id)` — sets HEALTHY /
       last_requested_action=PERMISSION_RESPONSE_SUBMITTED
     - `mark_message_followup_requested(db, thread_id)` — sets HEALTHY /
       last_requested_action=MESSAGE_FOLLOWUP_REQUESTED
     - `mark_message_followup_applied(db, thread_id)` — sets HEALTHY /
       last_applied_action=MESSAGE_FOLLOWUP_REQUESTED
     - `mark_cancel_requested(db, thread_id)` — sets CANCEL_PENDING /
       last_requested_action=CANCEL
  1. Each function calls `set_thread_repair_state()` from the database
     layer with the exact enum values currently used inline
  1. Update route handlers to call the named functions instead of inline
     `set_thread_repair_state()` calls
  1. Run full test suite
  1. Commit

- **Phase 5: Dispatch helper (D-05)** — status: `pending`
  1. Add `DispatchOutcome` dataclass to `control/dispatch.py`:
     - `success: bool`
     - `failure_type: str | None` (one of: "circuit_open", "at_capacity",
       "unreachable", "rejected", or None on success)
     - `exception: Exception | None`
     - `detail: str | None`
  1. Add `safe_dispatch()` function to `control/dispatch.py`:
     - Signature: `async def safe_dispatch(worker_client, dispatch_request, circuit_breaker, worker_spawner, *, bypass_circuit_breaker=False, trace_headers=None) -> DispatchOutcome`
     - Calls `dispatch_to_worker()` (existing function in same module)
     - Catches the 4 dispatch exception types and returns `DispatchOutcome`
       with appropriate `failure_type`
     - Logs every failure at WARNING level with the exception detail
     - Does NOT make status-update decisions
     - Does NOT raise — always returns
  1. Run full test suite (existing dispatch tests must pass — new function
     is additive)
  1. Commit

- **Phase 6: Service function extraction (D-04)** — status: `pending`
  1. Create `control/thread_service.py`:
     - `async def create_and_dispatch_thread(db, body, circuit_breaker, worker_spawner, worker_client, recursion_limit, trace_headers) -> ThreadCreationResult`
     - Moves orchestration from `api/routes/threads.py`
       `create_thread_endpoint`: thread creation, control action journaling,
       repair state via Phase 4 functions, dispatch via `safe_dispatch()`,
       marks FAILED on dispatch failure, transitions to RUNNING on success
     - `ThreadCreationResult` dataclass: `thread_id: str`, `status: str`,
       `nickname: str | None`, `dispatched: bool`,
       `error_detail: str | None`
     - Does NOT call `db.commit()`
     - Does NOT import from `api/`
     - `recursion_limit` passed as parameter (no `settings` access)
  1. Create `control/permission_service.py`:
     - `async def respond_to_permission(db, request_id, option_id, idempotency_key, aggregator, circuit_breaker, worker_spawner, worker_client, recursion_limit, trace_headers) -> PermissionResult`
     - Moves orchestration from `api/routes/permissions.py`: permission
       lookup with fallback extraction, thread validation, idempotency
       deduplication, state machine checks (APPLIED/SUPERSEDED/EXPIRED
       early returns), control action creation, approval state management,
       repair state via Phase 4 functions, dispatch via `safe_dispatch()`
       (lenient — does NOT mark FAILED on capacity/unreachable), aggregator
       resolution
     - `PermissionResult` dataclass: `action_id: str`,
       `action_status: str`, `thread_id: str`, `thread_status: str`,
       `dispatched: bool`, `error_detail: str | None`
     - Does NOT call `db.commit()`
  1. Create `control/message_service.py`:
     - `async def send_followup_message(db, thread_id, content, agent_id, idempotency_key, circuit_breaker, worker_spawner, worker_client, recursion_limit, trace_headers) -> MessageResult`
     - Moves orchestration from `api/routes/messages.py`: thread lookup,
       terminal/non-active status guard, idempotency deduplication, control
       action creation, repair state via Phase 4 functions, dispatch via
       `safe_dispatch()` (marks FAILED on capacity/unreachable/rejected),
       status transition to RUNNING
     - `MessageResult` dataclass: `action_id: str`, `thread_id: str`,
       `thread_status: str`, `dispatched: bool`,
       `error_detail: str | None`
     - Does NOT call `db.commit()`
  1. Create `control/cancel_service.py`:
     - `async def cancel_thread(db, thread_id, idempotency_key, circuit_breaker, worker_spawner, worker_client, trace_headers) -> CancelResult`
     - Moves orchestration from `api/routes/cancel.py`: terminal status
       guard, idempotency deduplication, control action creation, repair
       state via Phase 4 functions, dispatch via `safe_dispatch()` with
       `bypass_circuit_breaker=True` (lenient — does NOT mark FAILED),
       failure recovery logging
     - `CancelResult` dataclass: `action_id: str`, `thread_id: str`,
       `cancelled: bool`, `thread_status: str`,
       `error_detail: str | None`
     - Does NOT call `db.commit()`
     - No `recursion_limit` needed (cancel dispatch does not set it)
  1. Thin `api/routes/threads.py`:
     - `create_thread_endpoint` becomes: parse request, extract trace
       headers, call `create_and_dispatch_thread()`, commit,
       `mark_worker_connected(request)` if dispatched, adapt result to
       `CreateThreadResponse`
     - Other endpoints (`list_threads`, `get_thread_metadata`,
       `delete_thread`, `archive_thread`) are already thin — leave as-is
  1. Thin `api/routes/permissions.py`:
     - `respond_to_permission_endpoint` becomes: parse headers, compute
       idempotency key, call `respond_to_permission()`, commit,
       `mark_worker_connected(request)` if dispatched, adapt result to
       response schema
  1. Thin `api/routes/messages.py`:
     - `send_message_endpoint` becomes: parse headers, compute idempotency
       key, call `send_followup_message()`, commit,
       `mark_worker_connected(request)` if dispatched, adapt result to
       `SendMessageResponse`
  1. Thin `api/routes/cancel.py`:
     - `cancel_thread_endpoint` becomes: parse headers, compute idempotency
       key, call `cancel_thread()`, commit,
       `mark_worker_connected(request)` if dispatched, adapt result to
       `CancelThreadResponse`
  1. Verify no circular imports: `python -c "from vaultspec_a2a.api.routes import threads, permissions, messages, cancel"`
  1. Verify no `api.` imports in new service modules
  1. Verify no `db.commit()` calls in service modules
  1. Run full test suite
  1. Commit

## Parallelization

Phases 1-5 are independent and can run in parallel. Phase 6 depends on
all previous phases because service functions import from renamed database
modules (Phase 1), use terminal status constants (Phase 2), use
`recursion_limit` parameter pattern (Phase 3), call repair-state functions
(Phase 4), and call the dispatch helper (Phase 5).

Within Phase 6, the four service function extractions are independent and
can be implemented by parallel subagents, each working on one route+service
pair.

## Verification

- **Boundary validation:**
  - Zero `from.*database\.crud import` anywhere in the codebase
  - Zero imports from `api/` in any `control/` module
  - Zero imports from `control` in `ipc/schemas.py`
  - No file over 1,000 lines in touched scope
- **Handler thinness:** Each of the 4 heavy route handlers < 80 lines
  (excluding imports/decorators). Verify with `wc -l`.
- **Service function isolation:**
  - Grep service modules for `api.` imports — must find zero
  - Grep for `db.commit()` in service modules — must find zero
  - Grep for `from.*control\.config import settings` in service modules —
    must find zero (use `recursion_limit` parameter instead)
- **Dispatch logging:** Grep `safe_dispatch` for log calls on every
  exception path — every failure type must have a log entry.
- **Circular imports:** `python -c "from vaultspec_a2a.api.routes import threads, permissions, messages, cancel"` must succeed.
- **Test baseline:** `pytest -m core` >= 520, `pytest -m middleware` >= 574,
  full suite >= 1,094.
- **Functional:** The HTTP API behavior must be identical before and after
  extraction. No new error codes, no changed response shapes, no altered
  status transitions.
