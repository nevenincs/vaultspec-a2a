---
tags:
  - '#audit'
  - '#service-layer'
date: '2026-03-30'
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

## Cumulative Violation Summary

| Severity | Cycle 1 | Cycle 2 | Total |
|----------|---------|---------|-------|
| CRITICAL | 8 | 6 | **14** |
| HIGH | 9 | 6 | **15** |
| MEDIUM | 0 | 1 | **1** |
| Total | **17** | **13** | **30** |
