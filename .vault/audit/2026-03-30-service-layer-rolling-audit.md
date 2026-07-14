---
tags:
  - '#audit'
  - '#service-layer'
date: '2026-03-30'
modified: '2026-03-30'
related:
  - '[[2026-03-30-service-layer-research]]'
  - '[[2026-03-28-infra-config-rolling-audit]]'
---

# `service-layer` rolling audit

Living audit document for the service layer containerization work.
Captures all boundary violations, duplication, shadowing, and
architectural concerns discovered across multiple audit cycles.

## Cycle 1 — Initial boundary audit (2026-03-30)

Four parallel audit agents covering Layer 1 independence, Layer 2
thinness, Layer 3 containment, and testability/config.

### Layer 1 — Library Independence

| ID | Finding | Severity | File(s) |
|----|---------|----------|---------|
| V1.1 | Module-level `domain_config = DomainConfig()` singleton triggers `.env` file I/O and env var resolution at import time. 12 Layer 1 production modules import this singleton, making their import behavior depend on ambient environment state. | **CRITICAL** | `domain_config.py:148` |
| V1.3-A | `DomainConfig` extends `pydantic_settings.BaseSettings` — an infrastructure library for reading env vars and `.env` files. This makes `pydantic-settings` a hard Layer 1 dependency. A "pure domain" library should not depend on infrastructure config machinery. | **CRITICAL** | `domain_config.py:10,13` |
| V1.3-B | Singleton pattern prevents config injection. No way to run two configurations concurrently, construct Layer 1 objects without triggering env resolution, or override config without monkey-patching. | **CRITICAL** | `domain_config.py:148` |
| C1.4 | `pytest -m core` tests are not hermetic — importing any Layer 1 module that touches `domain_config` triggers env resolution. A `.env` file in `$CWD` silently alters test behavior. | **HIGH** | all Layer 1 consumers |

**Root cause:** All four findings share one root — `DomainConfig` extends
`BaseSettings` and is instantiated at module scope. Fix: make
`DomainConfig` a plain `pydantic.BaseModel` or frozen dataclass; move
env-reading to infrastructure layer.

### Layer 2 — Entry Point Thinness

| ID | Finding | Severity | File(s) |
|----|---------|----------|---------|
| V5 | `ws_dispatch.py` is a shadow service layer — 226 lines duplicating DB access, state validation, terminal-status checks, metadata parsing, and error handling that the REST service functions already implement. Two parallel architectures for the same operations. | **CRITICAL** | `api/ws_dispatch.py:120-226,242-298` |
| V7 | `event_handlers.py` contains the entire thread lifecycle state machine — permission creation/superseding, approval status transitions, terminal event handling, repair state management. 370+ lines of domain logic in an infrastructure coordination module. | **CRITICAL** | `control/event_handlers.py:51-421` |
| V1 | `_process_metadata` in `threads.py` does filesystem validation, context ref discovery, team config loading, nickname generation — domain enrichment embedded in a route handler. | **HIGH** | `api/routes/threads.py:58-98` |
| V6 | `ws_dispatch.py` calls `get_thread` (DB access) directly, bypassing the service layer entirely. | **HIGH** | `api/ws_dispatch.py:24,129,263` |
| V3 | String-prefix error interpretation in route handlers: `startswith("circuit_open:")`, `startswith("at_capacity:")`. Handlers decode service-layer result encodings instead of receiving typed error categories. | **HIGH** | `api/routes/threads.py:162-181`, `messages.py:63-80` |
| V4 | Inline business rules in archive/delete endpoints: terminal status checks and state transition logic embedded in handlers. | **HIGH** | `api/routes/threads.py:278-324` |
| V8 | `thread_service.py` assembles domain objects (context preamble, vault index, autonomous flag resolution from team config) — domain orchestration in what should be a coordination layer. | **HIGH** | `control/thread_service.py:137-163` |
| V9 | Hardcoded business fallback in `ConnectionManager`: emits `agent_status` with hardcoded agent ID `"vaultspec-supervisor"` and state `SUBMITTED` when no message handler is registered. | **HIGH** | `api/websocket.py:349-356` |
| V2 | Inline JSON parsing of `thread_metadata` to extract `feature_tag`, `source_branch`, `callee` in list endpoint — presentation concern in a route handler. | **HIGH** | `api/routes/threads.py:226-233` |

### Layer 3 — Infrastructure Containment

| ID | Finding | Severity | File(s) |
|----|---------|----------|---------|
| L3.2 | 5 compose files at repo root, Dockerfiles in `docker/`, no `service/` directory. Deployment topology is not discoverable from directory structure. | **CRITICAL** | repo root |
| L3.1 | `COPY src/vaultspec_a2a/` copies the entire package tree including ~95 test files into every image. Neither gateway nor worker image is scoped to its own modules. | **CRITICAL** | `docker/prod.Dockerfile`, `docker/dev.Dockerfile` |
| L3.6 | `.dockerignore` missing `**/tests/` — all test code enters build context and lands in production images. | **CRITICAL** | `.dockerignore` |
| L3.8 | `VAULTSPEC_PORT=8000` default defined in 5 separate files. Config drift risk. | **HIGH** | `config.py`, `.env.example`, 2 compose files, `Justfile` |
| L3.5 | `FIGMA_ACCESS_TOKEN` in `.env.example` is a zombie — not consumed by any code. Alias env vars `GOOGLE_CLOUD_PROJECT_ID` and `VAULTSPEC_MCP_API_BASE_URL` accepted but undocumented. | **HIGH** | `.env.example` |
| L3.7 | The 5-file compose overlay pattern is not self-documenting. No README or top-level guide explains which are standalone vs overlays. | **HIGH** | repo root |

### Testability

| ID | Finding | Severity | File(s) |
|----|---------|----------|---------|
| T6.1 | Most co-located test modules (`api/`, `database/`, `streaming/`, `worker/`, `workspace/`, `thread/`, `context/`, `lifecycle/`, `team/`, `control/`) carry no `core`/`middleware` marker. Included by default through negation of infra markers, not by assertion of layer. Confidence in test layer isolation is low. | **CRITICAL** | all `*/tests/conftest.py` |
| T6.3 | OTel OTLP exporter fires during middleware tests (background thread pushes to `localhost:4317` even without Jaeger). Not a failure but noise that should not occur outside `requires_jaeger` tests. | **HIGH** | `telemetry/` |

## Cycle 1 — Summary Counts

| Severity | Count |
|----------|-------|
| CRITICAL | 8 |
| HIGH | 9 |
| Total | **17** |

## Cycle 2 — Deep-dive audits (2026-03-30)

Five parallel agents: WS/REST duplication, event handler domain
extraction, business logic in protocols, test marker correctness,
and `control/` shadowing analysis.

### WS/REST Duplication — `ws_dispatch.py` vs REST services

The WebSocket dispatch path is a **shadow service layer** built before
the REST service refactor. It inlines the same operations but has
**diverged** and **regressed**:

**Behavioral bugs from duplication:**

| Bug | REST behavior | WS behavior |
|-----|---------------|-------------|
| `WorkerAtCapacityError` on message | Marks thread FAILED | Does NOT mark FAILED — thread lingers |
| Cancel on terminal thread | Rejected (state guard) | Dispatched anyway (no guard) |
| Status → RUNNING after dispatch | Updated | Not updated |
| Status → CANCELLING after cancel | Updated | Not updated |

**Missing infrastructure in WS path (present in REST):**

- No idempotency deduplication (both message and cancel)
- No control action audit trail
- No repair state machine participation
- No status transitions on dispatch success

**Accidental drift:**

- Terminal-state guard uses hand-rolled tuple of `.value` strings vs
  `NON_ACTIVE_STATUSES` frozenset
- Validation order: WS checks terminal-then-INPUT_REQUIRED; REST checks
  INPUT_REQUIRED-then-terminal
- JSON decode exception: WS catches `ValueError`; REST catches
  `json.JSONDecodeError` (subclass)
- Agent ID default: WS inline `"vaultspec-supervisor"`; REST in route

**Root cause:** WS handlers predate the `control/*_service.py` refactor
and were never updated to delegate. They should call the same service
functions as REST, with protocol-specific error translation only.

### Event Handlers — Domain Logic Classification

`event_handlers.py` (468 lines) is **79% infrastructure, 19% domain**:

| Function | Domain lines | What domain logic |
|----------|-------------|-------------------|
| `_handle_terminal_event` | ~15 | Cancel-action finalization rule, terminal→HEALTHY repair rule |
| `_handle_permission_event` | ~45 | Full permission FSM: supersede, INPUT_REQUIRED transition, PAUSED_RESUMABLE, approval PENDING/APPROVED/REJECTED |
| `_handle_progress_event` | ~20 | Progress-implies-applied inference, RUNNING+HEALTHY transition |
| `_handle_execution_state_event` | ~10 | Payload validation/normalization |
| `relay_event` | 0 | Pure orchestration |

**Three domain state machines have no Layer 1 counterpart:**

- Terminal effects (given terminal status + cancel action → repair state)
- Permission FSM (request → supersede/resolve → approval status)
- Progress-applied inference (progress → answered permissions applied)

These should extract to Layer 1 as pure decision functions returning
descriptor dataclasses, following the pattern of
`lifecycle/reconciliation.py`. The event handlers would then become thin
coordinators: call domain function → execute DB writes.

### Business Logic in Protocol Handlers — Full Scan

**Most pervasive violations across 12 files:**

| Pattern | Files affected | Count |
|---------|---------------|-------|
| `db.commit()` in handlers (should be service-owned) | threads, cancel, messages, permissions | 6 sites |
| String-prefix/substring error parsing | threads, cancel, messages | 5 sites |
| `thread_state.py` — 95-line service orchestration inline | thread_state | 1 (worst offender) |
| `internal.py` — event relay copy-pasted 3 times | internal | 3 sites |
| `health.py` — full probe orchestration (DB+HTTP+readiness) | health | 1 |
| `teams.py` — worker/aggregator merge + preset loading | teams | 3 functions |
| `_process_metadata` — domain enrichment in route | threads | 1 |
| `ws_dispatch.py` — service logic in protocol adapter | ws_dispatch | 2 functions |
| `app.py` — reconciliation + startup orchestration in lifespan | app | 1 |

**Key finding:** Services return stringly-typed errors (`error_detail`
strings with prefix conventions). Every handler must parse these strings
to decide HTTP status codes. Services should return typed error enums
or raise typed exceptions.

### Test Marker Audit

| Module | Current | Correct? | Issue |
|--------|---------|----------|-------|
| `graph/tests/nodes/test_worker_integration.py` | `core` (inherited) | **WRONG** | Imports `providers.acp_chat_model` (Layer 2). Needs `requires_acp` or `live` marker. |
| `utils/tests/test_logging.py` | `core` + `unit` | **WRONG** | Imports `control.config.Settings` (Layer 2). Should be `middleware`. |
| `thread/tests/` | `core` only | **INCOMPLETE** | Missing `unit` marker (all other core conftest files apply both). |
| `streaming/tests/` | `core` + `unit` | **BORDERLINE** | `streaming/` classified as Layer 1.5 — imports are clean but classification is ambiguous. |
| All other 12 modules | Correct | YES | No violations. |

### `control/` Shadowing Audit

**All six audited modules are clean:**

| Module | Classification |
|--------|---------------|
| `snapshot.py` | Pure coordination — delegates to `thread/snapshots.py` |
| `projection.py` | Pure coordination — DB reads + Layer 1 type merges |
| `health.py` | Pure coordination — reads runtime state, formats |
| `diagnostics.py` | Pure coordination — DB probe + classification |
| `dispatch.py` | Pure coordination — HTTP dispatch + circuit breaker |
| `circuit_breaker.py` | Infrastructure — textbook pattern, no domain knowledge |

No shadowing, mirroring, or domain creep found. The shadowing is
exclusively in `event_handlers.py` (covered above) and `ws_dispatch.py`
(covered in duplication audit).

## Cycle 2 — New Findings

| ID | Finding | Severity | Source |
|----|---------|----------|--------|
| V10 | WS message dispatch does NOT mark thread FAILED on `WorkerAtCapacityError` — REST does | **CRITICAL** | Duplication audit |
| V11 | WS cancel dispatch has NO terminal-state guard — can cancel completed/archived threads | **CRITICAL** | Duplication audit |
| V12 | WS path missing idempotency, control actions, repair state, and status transitions | **CRITICAL** | Duplication audit |
| V13 | Permission FSM domain logic (45 lines) in `event_handlers.py` has no Layer 1 counterpart | **CRITICAL** | Event handler audit |
| V14 | `thread_state.py` endpoint is 95 lines of service orchestration inline in handler | **CRITICAL** | Protocol audit |
| V15 | `internal.py` event relay pattern copy-pasted 3 times | **HIGH** | Protocol audit |
| V16 | Services return stringly-typed errors; handlers parse string prefixes for HTTP codes | **HIGH** | Protocol audit |
| V17 | `db.commit()` in 6 handler sites — transaction boundaries owned by handlers not services | **HIGH** | Protocol audit |
| V18 | `graph/tests/nodes/test_worker_integration.py` marked `core` but imports Layer 2 | **HIGH** | Test marker audit |
| V19 | `utils/tests/test_logging.py` marked `core` but imports `control.config.Settings` | **HIGH** | Test marker audit |
| V20 | `thread/tests/conftest.py` missing `unit` marker | **MEDIUM** | Test marker audit |
| V21 | Terminal-state guard in WS uses hand-rolled tuple vs `NON_ACTIVE_STATUSES` frozenset | **MEDIUM** | Duplication audit |

## Cycle 3 — Deep-dive audits (2026-03-30)

Five parallel agents: hand-rolled literals, config redefinition, free-standing
domain logic in Layer 2, test marker correctness, and Layer 1 constant gaps.

### Hand-Rolled Literals vs Centralized Enums

Widespread use of bare string literals where Layer 1 enums exist:

| Category | Violation count | Root issue |
|----------|----------------|------------|
| `ThreadStatus` bare strings (`"running"`, `"failed"`, etc.) | 20+ sites | Enum exists, not used |
| `ControlActionType` bare strings (`"ingest"`, `"cancel"`, `"resume"`) | 12 sites | Enum exists, not used |
| `ApprovalStatus` bare strings (`"approved"`, `"rejected"`, `"pending"`) | 4 sites | Enum exists, not used |
| `"vaultspec-supervisor"` default agent ID | 8 prod sites | No constant exists |
| `TERMINAL_STATUSES` inline re-definitions | 2 sites | Frozenset exists, hand-rolled |

**Key files:** `worker/executor.py` (15+ bare strings), `streaming/ingest.py`
(5), `worker/state_projection.py` (3), `api/ws_dispatch.py` (3),
`control/cancel_service.py` (1), `graph/nodes/supervisor.py` (3).

### Config Value Redefinition Across Layers

Port defaults (`8000`, `8001`, `8200`) defined in 5+ files each:

| Value | Authoritative | Also in |
|-------|---------------|---------|
| `8000` | `config.py:170` | 2 compose files (fallback), `doctor.py`, `verify.py`, Justfile |
| `8001` | `config.py:211` | 2 compose files, `doctor.py`, Justfile (2 recipes) |
| `8200` | `config.py:192` | `doctor.py` |
| `"sqlite"` | `config.py:39,47` | 2 compose files (explicit default assignments) |
| `"127.0.0.1"` | `config.py:216` | `cli/_team.py:355`, `cli/_util.py:115` (hardcoded) |

`doctor.py` hardcodes all three ports in `_DEFAULT_PORTS` instead of
reading from `settings`. `verify.py` embeds `:8000` in module-level URL
constants.

### Free-Standing Domain Logic in Layer 2/3

**48 domain decisions** found in Layer 2 with no Layer 1 pure-function
counterpart:

| Category | Count | Proposed Layer 1 module |
|----------|-------|------------------------|
| Dispatch failure policy | 6 | `thread/dispatch_policy.py` |
| Permission response FSM | 8 | `thread/permission_policy.py` |
| Permission event FSM | 7 | `thread/permission_fsm.py` |
| Thread creation rules | 5 | `thread/creation.py` |
| Cancel eligibility | 3 | `thread/cancel_policy.py` |
| Message eligibility | 2 | `thread/message_policy.py` |
| Terminal effects | 3 | `thread/terminal_effects.py` |
| Repair state mapping | 7 | `thread/repair_policy.py` |
| Deletion/archive guards | 2 | `thread/lifecycle_guards.py` |
| Idempotency key derivation | 2 | `thread/idempotency.py` |
| Default agent ID | 1 | `thread/constants.py` |
| Checkpoint error → repair | 2 | extend `snapshots.py` |

**Critical inconsistency found:** Dispatch failure policy differs
between services — `thread_service` marks FAILED for `at_capacity`;
`permission_service` does NOT. This invisible because each service
hard-codes its own policy inline.

### Test Marker Audit

| Violation | Severity |
|-----------|----------|
| `graph/tests/nodes/test_worker_integration.py` marked `core` but imports `providers.acp_chat_model` and spawns subprocess | **HIGH** |
| `utils/tests/test_logging.py` marked `core` but imports `control.config.Settings` | **HIGH** |
| `thread/tests/conftest.py` missing `unit` marker (inconsistent with all other `core` conftest files) | **MEDIUM** |
| `tests/evals/` has no marker and no fail-fast hook | **MEDIUM** |
| `graph/tests/nodes/` has no conftest — inherits parent markers wholesale | **LOW** |

**`service` marker proposal:** Single Layer 3 marker replacing the
fragmented `live`/`requires_*` family. Added to `addopts` as
`not service`. Bridge via `pytest_collection_modifyitems` auto-applying
`service` to legacy-marked tests. New Layer 3 tests use `service` only.

### Layer 1 Constant Gaps

| Missing constant | Inline usage count | Proposed location |
|------------------|--------------------|-------------------|
| `DEFAULT_SUPERVISOR_ID` (`"vaultspec-supervisor"`) | 8 prod sites | `thread/constants.py` |
| `DispatchRequest.action` typed as `ControlActionType` | 3 match arms + 7 assignments | `ipc/schemas.py` type change |
| `REJECT_OPTION_IDS` frozenset | 2 `startswith("reject")` checks | `graph/enums.py` |
| `STARTUP_REPAIR_REASON` constant | 2 coupled magic strings | `lifecycle/reconciliation.py` |
| `AgentControlAction` vs `ControlActionType` divergence | structural | evaluate merge or document distinction |

### Cycle 3 — New Findings

| ID | Finding | Severity |
|----|---------|----------|
| V22 | 20+ bare `ThreadStatus` string literals instead of enum usage | **CRITICAL** |
| V23 | 12 bare `ControlActionType` string literals instead of enum | **CRITICAL** |
| V24 | 48 domain decisions in Layer 2 with no Layer 1 counterpart | **CRITICAL** |
| V25 | Dispatch failure policy inconsistent across services (FAILED vs lenient for same error) | **CRITICAL** |
| V26 | `DEFAULT_SUPERVISOR_ID` scattered across 8 files with no constant | **HIGH** |
| V27 | Port defaults hardcoded in 5+ files per value | **HIGH** |
| V28 | `DispatchRequest.action` typed as `Literal[...]` not `ControlActionType` | **HIGH** |
| V29 | `test_worker_integration.py` imports Layer 2 under `core` marker | **HIGH** |
| V30 | `test_logging.py` imports Layer 2 under `core` marker | **HIGH** |
| V31 | `ApprovalStatus` bare strings in `supervisor.py` and `projection.py` | **HIGH** |
| V32 | `thread/tests/conftest.py` missing `unit` marker | **MEDIUM** |
| V33 | `tests/evals/` has no marker or fail-fast hook | **MEDIUM** |
| V34 | Rejection determined by `startswith("reject")` not enum check | **MEDIUM** |
| V35 | `TERMINAL_STATUS_MAP` uses string keys instead of enum | **LOW** |
| V36 | `graph/tests/nodes/` has no local conftest | **LOW** |

## Cumulative Violation Summary

| Severity | Cycle 1 | Cycle 2 | Cycle 3 | Total |
|----------|---------|---------|---------|-------|
| CRITICAL | 8 | 6 | 4 | **18** |
| HIGH | 9 | 6 | 6 | **21** |
| MEDIUM | 0 | 1 | 3 | **4** |
| LOW | 0 | 0 | 2 | **2** |
| Total | **17** | **13** | **15** | **45** |

## Cycle 4 — Library documentation verification (2026-03-30)

Five parallel agents verified the codebase against official documentation
for LangGraph, Pydantic/pydantic-settings, FastAPI, SQLAlchemy async,
and OpenTelemetry using Context7 MCP and web research.

### LangGraph — 22 MATCH, 0 MISMATCH, 2 CONCERN

The LangGraph integration is **correct and well-implemented**. All core
patterns verified:

- StateGraph construction, node addition, edge wiring — correct
- `astream_events(version="v2")` with event classification — correct
- `Command(resume=...)` for interrupt resumption — correct
- `AsyncSqliteSaver`/`AsyncPostgresSaver` via `from_conn_string()` + `setup()` — correct
- TeamState TypedDict with `add_messages` reducer — correct
- `aget_state` for checkpoint inspection — correct
- `GraphInterrupt` caught as `BaseException` — correct

| ID | Finding | Severity |
|----|---------|----------|
| V37 | `graph.recursion_limit` set as compile-time attribute (compiler.py:386). Docs say pass via `config={"recursion_limit": N}` at runtime. The project also passes it correctly at runtime in executor.py — the compile-time set is redundant and undocumented. | **MEDIUM** |
| V38 | `graph.step_timeout` attribute (compiler.py:382). Exists in LangGraph's `Pregel` base but is not in user-facing docs. Internal attribute — upgrade risk. | **LOW** |

### Pydantic / pydantic-settings — 13 MATCH, 0 MISMATCH, 2 CONCERN

All pydantic-settings patterns are **functionally correct**:

- `BaseSettings` with `env_file` + `env_prefix` — correct
- `Settings(DomainConfig, InfraConfig)` MRO — works because `Settings`
  declares its own `model_config` (critical — removal would silently
  change behavior)
- `validation_alias` for third-party env vars — correct
- `AliasChoices` — correct
- `field_validator(mode="before")`, `model_validator(mode="after")` — correct

| ID | Finding | Severity |
|----|---------|----------|
| V39 | All 18 DomainConfig fields have redundant `alias="VAULTSPEC_<NAME>"` that duplicates what `env_prefix="VAULTSPEC_"` already produces. Not wrong, but unnecessary boilerplate. | **LOW** |
| V40 | Two singletons (`domain_config` + `settings`) each parse `.env` independently at import time. Minor performance concern (one extra file read). | **LOW** |

### FastAPI — 19 MATCH, 0 MISMATCH, 2 CONCERN

FastAPI usage is **correct throughout**:

- Lifespan context manager, factory pattern — correct
- `Depends()` with return and yield patterns — correct
- WebSocket accept/receive/send lifecycle — correct
- CORS middleware, static file serving — correct
- ASGITransport for testing — correct

| ID | Finding | Severity |
|----|---------|----------|
| V41 | Mixed `asyncio`/`anyio` concurrency primitives: gateway uses raw `asyncio`, worker uses `anyio.create_task_group()`. Both work but inconsistent. | **LOW** |
| V42 | `app.router.lifespan_context` override in tests is an undocumented Starlette internal. Fragile across upgrades. | **MEDIUM** |

### SQLAlchemy async — 17 MATCH, 0 MISMATCH, 2 CONCERN

SQLAlchemy usage is **correct per 2.0 async docs**:

- `create_async_engine` for both aiosqlite and asyncpg — correct
- `async_sessionmaker` with `expire_on_commit=False` — correct
- `get_db()` yield pattern for FastAPI — correct
- WAL mode / busy_timeout pragmas — correct
- ORM models with `DeclarativeBase`, `mapped_column`, `Mapped[T]` — correct
- Repository pattern: `select()` + `scalars()`, flush-not-commit — correct
- Alembic async runner — correct

| ID | Finding | Severity |
|----|---------|----------|
| V43 | **No `lazy="raise"` on any relationship.** Default `lazy="select"` will raise `MissingGreenlet` if relationship attributes are ever accessed in async context. Currently safe only because repositories never traverse relationships. Adding `lazy="raise"` would make this a compile-time safety net. | **HIGH** |
| V44 | `migrate.py` uses `asyncio.to_thread(command.upgrade, cfg, "head")` — Alembic's `command.upgrade` internally calls `asyncio.run()`, creating a nested event loop in a worker thread. Works today but architecturally fragile. | **MEDIUM** |

### OpenTelemetry — 15 MATCH, 0 MISMATCH, 3 CONCERN

OTel implementation is **mostly correct**:

- TracerProvider + BatchSpanProcessor + OTLP gRPC exporter — correct
- MeterProvider + PeriodicExportingMetricReader — correct
- W3C traceparent extract/inject via `propagate` — correct
- Span attributes using modern semantic conventions — correct
- Resource with `service.name` — correct

| ID | Finding | Severity |
|----|---------|----------|
| V45 | **Missing `TracerProvider.shutdown()` at process exit.** Neither gateway nor worker lifespan calls shutdown. Buffered spans may be silently dropped on exit. OTel docs explicitly recommend calling `provider.shutdown()` during teardown. | **HIGH** |
| V46 | Dead error-handling code in middleware.py (lines 151-155): `span.set_status()` and `span.record_exception()` called on an already-ended span. The context manager `__exit__` handles this automatically — the explicit except block is misleading dead code. | **MEDIUM** |
| V47 | OTLP exporter fires during non-Jaeger tests. `OTEL_SDK_DISABLED` not set in test env, causing `BatchSpanProcessor` to attempt gRPC connections to `localhost:4317` during every test run. Produces background noise. | **HIGH** |

### Cycle 4 — New Findings

| ID | Finding | Severity | Library |
|----|---------|----------|---------|
| V37 | Redundant `graph.recursion_limit` compile-time attribute | **MEDIUM** | LangGraph |
| V38 | `graph.step_timeout` relies on undocumented internal attribute | **LOW** | LangGraph |
| V39 | 18 redundant alias declarations in DomainConfig | **LOW** | pydantic-settings |
| V40 | Double `.env` parse (two singletons) | **LOW** | pydantic-settings |
| V41 | Mixed asyncio/anyio concurrency primitives | **LOW** | FastAPI |
| V42 | Undocumented `app.router.lifespan_context` in tests | **MEDIUM** | FastAPI/Starlette |
| V43 | No `lazy="raise"` on ORM relationships — MissingGreenlet risk | **HIGH** | SQLAlchemy |
| V44 | Nested `asyncio.run()` in migration thread | **MEDIUM** | SQLAlchemy/Alembic |
| V45 | Missing `TracerProvider.shutdown()` at exit — spans may be lost | **HIGH** | OpenTelemetry |
| V46 | Dead span error-handling code in middleware | **MEDIUM** | OpenTelemetry |
| V47 | OTLP exporter noise during tests — `OTEL_SDK_DISABLED` not set | **HIGH** | OpenTelemetry |

## Cumulative Violation Summary

| Severity | C1 | C2 | C3 | C4 | Total |
|----------|----|----|----|----|-------|
| CRITICAL | 8 | 6 | 4 | 0 | **18** |
| HIGH | 9 | 6 | 6 | 3 | **24** |
| MEDIUM | 0 | 1 | 3 | 4 | **8** |
| LOW | 0 | 0 | 2 | 5 | **7** |
| Total | **17** | **13** | **15** | **12** | **57** |

## Cycle 4.5 — Pre-merge self-review (2026-03-31)

Five issues identified during pre-merge status review. Three were
regressions requiring immediate fixes; two were observations.

### Findings

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| F1 | Two `db.commit()` calls in `api/routes/threads.py` delete/archive endpoints — handlers owned transaction boundaries instead of services | **CRITICAL** | **FIXED** — extracted `delete_thread_service()` and `archive_thread()` to `control/thread_service.py` |
| F2 | OTel exporter noise during tests — `BatchSpanProcessor` and `PeriodicExportingMetricReader` attempt gRPC to `localhost:4317` during every test run | **HIGH** | **FIXED** — root `conftest.py` sets `OTEL_METRICS_EXPORTER=none` and redirects trace exporter to non-routable `198.51.100.1:4317` |
| F3 | Layer 1 → `control.config` coupling — Phase 3 moved `domain_config` singleton to `control/config.py`, making 12 Layer 1 modules import from Layer 2. Layer 1 was no longer independently importable. | **CRITICAL** | **FIXED** — moved `DomainSettingsConfig` and `domain_config` singleton back to `domain_config.py`. All 23 consumers import from Layer 1 path. Bare REPL import verified. |
| F4 | 25+ commits — large PR with substantial diff. Commit history is logical (phase per commit) but review burden is high. | **LOW** | Acknowledged — structural reality of 10-phase plan |
| F5 | README fully rewritten — line counts verified with `wc -l` but architecture descriptions, dependency graph, and consumer tables are synthesis. | **LOW** | Acknowledged — human review recommended |

### Resolution commit

All three code fixes (F1, F2, F3) landed in commit `a28e208`:
`fix: resolve 3 regressions — Layer 1 independence, handler commits, OTel noise`

## Cycle 5 — 15-agent sonar audit (2026-03-31)

Post-fix verification audit with 15 parallel agents covering all
checklist domains. 3 regression fixes applied before the audit
(Layer 1 coupling, handler commits, OTel noise).

### CLEAN domains (10/15 agents)

Layer 1 import independence, Layer 1 test isolation (509 core, zero
L2 imports), entry point cross-imports, infrastructure containment,
db.commit ownership (zero in handlers), ORM lazy="raise" (12/12),
test markers (18 conftest files correct), deleted module remnants,
config/secrets, full test suite (1035 pass).

### Bug found and fixed

| ID | Finding | Severity |
|----|---------|----------|
| V48 | `worker/app.py:160` — MeterProvider shutdown guard checks `provider` (TracerProvider) instead of `meter_provider`. Metric shutdown silently gated on wrong object. | **CRITICAL** (bug) — FIXED |

### Remaining moderate findings — ALL RESOLVED

All 8 findings from Cycle 5 were fixed in subsequent commits.

| ID | Finding | Status | Resolution |
|----|---------|--------|------------|
| R1 | `health.py` probe orchestration in route | **RESOLVED** | Extracted to `control/health.py::build_full_health()`. Route is 31 lines. |
| R2 | `teams.py` DB query + dedup logic in route | **RESOLVED** | Created `control/team_service.py::build_team_status()`. Route delegates. |
| R3 | `threads.py` uuid4, json.loads, list_threads in route | **RESOLVED** | Moved to `thread_service.py`: `generate_thread_id()`, `list_threads_service()`, `_parse_thread_summary_metadata()`. |
| R4 | `messages.py` string-sniffing on error_detail | **RESOLVED** | `FailureType` extended with `NOT_FOUND`, `INPUT_REQUIRED`, `TERMINAL`. Handlers use typed checks. |
| R5 | `ws_dispatch.py` string parsing for WS error codes | **RESOLVED** | `_raise_message_failure` rewritten to use `FailureType` enum. |
| R6 | `thread_state.py` direct `get_thread(db)` | **RESOLVED** | `build_thread_state()` accepts `thread_id` directly, does lookup internally. |
| R7 | 13 bare string literals | **RESOLVED** (7 of 13) | Column defaults, fallbacks, log extras replaced with enums. 6 remaining are non-enum contexts (markdown parsing, docstrings, wire protocol). |
| R8 | `dispatch.py` bare `"ingest"` string | **RESOLVED** | `ControlActionType.INGEST` with `ty: ignore`. |

### Cycle 5 Summary

- **1 critical bug found and fixed** (V48)
- **8 moderate pre-existing findings tracked** (R1-R8)
- **10 domains fully clean**
- **Layer 1 independence: VERIFIED** — bare REPL import succeeds
- **Test suite: 1035 pass, zero failures**

## Cycle 4 — Key Takeaway

**The core library integrations are implemented correctly.** LangGraph
(22/24 match), pydantic-settings (13/15 match), FastAPI (19/21 match),
SQLAlchemy (17/19 match), and OpenTelemetry (15/18 match) all follow
official documentation closely. Zero outright misimplementations found.

The findings are:
- **Defensive gaps** (V43 `lazy="raise"`, V45 `TracerProvider.shutdown()`)
  that don't cause bugs today but will when the code evolves
- **Redundancy** (V37 compile-time recursion_limit, V39 alias duplication,
  V40 double env parse) that adds noise but doesn't break correctness
- **Test hygiene** (V47 OTLP noise, V42 internal Starlette API) that
  affects developer experience
