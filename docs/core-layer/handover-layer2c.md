# Layer 2c — Database Layer Rework + Handler Extraction — Handover

**GitHub repo:** wgergely/vaultspec-a2a
**GitHub Issue:** wgergely/vaultspec-a2a#10
**Prerequisite:** PR #9 (Layer 2b domain logic extraction) merged to `main`.
**Remote name:** `vaultspec-a2a` (NOT `origin`)
**Merge strategy:** Merge commits only. Squash and rebase are disabled.

## History

| PR | Layer | What it did | Status |
|----|-------|-------------|--------|
| #2 | Control layer | CLI/Justfile separation, `control/` package | MERGED |
| #3 | Layer 1 (core) | Decomposed monolithic `core/` into `thread/`, `context/`, `team/`, `graph/`, `streaming/`, `lifecycle/` | MERGED |
| #4 | Layer 2a (entry points) | Split `endpoints.py` into 8 route modules. Split `executor.py` into 3. Extracted `ipc/`, `control/` runtime modules | MERGED |
| #9 | Layer 2b (domain logic) | Extracted domain enums/transitions/snapshots to Layer 1. Split `crud.py`. Dependency-inverted `control/` → `api/` via Layer 1 dataclasses. Fixed `utils/` inversions | MERGED (expected) |
| **Next** | **Layer 2c** | **Database layer rework + route handler extraction** | **NOT STARTED** |

## What Layer 2b delivered

- `thread/enums.py` — 6 domain enums + `InvalidTransitionError`
- `thread/transitions.py` — `_VALID_TRANSITIONS` state machine
- `thread/snapshots.py` — 8 D-12 snapshot dataclasses, 3 projection dataclasses, pure functions, predicates, constants
- `thread/models.py` — `PlanEntry` frozen dataclass
- `database/crud.py` split into `crud_threads.py` (359L), `crud_permissions.py` (299L), `crud_artifacts.py` (126L), `_crud_helpers.py` (130L)
- `utils/` layer inversions fixed; `AgentState` moved to `graph/enums.py`; dead code deleted
- `control/` has zero imports from `api/`

Test baseline: 520 core, 574 middleware, 1094 total — all passing.

## Post-Layer 2b boundary audit findings (2026-03-28)

Full audit at `.vault/audit/2026-03-28-post-layer2b-boundary-audit.md`.
Zero critical violations. The remaining issues:

### Moderate (4)

**1. Route handler orchestration leakage** — `api/routes/threads.py`
(431L), `permissions.py` (319L), `messages.py` (215L), `cancel.py`
(166L) contain multi-step orchestration: control action creation, repair
state management, idempotency deduplication, dispatch error recovery,
approval state transitions. These handlers need business-rule
understanding to modify, not just HTTP protocol knowledge.

**2. Direct database CRUD calls in route handlers** — All route handlers
directly call `database.crud` functions and manage `AsyncSession`
lifecycle (explicit `db.commit()` calls). The HTTP layer is coupled to
the data access pattern.

**3. `settings` God object** — The composed `Settings` singleton
(`DomainConfig` + `InfraConfig`) is imported by 34 files. Every
consumer gets access to everything — a provider sees database URLs, a
worker sees API keys it doesn't need.

**4. `acp_chat_model.py` at 1,821 lines** — 82% over the 1,000-line
mandate. Contains ACP subprocess management, JSON-RPC protocol,
streaming parser, permission bridge, and session lifecycle in one file.

### Minor (3 remaining)

**1. `ipc/schemas.py` imports `settings` from `control.config`** — IPC
schemas should be independent of configuration. The import is used for
a default field value.

**2. `protocols/mcp/server.py` at 1,045 lines** — Barely over the
1,000-line mandate. 9 MCP tool handlers in one file.

**3. Missing `.dockerignore`** — Build context sends entire repo to
Docker. Mitigated by selective `COPY` in Dockerfiles but wasteful.

## The problem: database layer naming and structure

PR #9 split `crud.py` mechanically to unblock the domain logic
extraction. The result works but is not production-quality:

- `crud.py` is now a 211-line re-export hub that exists solely so 14
  consumer files that `from database.crud import X` don't break
- `_crud_helpers.py` (130L) holds generic persistence utilities
- `crud_threads.py` (359L) exceeds the ~300L target
- The `crud_*` naming convention is not descriptive of domain ownership

This must be reworked with proper domain-oriented naming and the
re-export hub eliminated.

## The problem: route handler business logic

Route handlers in `api/routes/` contain 100-300 lines of orchestration
logic each. They directly manage database sessions, create control
actions, handle dispatch errors, and manage state transitions. If the
same flow needed to run from a CLI or message queue, the logic would
need duplication.

The fix: extract orchestration into `control/` service functions. Route
handlers become thin protocol translators (<30 lines each).

## Mandatory reading before starting

1. `src/vaultspec_a2a/README.md` — Living architecture doc (up to date)
2. `.vault/audit/2026-03-28-post-layer2b-boundary-audit.md` — Fresh
   6-section boundary audit with exact file paths and line numbers
3. `.vault/adr/2026-03-27-domain-logic-extraction-adr.md` — Layer 2b
   ADR for methodology reference
4. `.vault/adr/2026-03-24-entry-point-decomposition-adr.md` — Layer 2a
   ADR (references handler extraction as future work)

## Rules (non-negotiable, learned from PRs #2-#9)

- No backwards-compat shims. Old import paths break loudly.
- No deferral. If the plan says decompose, decompose.
- Stay in scope. Define scope before starting.
- Modules over 1,000 lines must be split.
- No re-export shims. One canonical import path per symbol.
- Test for each phase. Preserve green test suite.
- No mocks, stubs, fakes, patches, skips.
- Commit after every phase. Push continuously.
- Merge commits only. Squash/rebase disabled.
- `ty` type checker uses `# ty: ignore[rule-name]` syntax. Lacks
  Pydantic plugin (astral-sh/ty#2403) — use
  `# ty: ignore[invalid-argument-type]` at Pydantic/Protocol call sites.
- No `# noqa` band-aids. Fix root causes.

## Suggested work plan

### Track A: Database layer rework (user-flagged priority)

1. Rename `crud_threads.py` → domain-oriented name (e.g.,
   `thread_repository.py` or adopt a `repositories/` sub-package)
2. Rename `crud_permissions.py` → e.g., `permission_repository.py`
3. Rename `crud_artifacts.py` → e.g., `artifact_repository.py`
4. Rename `_crud_helpers.py` → `_helpers.py` or fold into sub-package
5. Eliminate `crud.py` re-export hub (211L) — update all 14 consumer
   files to import from canonical module paths
6. Update `database/__init__.py` facade
7. Verify all tests pass

### Track B: Route handler extraction

1. Create `control/thread_service.py` — `create_and_dispatch_thread()`,
   consolidating the 170L orchestration from `threads.py`
2. Create `control/permission_service.py` —
   `respond_to_permission()`, consolidating 260L from `permissions.py`
3. Create `control/message_service.py` —
   `send_followup_message()`, consolidating from `messages.py`
4. Extract cancel orchestration from `cancel.py`
5. Each route handler becomes <30 lines: parse request, call service,
   format response
6. Fix `ipc/schemas.py` settings import (compute default at call site)

### Track C: File size violations (if time permits)

1. Split `acp_chat_model.py` (1,821L) into `acp_protocol.py`,
   `acp_process.py`, `acp_chat_model.py`
2. Split `mcp/server.py` (1,045L) into per-tool modules under
   `mcp/tools/`
3. Add `.dockerignore`

## Test baseline targets

```bash
pytest -m core        → >= 520
pytest -m middleware   → >= 574
pytest                → >= 1,094
```

## Boundary validation commands

```bash
# Layer 1 must not import Layer 2+
grep -rn 'from.*api\.\|from.*cli\.\|from.*worker\.\|from.*database\.\|from.*providers\.\|from.*control\.' \
  src/vaultspec_a2a/thread/ src/vaultspec_a2a/context/ src/vaultspec_a2a/team/ \
  src/vaultspec_a2a/graph/ src/vaultspec_a2a/streaming/ src/vaultspec_a2a/lifecycle/ \
  --include='*.py' | grep -v '/tests/' | grep -v __pycache__

# control/ must not import from api/
grep -rn 'from.*api\.' src/vaultspec_a2a/control/ --include='*.py' \
  | grep -v tests/ | grep -v __pycache__

# utils/ must not import from control/
grep -rn 'from.*control\.' src/vaultspec_a2a/utils/ --include='*.py' \
  | grep -v tests/ | grep -v __pycache__

# No file over 1,000 lines in touched scope
find src/vaultspec_a2a/database src/vaultspec_a2a/control src/vaultspec_a2a/api/routes \
  -name '*.py' -exec wc -l {} + | sort -rn | head -10
```

## Scope boundary

Touches: `database/` (renaming + restructuring), `api/routes/` (handler
extraction), `control/` (receiving extracted orchestration).

Does NOT touch: Layer 1 (`thread/`, `context/`, `team/`, `graph/`,
`streaming/`, `lifecycle/`), `providers/` (unless Track C), `telemetry/`,
`workspace/`.

## After this PR

- **Layer 3 infrastructure config** — Docker password fix, compose
  consolidation, Justfile audit, `.dockerignore`
- **Backend readiness tracks** — observability pivot (log/trace
  correlation, runtime authority ADR, verifier diagnostics, Docker
  provider certification)

## Remaining monoliths (monitor, don't fix unless in scope)

| File | Lines | Notes |
|------|-------|-------|
| `providers/acp_chat_model.py` | 1,821 | Track C candidate |
| `protocols/mcp/server.py` | 1,045 | Track C candidate |
| `control/verify.py` | 894 | Dev-tooling, splittable |
| `api/websocket.py` | 719 | Protocol code, high cohesion |
| `control/config.py` | 632 | 75 env fields, no logic |
| `control/worker_management.py` | 604 | Process supervision |

## Process

Use the vaultspec framework: research → ADR → plan → execute → review.
Run the full 6-section boundary audit prompt before starting research,
and again after the final phase to validate.
