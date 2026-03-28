---
tags:
  - '#audit'
  - '#domain-logic'
date: '2026-03-28'
related:
  - '[[2026-03-27-domain-logic-extraction-adr]]'
  - '[[2026-03-27-domain-logic-plan]]'
---

# post-layer-2b boundary audit

Systematic three-layer architecture audit of the vaultspec-a2a codebase after
PR #9 (Layer 2b domain logic extraction). This audit focuses on violations
that **remain** after D-01 through D-12 were implemented.

## Layer Classification

For this audit, the packages are classified as follows:

- **Layer 1 (Library/Domain):** `thread/`, `graph/`, `context/`, `lifecycle/`,
  `streaming/`, `team/`, `workspace/`, `utils/`, `domain_config.py`
- **Layer 2 (Entry Points + Infrastructure Services):** `api/`, `cli/`,
  `worker/`, `control/`, `database/`, `providers/`, `protocols/`, `ipc/`,
  `telemetry/`
- **Layer 3 (Infrastructure Config):** `docker/`, `docker-compose*.yml`,
  `Justfile`, `alembic.ini`

---

## Section 1: Library Independence (Layer 1 Integrity)

### What was fixed by PR #9

- Domain enums moved from `database/crud.py` to `thread/enums.py`
- State machine extracted to `thread/transitions.py`
- Pure snapshot logic extracted to `thread/snapshots.py`
- `PlanEntry` moved from `api/schemas/events.py` to `thread/models.py`
- `utils/logging.py` and `utils/trace.py` no longer import from `control.config`
  at runtime (use protocol-typed settings parameters instead)
- `AgentState` moved from `utils/enums.py` to `graph/enums.py`
- `lifecycle/reconciliation.py` imports from `thread/enums.py`, private enum
  copies deleted
- `vowel_counter.py` deleted, `utils/tests/` marker fixed to `core`

### Remaining violations: NONE

Layer 1 packages (`thread/`, `graph/`, `context/`, `lifecycle/`, `streaming/`,
`team/`, `workspace/`, `utils/`) have zero imports from `control/`, `api/`,
`database/`, or `worker/`. The `domain_config.py` module at package root uses
only `pydantic` and `pydantic_settings` — no infrastructure imports.

Layer 1 is independently importable without any running services.

---

## Section 2: Entry Point Thinness (Layer 2 Integrity)

### Violation: Business logic embedded in route handlers

**Layer:** 2 (Entry Points)
**File(s):** `src/vaultspec_a2a/api/routes/threads.py` (431 lines),
`src/vaultspec_a2a/api/routes/permissions.py` (319 lines),
`src/vaultspec_a2a/api/routes/messages.py` (215 lines),
`src/vaultspec_a2a/api/routes/cancel.py` (166 lines)
**Severity:** Moderate
**Description:** Route handlers perform multi-step orchestration sequences
that go beyond protocol translation: creating control actions, setting repair
state, computing idempotency keys, constructing dispatch requests, handling
error recovery (marking threads failed on dispatch failure), and managing
approval state transitions. The `create_thread_endpoint` function alone is
~170 lines with conditional team preset loading, vault index building, context
preamble construction, and dispatch error handling. The
`respond_to_permission_endpoint` is ~260 lines with state machine guards,
idempotency deduplication, and conditional approval state updates.

These handlers need business-rule understanding to modify, not just HTTP
protocol knowledge. If the same thread creation flow needed to be triggered
from a CLI or message queue, the orchestration would need to be duplicated.

**Recommendation:** Extract handler orchestration into `control/` service
functions (e.g., `control/thread_service.py` with `create_and_dispatch_thread`,
`respond_to_permission`, `send_followup_message`). Route handlers become thin
wrappers: parse request, call service function, format response. This is the
natural next layer isolation step (Layer 2c).

### Violation: Duplicated `_PLAN_APPROVAL_PAUSE_CAUSES` in route handler

**Layer:** 2 (Entry Points)
**File(s):** `src/vaultspec_a2a/api/routes/permissions.py` (lines 53-56)
**Severity:** Minor
**Description:** The `_PLAN_APPROVAL_PAUSE_CAUSES` constant is re-defined in
the permissions route handler as a local set literal, independent of the
canonical `PLAN_APPROVAL_PAUSE_CAUSES` already living in
`thread/snapshots.py`. Both `control/event_handlers.py` and
`control/projection.py` correctly import from `thread.snapshots`, but the
route handler does not.

**Recommendation:** Import `PLAN_APPROVAL_PAUSE_CAUSES` from
`thread.snapshots` instead of re-defining it. This eliminates the drift risk.

### Violation: Direct database CRUD calls in route handlers

**Layer:** 2 (Entry Points)
**File(s):** All route handler files in `api/routes/`
**Severity:** Moderate
**Description:** Route handlers directly call `database.crud` functions
(`create_thread`, `get_thread`, `update_thread_status`,
`set_thread_repair_state`, `create_control_action`, etc.) and manage
`AsyncSession` lifecycle (including explicit `db.commit()` calls). This
couples the HTTP layer to the database access pattern. If the data access
strategy changed (e.g., repository pattern, CQRS), every route handler would
need modification.

**Recommendation:** This is the same issue as the orchestration leakage above.
Service-layer functions in `control/` should own the database session
lifecycle and CRUD orchestration. Route handlers receive results, not sessions.

---

## Section 3: Infrastructure Containment (Layer 3 Integrity)

### No critical violations found

- Dockerfiles are in `docker/` directory, not repo root
- Dockerfiles copy only what is needed (`COPY src/vaultspec_a2a/` not
  `COPY . /app`)
- No hardcoded secrets in Dockerfiles or compose files
- `VAULTSPEC_INTERNAL_TOKEN` is required at runtime via env var with
  explicit `?VAULTSPEC_INTERNAL_TOKEN is required` validation
- Compose `command` entries are simple service start commands (uvicorn)
- No business logic in compose entrypoints

### Minor observation: context: `.` in compose build

**Layer:** 3
**File(s):** `docker-compose.prod.yml` (line 17: `context: .`)
**Severity:** Minor (mitigated)
**Description:** The build context is the repo root, which sends the entire
repo to Docker. However, this is mitigated by the Dockerfiles using selective
`COPY` statements (`COPY src/vaultspec_a2a/`, `COPY pyproject.toml uv.lock`).
A `.dockerignore` would further reduce build context size.

**Recommendation:** Add a `.dockerignore` excluding `.vault/`, `.git/`,
`docs/`, `knowledge/`, `data/`, `node_modules/`, `__pycache__/` to reduce
build context transfer time.

---

## Section 4: Cross-Language Boundary Hygiene

### No violations found

The project has clean separation between Python and Node.js ecosystems:

- `pyproject.toml` manages Python dependencies only
- `package.json` manages Node.js dependencies (UI + ACP runtime) only
- Cross-ecosystem interaction happens only in Docker multi-stage builds where
  Node artifacts (built frontend, `node_modules/`) are copied into the Python
  worker image
- The Gemini CLI is installed in a dedicated Docker stage and copied as a
  runtime artifact

---

## Section 5: Configuration and Secrets

### No critical violations found

- `.env` is in `.gitignore` (line 22)
- `.env.example` exists at repo root
- No hardcoded secrets found in source files (API keys are read from
  `settings` which reads from env vars)
- The test file `test_factory.py` uses `"static-test-key"` which is clearly
  a test placeholder, not a real secret

### Violation: Telemetry module reads env vars at import time

**Layer:** 1/2 boundary
**File(s):** `src/vaultspec_a2a/telemetry/instrumentation.py` (lines 58-81)
**Severity:** Minor
**Description:** The telemetry module reads 8 `os.environ` variables at module
import time (`OTEL_SERVICE_NAME`, `OTEL_SERVICE_VERSION`,
`OTEL_EXPORTER_OTLP_ENDPOINT`, etc.). This is explicitly documented and
intentional (comment at line 48: "OTel SDK configuration must be determined at
import time"), and these are standard OTel env vars, not application-specific
infrastructure config.

**Recommendation:** Accept as-is. This follows OTel conventions and is well
documented. The module never reads application secrets.

### Observation: `control.config.settings` is a God object

**Layer:** 2
**File(s):** `src/vaultspec_a2a/control/config.py` (632 lines)
**Severity:** Moderate
**Description:** The `settings` singleton (composed from `DomainConfig` +
`InfraConfig`) is imported by 34 files across `api/`, `worker/`, `providers/`,
`protocols/`, `ipc/`, `cli/`, `database/`, and `control/`. While the split
into `DomainConfig` (Layer 1 behavioral knobs) and `InfraConfig` (Layer 2
infrastructure) is architecturally clean, the composed `Settings` object means
every consumer gets access to everything — a provider module can see database
URLs, a worker module can see API keys it doesn't need.

**Recommendation:** For a future Layer 3 PR, consider having modules import
`DomainConfig` directly (already available at `domain_config.py`) instead of
the composed `Settings` where only behavioral knobs are needed. Layer 1
modules already do this correctly. The 34-file `settings` import list could
be significantly reduced.

---

## Section 6: Testability Assessment

### Layer 1 tests: PASS without infrastructure

`utils/tests/`, `thread/tests/`, `context/tests/`, `graph/tests/` (unit
subset), `lifecycle/tests/` are all marked `core` and run without Docker,
database, or external services.

### Layer 2 tests: Direct infrastructure coupling

**Violation:** Entry point tests use real infrastructure

**Layer:** 2
**File(s):** `src/vaultspec_a2a/api/tests/`, `src/vaultspec_a2a/worker/tests/`
**Severity:** Moderate
**Description:** API and worker tests use real `AsyncSession` instances
against in-memory SQLite, real `EventAggregator` instances, and real
`Checkpointer` instances. This is actually the project's explicit philosophy
(no mocks/fakes mandate), so it's not a defect per se, but it means Layer 2
tests require the full dependency chain to be available. The trade-off is
higher test fidelity but slower tests and no isolation between layers.

**Recommendation:** Accept as-is given the project's explicit no-mocks mandate.
The tests are effectively integration tests that validate the full call stack,
which is valuable. If test speed becomes an issue, the service-layer
extraction recommended in Section 2 would enable testing orchestration logic
with a lighter database fixture.

### Test directory structure: CLEAR

The project uses co-located `tests/` directories within each package, which
provides clear mapping between source and test code. Top-level `tests/`
contains integration/e2e tests. This structure is well-organized.

---

## Section 7: Additional Findings

### Violation: `ipc/schemas.py` imports from `control.config`

**Layer:** 2 internal coupling
**File(s):** `src/vaultspec_a2a/ipc/schemas.py` (line 14)
**Severity:** Minor
**Description:** The IPC schemas module imports `settings` from
`control.config`. The IPC schemas are shared message types between gateway and
worker — they should be independent of configuration. The import is likely
used for a default value on a field.

**Recommendation:** Remove the `settings` import. If a default value depends
on configuration, make it a required field or compute the default at the call
site where `settings` is naturally available.

### Violation: `acp_chat_model.py` exceeds 1,000 lines

**Layer:** 2
**File(s):** `src/vaultspec_a2a/providers/acp_chat_model.py` (1,821 lines)
**Severity:** Moderate
**Description:** This module exceeds the project's 1,000-line mandate by 82%.
It contains the complete ACP subprocess management, JSON-RPC protocol handler,
streaming chunk parser, permission callback bridge, and session lifecycle —
all in one file.

**Recommendation:** Split into focused sub-modules: `acp_protocol.py`
(JSON-RPC message handling), `acp_process.py` (subprocess management),
`acp_chat_model.py` (LangChain BaseChatModel interface). This is out of scope
for the current PR but should be tracked.

### Violation: `protocols/mcp/server.py` exceeds 1,000 lines

**Layer:** 2
**File(s):** `src/vaultspec_a2a/protocols/mcp/server.py` (1,045 lines)
**Severity:** Minor (barely over threshold)
**Description:** The MCP server module is slightly over the 1,000-line mandate.
It defines 9 MCP tools, each as an async handler function.

**Recommendation:** Split tool handlers into individual modules under
`protocols/mcp/tools/` if further growth is expected.

---

## Summary Assessment

### Layer 1 health: GOOD

The library layer is fully independent. All domain types (enums, state machine,
snapshot dataclasses, error types, models) live in Layer 1. No Layer 1 module
imports from infrastructure. `DomainConfig` provides behavioral knobs without
infrastructure coupling. Layer 1 could be extracted into a standalone package
today.

### Layer 2 health: MODERATE — orchestration leakage in route handlers

The `control/` -> `api/` boundary violation that was the primary target of
PR #9 is **fully resolved** (zero `control/` imports from `api/`). However,
the reverse direction has a new concern: route handlers contain substantial
orchestration logic that belongs in service functions. This is the natural
next step (Layer 2c: extract handler orchestration to `control/` service layer).

### Layer 3 health: GOOD

Infrastructure config is clean. Dockerfiles are well-structured with
multi-stage builds, selective COPY, and no hardcoded secrets. Compose files use
runtime env vars correctly. Could move to Kubernetes without application code
changes.

### Cross-language health: GOOD

Python and Node.js ecosystems coexist cleanly. Cross-ecosystem interaction is
limited to Docker build stages. The Node.js removal would require only
Dockerfile and ACP provider changes.

### Overall boundary integrity score

| Severity | Count | Details |
|----------|-------|---------|
| Critical | 0 | - |
| Moderate | 4 | Route handler orchestration leakage, direct DB calls in handlers, `settings` god object coupling, `acp_chat_model.py` over 1,000 lines |
| Minor | 4 | Duplicated `_PLAN_APPROVAL_PAUSE_CAUSES` in permissions route, `ipc/schemas.py` settings import, `mcp/server.py` over 1,000 lines, missing `.dockerignore` |

**Net assessment:** The Layer 2b extraction achieved its goals — zero
`control/` -> `api/` imports, domain types in Layer 1, `crud.py` split, utils
inversions fixed. The remaining moderate violations are primarily about route
handler thickness (orchestration logic that should live in `control/` service
functions) and the `settings` singleton's wide reach. These are natural
candidates for a Layer 2c PR.
