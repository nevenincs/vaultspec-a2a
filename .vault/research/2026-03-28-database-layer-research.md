---
tags:
  - '#research'
  - '#database-layer'
date: '2026-03-28'
related:
  - '[[2026-03-28-post-layer2b-boundary-audit]]'
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `database-layer` research: `layer-2c-database-rework-handler-extraction`

Research for the Layer 2c PR covering three tracks: database layer renaming
(Track A), route handler extraction (Track B), and file size violations
(Track C). Conducted against the post-Layer 2b codebase (PR #9 merged).

## Findings

### Track A: Database Layer Current State

**Facade architecture (post-Layer 2b):**

- `database/__init__.py` (145L) exports 54 symbols from submodules
- `database/crud.py` (211L) is a pure re-export hub — 42 symbols, zero logic
- `database/crud_threads.py` (359L) — 13 exported functions (thread CRUD,
  status transitions, repair/approval state, execution state, metadata)
- `database/crud_permissions.py` (299L) — 13 exported functions (permission
  lifecycle, control action journal, idempotency lookups)
- `database/crud_artifacts.py` (127L) — 8 exported functions (artifacts,
  permission logs, cost tracking)
- `database/_crud_helpers.py` (131L) — 10 internal symbols (`save_model`,
  `_utcnow`, `_UnsetType`/`_UNSET`, 6 coercion helpers)

**Consumer analysis (22 files total):**

- 18 production files import via `from database.crud import X`
- 4 test files import via `from database.crud import X`
- 1 test file (`database/tests/test_database.py`) imports 24 symbols from
  `..crud` (relative)
- Most-imported functions: `get_thread` (6 files), `update_thread_status`
  (6 files), `create_control_action` (4 files), `set_thread_repair_state`
  (4 files)

**Key finding:** The `crud.py` re-export hub (211L) exists solely for backward
compatibility. All 22 consumers import through it. Eliminating it requires
updating all 22 files to import from domain-specific modules directly, or
updating the `database/__init__.py` facade to re-export from the new modules
(keeping a single stable import path).

**Recommended approach:** Rename the domain modules, update
`database/__init__.py` to re-export from the renamed modules, delete
`crud.py`. Consumers that import `from database.crud import X` update to
`from database import X` (already supported by the facade). Consumers that
import `from database import X` need no changes.

### Track B: Route Handler Orchestration Leakage

**Route handler analysis:**

| Route | Total | Protocol | Business | % Business |
|-------|-------|----------|----------|-----------|
| `threads.py` | 431L | ~60L | ~371L | 86% |
| `permissions.py` | 314L | ~10L | ~304L | 97% |
| `messages.py` | 215L | ~15L | ~200L | 93% |
| `cancel.py` | 166L | ~8L | ~158L | 95% |
| `health.py` | 82L | ~82L | 0L | 0% (thin) |
| `teams.py` | 102L | ~102L | 0L | 0% (thin) |
| `admin.py` | 15L | ~15L | 0L | 0% (thin) |
| `thread_state.py` | 157L | ~150L | ~7L | 4% (thin) |

Total extractable business logic: ~639 lines across 4 routes.

**Duplicated patterns identified (7):**

- **Idempotency key resolution** — 3 instances (permissions, messages, cancel).
  Each computes `hashlib.sha256(...)` with different key formats, then calls
  `get_control_action_by_idempotency_key`. 18 lines per instance.

- **Terminal status check** — 5 instances across 4 routes. Different subsets
  of `ThreadStatus` enum (messages/cancel include `ARCHIVED`, permissions
  doesn't). Each is a 5-14 line inline set literal comparison.

- **Dispatch error recovery** — 4 instances (13-32 lines each, 97 total).
  Policy varies: threads/messages/permissions fail-fast on `CircuitOpenError`,
  cancel bypasses circuit breaker. All catch `WorkerAtCapacityError`,
  `WorkerUnreachableError`, `WorkerDispatchRejectedError` with different
  recovery behavior (mark FAILED vs. silent swallow).

- **Control action creation** — 6 calls across 4 routes. Straightforward
  CRUD, no extraction needed.

- **Repair state updates** — 8+ calls across 4 routes. Each sets
  `repair_status`, `execution_readiness`, `last_requested_action` with
  route-specific enum values.

- **PLAN_APPROVAL_PAUSE_CAUSES** — imported in 3 files (permissions,
  event_handlers, projection). Permissions route should delegate to control
  layer.

- **Metadata JSON parsing** — 3 instances (7 lines each). Low ROI extraction.

**Existing control/ layer (4,754L total):**

Already contains service modules from Layer 2a extraction:
`dispatch.py` (264L, dispatch orchestration), `event_handlers.py` (467L,
worker event relay), `health.py` (170L, health assembly),
`projection.py` (337L, state projection), `snapshot.py` (202L, snapshot
enrichment), `circuit_breaker.py` (98L), `worker_management.py` (604L),
`verify.py` (894L), `diagnostics.py` (150L), `hooks.py` (191L),
`doctor.py` (383L), `config.py` (632L), `db.py` (312L).

**Recommended extraction approach:**

Rather than creating thin service-layer wrappers that merely relocate the
same code, focus on extracting the **duplicated cross-cutting concerns**
into reusable control-layer functions:

- `TERMINAL_STATUSES` constant in `thread/enums.py` — eliminates 5 inline
  set literals
- Idempotency deduplication helper in `control/` — eliminates 3x pattern
- Dispatch error policies — consolidate 4x handlers into policy-based
  dispatch (strict/lenient/cancel)
- Named repair-state transition functions in `control/` — eliminates 8+
  inline repair updates

The full "extract orchestration to service functions, handlers become <30
lines" approach from the handover is achievable but requires careful design
around dispatch error policy variation. Each route has subtly different
error recovery behavior that cannot be collapsed into a single function
without introducing policy parameters.

### Track C: File Size Violations

**`providers/acp_chat_model.py` (1,821L) — 82% over mandate:**

6 distinct responsibility sections with natural split boundaries:

- Lines 1-155: ACP subprocess management (constants, capability mappings,
  `_AcpSessionContext`)
- Lines 344-408: Streaming & message parsing (`_yield_chunks`)
- Lines 649-732: JSON-RPC protocol dispatch (`_process_stdout_loop`,
  `_dispatch_packet`, `_handle_client_response`, `_handle_server_rpc`)
- Lines 786-865: Permission bridge (`_on_request_permission`)
- Lines 1257-1667: Session lifecycle (`_initialize_session`,
  `_setup_session`, `_authenticate_rpc`, `_cleanup_session`)
- Lines 1694-1821: Public API methods (`fork_session`, `list_sessions`,
  `set_mode`, etc.)

All sections are methods on the `AcpChatModel` class, making extraction
non-trivial — requires mixin pattern or delegation to helper objects.

**`protocols/mcp/server.py` (1,045L) — 4.5% over mandate:**

11 MCP tool handlers (not 9 as previously documented):
`start_thread` (142L), `get_thread_status` (117L), `list_threads` (86L),
`respond_to_permission` (83L), `send_message` (77L), `get_team_status` (71L),
`cancel_thread` (62L), `archive_thread` (61L), `get_pending_permissions` (59L),
`list_team_presets` (58L), `delete_thread` (47L).

Natural grouping: thread lifecycle (4 handlers), thread status (2), messaging
(2), discovery (3). Each handler is primarily HTTP request wrapping with
error handling — low cohesion between handlers, easy to split.

**`ipc/schemas.py` settings import:**

Line 14 imports `settings` from `control.config`. Used at line 44:
`recursion_limit: int = Field(default_factory=lambda: settings.graph_recursion_limit)`.
Fix: make `recursion_limit` a required field or compute default at call site.

**File size ranking in scope (top 10):**

| File | Lines |
|------|-------|
| `database/tests/test_database.py` | 1,018 |
| `control/verify.py` | 894 |
| `control/config.py` | 632 |
| `control/worker_management.py` | 604 |
| `control/event_handlers.py` | 467 |
| `api/routes/threads.py` | 431 |
| `control/doctor.py` | 383 |
| `database/crud_threads.py` | 359 |
| `control/projection.py` | 337 |
| `api/routes/permissions.py` | 314 |

### Scope Assessment

**Track A (database renaming):** Low risk, mechanical. 22 consumer files to
update. Recommended: rename modules, update facade, delete re-export hub.
Clear dependency chain, no behavioral changes.

**Track B (handler extraction):** Medium risk. 639 lines of extractable
business logic. Duplicated patterns are clear extraction targets. Full
service-layer extraction is the goal but dispatch error policy variation
requires careful interface design. Recommend phased approach: constants
first, then cross-cutting helpers, then per-route service functions.

**Track C (file size violations):** High effort, lower priority. `acp_chat_model.py`
split requires class decomposition (mixin or delegation). `mcp/server.py`
split is straightforward but barely over threshold. `ipc/schemas.py` fix
is trivial. Recommend: fix `ipc/schemas.py` in this PR, defer
`acp_chat_model.py` and `mcp/server.py` splits to a dedicated PR.

### Test Baseline (post-Layer 2b)

- `pytest -m core` >= 520
- `pytest -m middleware` >= 574
- Full suite >= 1,094
