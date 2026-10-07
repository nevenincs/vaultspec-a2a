---
tags:
  - '#adr'
  - '#database-layer'
date: '2026-03-28'
modified: '2026-10-07'
body_hash: 'sha256:6cb23d87c2fb3bf80213140241b0449611d27af1c1e7b555c589a979e826f0d4'
related:
  - '[[2026-03-28-database-layer-research]]'
  - '[[2026-03-28-post-layer2b-boundary-audit]]'
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-24-entry-point-decomposition-adr]]'
  - '[[2026-10-06-codebase-remediation-audit]]'
  - '[[2026-08-02-control-action-leases-adr]]'
---

# `database-layer` adr: `layer-2c-database-rework-handler-extraction` | (**status:** `accepted`)

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

**Prerequisite:** PR #9 (Layer 2b domain logic extraction) merged to `main`.

## Problem Statement

Layer 2b (PR #9) extracted domain types to Layer 1 and split the monolithic
CRUD module, but left two architectural debts:

- **Database layer naming debt:** The CRUD split was mechanical — modules
  carry `crud_*` prefixes that describe implementation pattern rather than
  domain ownership, and a 211-line re-export hub exists solely for backward
  compatibility. This violates the project's no-shim mandate and obscures
  the domain model the database layer serves.

- **Route handler orchestration leakage:** Four route handlers contain
  80-85% business logic (state machine transitions, idempotency deduplication,
  dispatch error recovery, repair state management). These handlers require
  business-rule understanding to modify, not just HTTP protocol knowledge.
  The same orchestration cannot be reused from CLI, worker, or MCP entry
  points without duplication — violating the layer isolation principle that
  entry points are thin protocol translators delegating to shared services.

A minor coupling violation also remains: the IPC schemas module imports the
configuration singleton for a field default value, coupling shared message
types to infrastructure configuration.

## Considerations

- The database facade pattern (`database/__init__.py`) already provides a
  stable public API. 16 consumer files import directly from `database.crud`.
  After renaming, the facade re-exports from the new modules. Consumers
  switch to importing from `database` (facade) or specific repository
  modules — no re-export shim from the old `database.crud` path.

- The repository naming convention (`thread_repository`, `permission_repository`,
  `artifact_repository`) communicates domain ownership clearly and aligns with
  established patterns in the Python ecosystem. An alternative `repositories/`
  sub-package was considered but rejected — it adds a nesting level without
  proportional benefit for 3 modules.

- Dispatch error handling across the four heavy routes is **semantically
  different**, not just structurally duplicated. The variation is driven by
  operation reversibility:
  - Thread creation and message followup mark threads FAILED on dispatch
    failure because these operations are not retryable.
  - Permission response does NOT mark FAILED on capacity/unreachable
    because the permission window must stay open for retry.
  - Cancel bypasses the circuit breaker entirely and silently absorbs all
    dispatch errors because cancellation is asynchronous and best-effort.
  A unified "policy-based" abstraction cannot collapse these semantic
  differences without becoming a policy switchboard. The correct approach
  is a low-level dispatch helper that handles the common HTTP/exception
  pattern, while each service function retains its own status-update logic
  based on operation semantics.

- Seven duplicated patterns were identified across the four heavy route
  handlers. Their disposition:

  | Pattern | Sites | Decision |
  |---------|-------|----------|
  | Idempotency key resolution | 3 | Extract to service functions (D-04) |
  | Terminal status guards | 4 (inconsistent subsets) | Standardize via constant (D-03) |
  | Dispatch try/except structure | 4 | Extract low-level helper (D-05) |
  | Repair state transitions | 8+ | Extract named functions (D-07) |
  | Plan-approval pause-cause checks | 3 imports | Move into service function (D-04) |
  | Control action creation | 6 | Remain inline (thin CRUD calls) |
  | Metadata JSON parsing | 3 | Remain inline (low ROI) |

- The existing `control/` layer already contains dispatch orchestration,
  event handlers, health assembly, projection, and snapshot enrichment from
  Layer 2a. Adding service functions follows the established pattern.

- Track C file-size violations (`acp_chat_model.py` at 1,821 lines,
  `mcp/server.py` at 1,045 lines) require class decomposition and handler
  splitting respectively. These are architecturally independent from Tracks
  A and B and carry higher blast radius. Deferring them to a dedicated PR
  (Layer 2d) avoids scope creep. The `mcp/server.py` handlers will also be
  updated to use the new service functions in that PR, achieving entry-point
  thinness symmetry across API and MCP.

- Per the prior ADR's D-12 dependency inversion, `control/` modules return
  Layer 1 dataclasses or plain result objects — not `api/schemas` Pydantic
  models. Service functions follow this same principle: they return
  infrastructure result objects that route handlers adapt to HTTP responses.

## Constraints

- Test baseline: `pytest -m core` >= 520, `pytest -m middleware` >= 574,
  full suite >= 1,094. Each phase must preserve a green suite.
- No backwards-compat re-export shims. Old import paths break loudly.
- No re-export hubs — one canonical import path per symbol.
- Modules over 1,000 lines must be split.
- No mocks, stubs, fakes, patches, skips.
- Merge commits only. Squash/rebase disabled.
- Scope boundary: `database/` (renaming + restructuring), `api/routes/`
  (handler thinning), `control/` (receiving extracted orchestration),
  `ipc/schemas.py` (settings import fix), `thread/enums.py` (terminal
  status constant). Does NOT touch Layer 1 packages beyond
  `thread/enums.py`, `providers/`, `protocols/` (except test import
  updates), `telemetry/`, `workspace/`, or Layer 3 infrastructure.

## Implementation

Seven architectural decisions organized into three tracks with explicit
phase ordering.

### Track A: Database layer rework

**D-01: Rename database modules to domain-oriented repository convention.**

Rename `crud_threads.py` to `thread_repository.py`, `crud_permissions.py` to
`permission_repository.py`, `crud_artifacts.py` to `artifact_repository.py`,
and `_crud_helpers.py` to `_helpers.py`. The naming shift communicates that
these modules own a domain's persistence concerns, not generic CRUD operations.

**D-02: Eliminate the CRUD re-export hub.**

Delete `crud.py` entirely. Update `database/__init__.py` to import from the
renamed repository modules. Update all 16 consumer files (11 production, 5
test) to import from `database` (facade) or from specific repository modules.
No re-export shim from the old `database.crud` path.

### Track B: Route handler extraction

**D-03: Define terminal status constants in `thread/enums.py`.**

The four heavy routes define terminal status sets inconsistently — some
include `ARCHIVED`, others don't. Define two constants in the canonical
enum module:

- `TERMINAL_STATUSES` — the set of states where thread execution has
  stopped (`COMPLETED`, `FAILED`, `CANCELLED`). Used for guards that check
  "can this thread accept new work."
- `NON_ACTIVE_STATUSES` — extends terminal statuses with `ARCHIVED`. Used
  for guards that check "should this thread be visible in active listings."

Both are `frozenset` values composed from enum members in the same module.
No imports from Layer 2. This is a leaf constant addition that does not
compromise Layer 1 independence.

**D-04: Extract orchestration logic to `control/` service functions.**

Create four service modules in `control/`, one per domain operation:

- **Thread service** — create-and-dispatch sequence: thread creation,
  control action journaling, repair state initialization, dispatch
  construction, error recovery with FAILED status on failure, transition
  to RUNNING on success.
- **Permission service** — permission state machine validation, idempotency
  deduplication, approval state management, dispatch with lenient error
  recovery (no FAILED status — permission window stays open for retry).
- **Message service** — thread status validation, idempotency deduplication,
  dispatch with FAILED status on failure.
- **Cancel service** — terminal status guards, idempotency, dispatch with
  circuit-breaker bypass and silent error absorption (cancellation is
  best-effort), failure recovery logging.

**Session lifecycle:** Service functions receive `AsyncSession` from the
route handler via FastAPI dependency injection. The route handler retains
ownership of the commit point. Service functions own the business logic
and state transitions within the provided session but do not call
`session.commit()` themselves. This preserves FastAPI's session management
semantics while extracting business logic.

**Return types:** Service functions return plain result dataclasses defined
in `control/` (not `api/schemas` Pydantic models). Route handlers adapt
these results to HTTP responses. This follows the dependency-inversion
pattern established by the prior ADR's D-12: `control/` never imports
from `api/`.

**D-05: Extract low-level dispatch helper.**

Extract the common dispatch try/except structure into a helper that handles
the HTTP call, exception catching, and logging. The helper does NOT make
status-update decisions — it returns a result indicating success, the
specific failure type, or the exception. Each service function inspects
the result and applies its own status-update logic based on operation
semantics.

All dispatch failures are logged. No exception is silently swallowed
without a log entry. The helper guarantees observability regardless of
which service function calls it.

**D-07: Extract named repair-state transition functions.**

Extract named repair-state transition functions to a module in `control/`
that encapsulate the domain semantics of repair state changes. This
eliminates 8+ inline repair-state updates scattered across route handlers
and gives each transition a meaningful name rather than raw enum assignments.

### Track C: Minor coupling fix

**D-06: Fix IPC schemas configuration coupling.**

Remove the `control.config.settings` import from `ipc/schemas.py`. The
`recursion_limit` field on `DispatchRequest` loses its default factory.
Update the 6 production call sites that currently rely on the implicit
default to pass `settings.graph_recursion_limit` explicitly. Test call
sites that construct `DispatchRequest` must also provide the value.

## Phase Order

| Phase | Decisions | Prerequisite | Packages touched |
|-------|-----------|-------------|------------------|
| 1 | D-01, D-02 | none | `database/`, all 16 consumers |
| 2 | D-03 | none (parallel with 1) | `thread/enums.py` |
| 3 | D-06 | none (parallel with 1-2) | `ipc/schemas.py`, 6 call sites |
| 4 | D-07 | none (parallel with 1-3) | `control/` (new module) |
| 5 | D-05 | none (parallel with 1-4) | `control/` (new module) |
| 6 | D-04 | D-02 (import paths settled), D-03, D-05, D-07 | `control/` (new service modules), `api/routes/` |

Phases 1-5 can run in parallel. Phase 6 requires all others because
service functions import from the renamed database modules (D-02), use
the terminal status constants (D-03), call the dispatch helper (D-05),
and call the repair-state functions (D-07).

## Rationale

This ADR continues the layer isolation roadmap established by PRs #2-#9.
The core architectural principle remains: entry points are thin protocol
translators, infrastructure services own business orchestration, and domain
types live in Layer 1.

Track A (D-01, D-02) completes the database layer cleanup that PR #9
explicitly deferred. The repository naming convention is a deliberate
architectural choice — it signals that persistence modules are organized
by domain aggregate, not by implementation pattern.

Track B (D-03, D-04, D-05, D-07) delivers on the entry-point thinness
promise from PR #4's ADR that was deferred for the four heavy route
handlers. Extracting orchestration to `control/` service functions makes
the business logic reusable across entry points (API, CLI, MCP, worker)
and independently testable without HTTP infrastructure.

The dispatch helper (D-05) avoids the trap of unifying semantically
different error-recovery behaviors into a single abstraction. Instead, it
extracts only the structural commonality (HTTP call + exception catching +
logging) and leaves status-update decisions to the calling service. This
preserves the operational semantics that each route handler currently
encodes while eliminating the 4x structural duplication.

D-06 fixes the last minor cross-layer coupling identified in the
post-Layer 2b boundary audit.

Deferring Track C file-size violations to Layer 2d maintains scope
discipline. That PR will also update `mcp/server.py` handlers to use the
service functions created here, achieving entry-point thinness symmetry.

## Consequences

- `database/crud.py` ceases to exist. 16 consumer files must update their
  imports. The `database/__init__.py` facade remains the stable public
  import path.

- Route handlers in `api/routes/` shrink substantially. The four heavy
  handlers (threads, permissions, messages, cancel) delegate orchestration
  to service functions. Handlers retain only: request parsing, session
  injection, service function call, result-to-response adaptation, and
  commit. Health, teams, admin, and thread_state routes are already thin
  and need no extraction.

- The `control/` package grows by 4-5 new modules (4 service modules +
  1 dispatch helper + 1 repair-state module, some may be combined). Each
  module is focused on a single domain operation or cross-cutting concern.

- `thread/enums.py` gains two constants (`TERMINAL_STATUSES`,
  `NON_ACTIVE_STATUSES`). These are leaf constants composed from enum
  members in the same module — no new dependencies.

- `ipc/schemas.py` loses its `control.config` import. 6 production call
  sites and test call sites must provide `recursion_limit` explicitly.

- `mcp/server.py` handlers remain thick in this PR. They are tracked for
  Layer 2d, where they will be updated to call the service functions
  created here. This is a deliberate, documented deferral — not an
  oversight.

- File-size violations in `acp_chat_model.py` and `mcp/server.py` remain
  after this PR. They are tracked as Layer 2d candidates.

## Validation Criteria

After all phases:

- `database/crud.py` does not exist
- All database imports resolve through `database/__init__.py` facade or
  specific repository modules — no `database.crud` import path anywhere
- `TERMINAL_STATUSES` and `NON_ACTIVE_STATUSES` defined in `thread/enums.py`,
  no inline terminal-status set literals in `api/routes/`
- `ipc/schemas.py` has zero imports from `control`
- `control/` has zero imports from `api/`
- No route handler in `api/routes/` exceeds 150 lines
- Each of the 4 heavy route handlers (threads, permissions, messages,
  cancel) is < 80 lines of code excluding imports and decorators
- Service functions in `control/` do not import from `api/`
- Service functions do not call `session.commit()`
- All dispatch failures are logged (no silent swallowing)
- No file over 1,000 lines in touched scope
- `pytest -m core` >= 520 passed
- `pytest -m middleware` >= 574 passed
- Full suite >= 1,094 passed

## Amendment (2026-10-07): one repository per aggregate

Code paths are under `src/vaultspec_a2a/`.

**Change.** All SQL and ORM access to a table lives in `database/`, in the one module that owns its aggregate:

- `thread_repository.py`: `threads`, `thread_execution_state`, status elections and the run row lock.
- `control_action_repository.py`: the `control_actions` journal, its leases, graph-receipt persistence and the continuation-queue SQL. It takes over the journal half of `permission_repository.py` and absorbs `graph_receipt_repository.py`.
- `permission_repository.py`: `permission_requests` and `permission_logs`.
- `recovery_attempt_repository.py`: `recovery_attempts`, holding the SQL now in `control/recovery.py`.
- `deletion_saga_repository.py`: `thread_deletion_saga`, holding the SQL now in `control/repositories/deletion_saga.py`.
- `run_event_repository.py`: `run_events`. It reads `threads` only through `thread_repository`.
- `cost_repository.py`: `cost_tracking`, moved out of `artifact_repository.py`. Its read surface follows the accounting decision.

`authoring_cursor_repository.py` and `runtime_identity_repository.py` keep their aggregates. `artifact_repository.py` dissolves: the artifacts half is removed (R3-F13), and permission logs and cost move as listed above.

The rules that go with this layout:

- **No sub-package.** `control/repositories/` is removed. D-01 already rejected a `repositories/` sub-package. Its rule-free SQL moves into `database/`.
- **Policy stays in `control/` and `thread/`.** Lease policy, recovery classification and transitions stay there. Repositories hold queries, conditional writes and row mapping only.
- **Dependency direction.** `database/` imports none of `control/`, `api/`, `worker/` or `graph/`. `database/reconciliation.py` moves to `control/`: it is startup orchestration, and it imports `control.recovery_authority` (`database/reconciliation.py:8-13`).
- **Facade-only imports.** Code outside `database/` imports from the `database` facade (`database/__init__.py`). This includes type-only and function-local imports. The facade exports every public repository symbol. Modules inside `database/` use relative sibling imports.
- **One lease helper.** `database/_leases.py` builds the acquire, renew, release and settle predicates for a token-and-expiry column pair, and declares the lease durations together. `control_actions`, `recovery_attempts` and `thread_deletion_saga` use it (R3-F10). This amendment does not decide whether the saga moves from its timestamp-only claim to token plus expiry, because that is a schema change.
- **CHECK predicates from one source.** The models build their `CheckConstraint`s from `WRITE_AUTHORITY_CHECKS` (`database/write_authority_schema.py`) and `RECOVERY_DEADLINE_CHECKS` (`database/control_action_schema.py`) instead of retyping them (R3-F20). Alembic revisions keep their frozen literals.

**Why.** Ownership is split today (R3-F9, R3-F10, R3-F20 and R3-F23 in `2026-10-06-codebase-remediation-audit`):

- SQL for the same tables sits in four `database/` modules and nine `control/` modules, led by 76 ORM references in `control/recovery.py`.
- `control/repositories/` contradicts D-01.
- Module names hide what the modules hold. `database/permission_repository.py:1` holds the journal, and `database/artifact_repository.py:1` holds permission logs and cost.
- `graph_receipt_repository.py` is deep-imported (`control/dispatch_receipts.py:20`).
- The facade is bypassed (`api/app.py:61-63`, `api/routes/_gateway_read_endpoints.py:48`).

**Replaces.**

- D-01's three-module list and the "3 modules" premise in the sub-package consideration. The naming convention and the rejection of a sub-package stand.
- D-02's allowance to import "from specific repository modules", and the matching Validation Criteria line. Consumers outside `database/` import from the facade only.

**What binds at acceptance.**

- Track A as amended here.
- Tracks B and C (D-03 to D-07), which describe the implemented control service layer. D-04's direction rule binds: `control/` does not import `api/`. One violation is known: `control/health.py:516` imports `api.schemas.gateway_readiness` at runtime.
- The PR-scoped clauses are historical: the PR #9 prerequisite, the test-count baselines, the merge-commit rule, the phase order and the Layer 2d deferral. The 1,000-line module limit is owned by the pylint gate (`pyproject.toml:552`).
