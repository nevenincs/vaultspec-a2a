---
tags:
  - '#audit'
  - '#core-layer'
date: '2026-03-24'
related:
  - '[[2026-03-23-core-layer-boundary-adr]]'
---

# core-layer boundary audit — section 1: library independence / layer 1 integrity

Auditor: independent automated audit
Scope: `thread/`, `context/`, `team/`, `graph/`, `lifecycle/`, `domain_config.py`, `streaming/`
Date: 2026-03-24

---

## 1a. import test

**Command:** `python -c "from vaultspec_a2a.domain_config import ...; ... print('ALL IMPORTS: PASS')"`

**Result: PASS**

All 17 import targets resolved without error. No import-time side effects detected.

---

## 1b. test isolation

**Command:** `pytest src/vaultspec_a2a/thread/tests/ src/vaultspec_a2a/context/tests/ src/vaultspec_a2a/team/tests/ -x -q --tb=short`

**Result: PASS — 296 passed in 0.94s**

Zero infrastructure required (no running services, no database, no containers). All Layer 1 tests pass in under 1 second.

---

## 1c. infrastructure imports — exhaustive search results

### Findings by file

#### `src/vaultspec_a2a/thread/errors.py` — line 150

```
so that Layer 1 code never imports from the providers layer.
```

**Classification: OK** — docstring text. No actual import. The comment explicitly names the boundary rule.

---

#### `src/vaultspec_a2a/team/team_config.py` — line 111

```
ACP subprocess at runtime.
```

**Classification: OK** — docstring text. No actual import or subprocess usage. The word appears in a developer note explaining why pre-validation is impractical.

---

#### `src/vaultspec_a2a/graph/events.py` — line 7

```
Core never imports from ``api.schemas`` — the dependency arrow points outward.
```

**Classification: OK** — module docstring. No import. Correct architectural statement.

---

#### `src/vaultspec_a2a/graph/compiler.py` — line 37

```python
from .nodes.worker import WorkerNode, create_worker_node
```

**Classification: requires classification — see Violation V-01 below**

This imports from `graph/nodes/worker.py`. `worker.py` itself imports only from Layer 1 sub-modules (`context/`, `thread/`, `domain_config`, `graph/tools/`) plus `langchain_core` and `langgraph`. The name `worker` here refers to a **graph node** (an agent worker node inside the LangGraph graph), not the `worker/` infrastructure module. No cross-layer boundary is crossed.

**Classification: OK** — `graph/nodes/worker.py` is part of Layer 1 (`graph/`). The naming is potentially misleading but the module is correctly scoped.

---

#### `src/vaultspec_a2a/graph/nodes/__init__.py` — line 4

```python
from .worker import create_worker_node as create_worker_node
```

**Classification: OK** — same as above. Re-export of an intra-layer symbol.

---

#### `src/vaultspec_a2a/graph/compiler.py` — line 33

```python
from vaultspec_a2a.utils.enums import Model, Provider
```

**Classification: MINOR CONCERN — see V-02 below**

`utils/` is not listed in the Layer 1 definition. However `utils/enums.py` itself only imports from `enum` (stdlib). It carries no infrastructure coupling. `utils/logging.py` imports `opentelemetry` but compiler.py does NOT import that module.

---

### Summary of 1c

No actual infrastructure imports found in Layer 1 production code. All grep matches are either comments/docstrings or intra-layer references. The `utils.enums` coupling is minor and carries no transitive infrastructure dependency.

---

## 1d. configuration coupling

**Layer 1 files scanned for `os.environ`, `.env` reads, `env_file=`, direct env var access.**

**Result: CLEAN — with the single allowed exception.**

- `src/vaultspec_a2a/domain_config.py`: uses `pydantic_settings.BaseSettings` with `SettingsConfigDict(env_prefix="VAULTSPEC_", extra="ignore")`. This is the designated config entry point. **Allowed exception per audit spec.**
- No other Layer 1 file reads env vars directly.
- No `env_file=` path reads found outside `domain_config.py`.
- No `os.environ` calls found in any Layer 1 production file.

---

## 1e. layer 1.5 (`streaming/`) boundary check

**Scanned for imports from `api/`, `database/`, `providers/`, `telemetry/`, `control/`, `worker/`.**

**Result: CLEAN**

All `streaming/` imports resolve exclusively to:
- `..graph.*` (Layer 1)
- `..domain_config` (Layer 1)
- `..thread.errors` (Layer 1)
- `langgraph.*`, `langchain_core.*` (approved external deps)
- stdlib modules

No import from `api/`, `database/`, `providers/`, `telemetry/`, `control/`, or the infrastructure `worker/` package was found.

---

## violations

### Violation: graph/nodes/worker.py naming collision risk

**Layer:** 1
**File(s):** `src/vaultspec_a2a/graph/nodes/worker.py`, `src/vaultspec_a2a/graph/compiler.py:37`
**Severity:** minor
**Description:** `graph/nodes/worker.py` is a Layer 1 graph-node module that shares the name `worker` with the infrastructure `worker/` package. The grep pattern `from.*worker` matches legitimately. No boundary violation exists — `graph/nodes/worker.py` imports nothing from infrastructure — but the naming increases cognitive friction and could cause a future contributor to introduce a real violation while believing the import path is already established.
**Recommendation:** Consider renaming to `graph/nodes/agent_node.py` or `graph/nodes/worker_node.py` to distinguish the Layer 1 graph node from the Layer 2+ infrastructure worker process.

---

### Violation: graph/compiler.py imports from `utils/`

**Layer:** 1
**File(s):** `src/vaultspec_a2a/graph/compiler.py:33`
**Severity:** minor
**Description:** `graph/compiler.py` imports `Model` and `Provider` enums from `vaultspec_a2a.utils.enums`. `utils/` is not defined as part of Layer 1. `utils/enums.py` itself is stdlib-only (no infrastructure coupling), but `utils/logging.py` imports `opentelemetry` — meaning the `utils` package has mixed coupling levels. If a future import of `utils.logging` were added to a Layer 1 file, a telemetry transitive dependency would be introduced silently.
**Recommendation:** Move `Model` and `Provider` enums from `utils/enums.py` into `graph/enums.py` (which already exists and is Layer 1). This eliminates the cross-boundary reach entirely and consolidates domain enums where they belong.

---

## no-violation findings (confirmed clean)

| Area | Status | Notes |
|---|---|---|
| `thread/` imports | CLEAN | stdlib, langchain_core, langgraph only |
| `context/` imports | CLEAN | pydantic, langchain_core, pathlib only |
| `team/` imports | CLEAN | pydantic, tomllib, stdlib only |
| `graph/enums.py` | CLEAN | stdlib only |
| `graph/events.py` | CLEAN | dataclasses + graph/enums only |
| `graph/protocols.py` | CLEAN | stdlib + TYPE_CHECKING guard |
| `graph/nodes/supervisor.py` | CLEAN | Layer 1 + langchain_core/langgraph only |
| `graph/nodes/vault_reader.py` | CLEAN | Layer 1 + langchain_core only |
| `graph/tools/task_queue.py` | CLEAN | stdlib + domain_config only |
| `lifecycle/reconciliation.py` | CLEAN | stdlib only |
| `domain_config.py` | CLEAN | pydantic_settings (allowed exception) |
| `streaming/aggregator.py` | CLEAN | Layer 1 + langgraph only |
| `streaming/buffering.py` | CLEAN | Layer 1 + stdlib only |
| `streaming/emitters.py` | CLEAN | Layer 1 + stdlib + uuid only |
| `streaming/ingest.py` | CLEAN | Layer 1 + langgraph + stdlib only |
| `streaming/subscribers.py` | CLEAN | Layer 1 only |
| `streaming/transformer.py` | CLEAN | Layer 1 + stdlib only |
| `streaming/types.py` | CLEAN | Layer 1 + langgraph + stdlib only |
| `os.environ` in Layer 1 | NONE | Zero occurrences |
| `.env` file reads in Layer 1 | NONE | Zero occurrences |
| `database` imports in Layer 1 | NONE | Zero occurrences |
| `providers` imports in Layer 1 | NONE | Zero occurrences |
| `telemetry` imports in Layer 1 | NONE | Zero occurrences |
| `control` imports in Layer 1 | NONE | Zero occurrences |
| `api` imports in Layer 1 | NONE | Zero occurrences |
| Infrastructure `worker` imports in Layer 1 | NONE | Zero occurrences |

---

## summary

### layer 1 health score: 9.5 / 10

**Violations found:** 2, both minor (naming collision risk + utils boundary reach). Zero critical or moderate violations.

**Can Layer 1 be extracted as a standalone package today?**

**Yes, with one prerequisite step.**

The extraction is 95% ready. The single blocker is the `graph/compiler.py` import of `Model` and `Provider` from `utils/enums`. Those two symbols must either be:
- moved into `graph/enums.py` (preferred), or
- duplicated/re-exported within Layer 1

Once that is done, `thread/`, `context/`, `team/`, `graph/`, `lifecycle/`, `domain_config.py`, and `streaming/` form a dependency-closed set relying only on:
- `langchain_core` (approved)
- `langgraph` (approved)
- `pydantic` / `pydantic_settings` (approved)
- Python stdlib

The `graph/nodes/worker.py` naming issue is cosmetic and does not block extraction — it is a maintenance risk only.

**Test coverage confirms isolation:** 296 tests pass in 0.94 seconds with zero infrastructure.

---

## Section 5: Configuration and Secrets

### 5a. `.env` in version control

`git ls-files | grep "^\.env$"` → no output.

**PASS.** No `.env` file is committed. Only `.env.example` and `.env.integration.example` are tracked.

---

### 5b. Secrets in code

Full scan of `src/` for credential patterns (`password=`, `secret_key=`, `api_key=`, `token=`, `-----BEGIN.*PRIVATE KEY-----`, `sk-...`, `ghp_...`).

Findings in `src/`:

- `tests/conftest.py:311-316` — `.render_as_string(hide_password=False)` is a SQLAlchemy URL serialisation call, not a hardcoded credential. **OK.**
- `tests/evals/conftest.py:23` — `Client(api_key=api_key)` where `api_key = os.environ.get("LANGSMITH_API_KEY")`. No literal value; raises `RuntimeError` if unset. **OK.**

Finding outside `src/` (committed file):

- `docker-compose.prod.postgres.yml:11,26-27,41-42` — **VIOLATION.** Hardcoded credentials committed to version control:
  - `POSTGRES_PASSWORD: vaultspec`
  - `VAULTSPEC_DATABASE_URL: postgresql+asyncpg://vaultspec:vaultspec@postgres:5432/vaultspec`
  - `VAULTSPEC_CHECKPOINT_DATABASE_URL: postgresql://vaultspec:vaultspec@postgres:5432/vaultspec?sslmode=disable`

  The companion `docker-compose.postgres.yml` correctly uses `${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}`. The prod overlay does not follow this pattern.

| ID | Severity | Location | Detail |
|---|---|---|---|
| SEC-01 | HIGH | `docker-compose.prod.postgres.yml:11,26-27,41-42` | Hardcoded `POSTGRES_PASSWORD: vaultspec` and literal DB URLs with embedded password committed to version control. Replace with `${POSTGRES_PASSWORD}` substitution. |

No hardcoded API keys, tokens, or private keys found anywhere in `src/`.

---

### 5c. Configuration scatter

Two config classes exist, both in `src/vaultspec_a2a/`:

- `domain_config.py` → `DomainConfig(BaseSettings)` — pure behavioural knobs (debounce windows, buffer sizes, token budgets). No infrastructure coupling. No `env_file` load. Intentional: Layer 1 modules consume it directly.
- `control/config.py` → `InfraConfig(BaseSettings)` + `Settings(DomainConfig, InfraConfig)` — all infrastructure fields (ports, hosts, database URLs, API keys, filesystem paths). Loads `.env` via `env_file=".env"`. `Settings` composes both via multiple inheritance and is the drop-in replacement for the former `core.config.Settings`.

Docker-compose files carry env-var overrides (expected), all referencing the canonical `VAULTSPEC_*` prefix.

**Assessment:** The two-class split is intentional and correctly scoped. There is one canonical `Settings` object. No pathological scatter.

---

### 5d. `.env.example` completeness

Both `.env.example` and `.env.integration.example` are committed and comprehensive:

- `.env.example` — 170+ lines covering every `VAULTSPEC_*` variable with defaults, inline comments distinguishing MANDATORY vs OPTIONAL, port assignment table, provider API keys as empty placeholders, OTel, mock LLM, frontend Vite vars, CI flags. **PASS.**
- `.env.integration.example` — integration-test-specific overrides (Jaeger OTLP endpoint, test database URLs). **PASS.**

---

## Section 6: Testability Assessment

### 6a. Layer 1 tests pass without infrastructure

Command run:
```
pytest src/vaultspec_a2a/thread/tests/ src/vaultspec_a2a/context/tests/ \
       src/vaultspec_a2a/team/tests/ src/vaultspec_a2a/graph/tests/ \
       src/vaultspec_a2a/streaming/tests/ \
       -x -q --tb=short -k "not requires_vidaimock and not live and not requires_jaeger"
```

Result: **410 passed, 10 deselected in 2.22s. Zero failures.**

- `lifecycle/` has no `tests/` subdirectory (only `reconciliation.py`). Not included in run.

**PASS.**

---

### 6b. Test directory structure

Observed structure:

| Directory | Layer | Tests exist? |
|---|---|---|
| `thread/tests/` | Layer 1 | Yes — `test_errors.py`, `test_models.py`, `test_state.py` |
| `context/tests/` | Layer 1 | Yes — 6 test files |
| `team/tests/` | Layer 1 | Yes — `test_team_config.py` |
| `graph/tests/` | Layer 1 | Yes — `test_compiler.py`, `test_graph_execution.py`, `test_task_queue.py`, `nodes/` |
| `streaming/tests/` | Layer 1.5 | Yes — `test_aggregator.py` |
| `lifecycle/` | Layer 1 | No `tests/` subdirectory — gap |
| `api/tests/` | Layer 2 | (out of scope for this section) |
| `worker/tests/` | Layer 2 | (out of scope for this section) |
| `tests/` (top-level) | Integration | Yes |

The directory-to-layer mapping is immediately clear from paths alone.

**Gap:** `lifecycle/` has no co-located test directory. `reconciliation.py` is untested in-situ.

**Assessment: PASS with one gap.**

---

### 6c. Layer 1 test isolation — Layer 2 import violations

Scan for top-level imports from Layer 2 in all Layer 1 test files:

```
grep -rn "^from.*providers|^from.*control\.config|^from.*api\.|^from.*database|^from.*worker|^from.*telemetry" \
  src/vaultspec_a2a/{thread,context,team,graph,streaming}/tests/ --include="*.py"
```

Raw output:
```
graph/tests/nodes/test_worker_integration.py:32:  from vaultspec_a2a.providers.acp_chat_model import AcpChatModel
graph/tests/nodes/test_worker_integration.py:53:  from vaultspec_a2a.providers.acp_chat_model import AcpChatModel
graph/tests/nodes/test_worker_integration.py:76:  from vaultspec_a2a.providers.acp_chat_model import AcpChatModel
```

**Classification: ACCEPTABLE.** All three occurrences are lazy imports **inside async test function bodies**, not at module top-level. The test module is collected and its non-infra tests run without triggering the import. The tests use a real `acp_simulator.py` subprocess (no mocks), consistent with the no-fakes mandate.

No top-level Layer 2 imports exist in any Layer 1 test file.

**PASS** — with a note that `test_worker_integration.py` carries a soft runtime dependency on `providers/` when those three tests execute. This is correctly scoped as an integration test living inside the `graph/tests/nodes/` directory.

---

## Testability Health Score

| Dimension | Score | Notes |
|---|---|---|
| Layer 1 tests pass without infra | 5/5 | 410 passed, 0 failures, 2.22s |
| Test directory clarity | 4/5 | Clear mapping; `lifecycle/` has no tests |
| Layer 1 isolation — no top-level L2 imports | 5/5 | Zero violations |
| `.env` not committed | 5/5 | Clean |
| Secrets in source (`src/`) | 5/5 | No hardcoded credentials |
| Hardcoded credentials in committed infra files | 3/5 | SEC-01: `docker-compose.prod.postgres.yml` |
| `.env.example` completeness | 5/5 | Comprehensive and well-documented |

**Overall testability health: 32/35 (91%)**

Primary action item: SEC-01 — replace hardcoded Postgres credentials in `docker-compose.prod.postgres.yml` with `${POSTGRES_PASSWORD}` substitution (3 lines affected).

Secondary: add `lifecycle/tests/` coverage for `reconciliation.py`.

---

## Section 2: Entry Point Thinness

**Scope:** Layer 2 — `api/`, `worker/`, `cli/`, `control/`, `protocols/`
**Method:** Static import analysis + file-level business-logic assessment

---

### 2a. Entry Point Cross-Imports

#### api/ → worker/ (string reference only — not a Python import)

`api/app.py` lines 687 and 696 embed the string:

```
"from vaultspec_a2a.worker.app import main; main()"
```

This is a `-c` argument to `subprocess.Popen` — a spawn command, not a Python import statement. No `import` of `worker.*` occurs in `api/`.

#### worker/ → api/schemas/ (shared wire types — architectural, not accidental)

`worker/executor.py` lines 24–28:

```python
from ..api.event_adapter import sequenced_to_dict
from ..api.schemas.internal import (
    DispatchRequest,
    ExecutionStateProjectionPayload,
    ExecutionTaskProjectionPayload,
)
```

This couples the worker to the gateway's IPC contract definition. It is deliberate and does not create a circular dependency, but the import direction (worker → api) is architecturally inverted — the worker is logically downstream of the gateway yet imports from it. Flagged as architectural coupling.

#### All other L2 sibling cross-imports

| Direction | Result |
|---|---|
| cli/ → api/ | none |
| cli/ → worker/ | none |
| cli/ → control/ | none |
| api/ → cli/ | none |
| control/ → api/ | none |
| control/ → worker/ | none |
| protocols/ → api/ | none |
| protocols/ → worker/ | none |

**Cross-import verdict:** No accidental cross-imports between Layer 2 siblings.

---

### 2b. Business Logic in Entry Points

#### api/endpoints.py (1883 lines)

**Assessment: NOT thin. Contains significant business logic.**

Route handlers correctly delegate persistence to `database/crud`. However:

- `_process_metadata()` (lines 332–375): Validates workspace path, auto-discovers `.vault/` context refs, generates thread nicknames by loading team config topology. This is thread-creation policy, not HTTP protocol translation.
- `_enrich_snapshot_from_state()` / `apply_checkpoint_projection()` (lines 700–900, ~200 lines): Classifies LangChain message types, extracts plan entries and artifacts from checkpoint channel values, reconciles tool-call status between checkpoint and in-memory aggregator. Domain projection logic embedded in the API layer.
- `_finalize_snapshot_replay_status()` (lines 925–950): Encodes the reconnection replay/degradation contract as a decision tree. Business rule, not protocol.
- `send_message_endpoint`, `respond_to_permission_endpoint`, `cancel_thread_endpoint`: Each manually orchestrates multi-step sequences — check idempotency → create control action → set repair state → dispatch → update status → commit. Thread lifecycle transition rules written directly into route handlers.

**Framework-swap test:** Replacing FastAPI would require fully understanding thread lifecycle rules, checkpoint projection semantics, and the idempotency pattern. The framework and the business logic are not separable.

---

#### api/websocket.py (719 lines)

**Assessment: Borderline — `ConnectionManager` is clean, but dispatch factories embed guard logic.**

`ConnectionManager` is a well-scoped abstraction. However, the WS dispatch factories defined in `app.py` and wired at lifespan contain:

- Thread-status guards (INPUT_REQUIRED, terminal states) that duplicate identical guards in `endpoints.py`.
- `_ws_mark_failed_and_broadcast()` (lines 353–386 of `app.py`): DB write + WS broadcast as error-recovery orchestration, duplicating the REST-path failure handling in `endpoints.py`.

**Framework-swap test:** Connection-management parts are portable. The dispatch guard and failure-recovery sequences are entangled with `app.state`.

---

#### api/app.py (1507 lines)

**Assessment: Oversized application factory. Infrastructure classes belong in their own modules.**

Beyond app wiring, `app.py` defines:

- `WorkerCircuitBreaker` (lines 159–233): A 3-state reliability primitive (closed/open/half_open) with no FastAPI dependency — a general infrastructure class defined in the wrong place.
- `LazyWorkerSpawner` (lines 804–908): Worker lifecycle management — double-checked locking, adaptive polling, TCP port probing, stderr log management.
- `WorkerWatchdog` (lines 915+): Background restart task with exponential backoff.
- `_CacheControlMiddleware`: HTTP caching header logic.
- `_create_dispatch_message_handler` / `_create_dispatch_control_handler` (lines 389–594): WS dispatch factories that re-encode thread-status guard logic already present in `endpoints.py`.
- `_classify_missing_ws_thread()` (lines 275–350): Queries DB and checkpointer to classify why a thread is missing. Business rule logic in the app factory.

**Framework-swap test:** Replacing FastAPI/uvicorn would be difficult — the spawner, watchdog, and circuit breaker are wired to `app.state` and the FastAPI lifespan pattern throughout.

---

#### worker/executor.py (983 lines)

**Assessment: Appropriate owner of graph lifecycle, but embeds domain logic.**

`Executor` correctly owns graph compilation (LRU cache), event aggregation wiring, and the `astream_events` consumer loop. However:

- `_pre_flight_checkpoint()` (lines 353+): Inspects checkpoint content to detect post-crash reconciliation state and decide whether to short-circuit execution. Encodes LangGraph checkpoint semantics and thread lifecycle rules — domain logic in the executor.
- `_send_graph_registered()`: Sends node metadata to the gateway aggregator via IPC bridge — cross-layer coordination, not pure execution.

**Framework-swap test:** Replacing LangGraph would require heavy edits here. The executor legitimately owns LangGraph integration; the embedded thread-state inspection logic is the concern.

---

### 2c. Database Queries in Entry Points

| Location | Pattern | Verdict |
|---|---|---|
| `api/endpoints.py:245` | `await db.execute(text("SELECT 1"))` | Acceptable — health-check probe only |
| `api/app.py:286–290` | `async with session_factory() as db: await get_thread_execution_state(db, ...)` | Acceptable — delegates to `database/crud` |
| `api/app.py:364–366` | `async with session_factory() as db: await update_thread_status(...)` | Acceptable — delegates to `database/crud` |
| `control/db.py:94–95` | `conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")` | Acceptable — `control/` is a maintenance tool, raw SQLite pragma is intentional |
| `control/db.py:120` | `conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")` | Acceptable — same |
| `control/db.py:214` | `conn.execute(text(f"DELETE FROM {table}"))` | Moderate concern — dynamic table name. Low risk (internal tool) but `database/crud` would be safer |

No ORM model definitions in Layer 2. No raw data-access SQL in `api/` beyond the health-check probe. All route-handler data access goes through `database/crud`.

---

### violations

### Violation: snapshot projection logic embedded in route handler
**Layer:** 2
**File(s):** `src/vaultspec_a2a/api/endpoints.py` (approximately lines 700–900)
**Severity:** moderate
**Description:** `_enrich_snapshot_from_state()` and related helpers (~200 lines) perform LangChain message-type classification, checkpoint channel-value extraction (plan entries, artifacts, tool calls), and aggregator cross-reference for tool-call reconciliation. This is domain projection logic encoding knowledge of the LangGraph state schema, placed directly in the API layer rather than a dedicated projection module.
**Recommendation:** Verify whether `api/projection.py` already partially contains this logic. If not, extract the full projection pipeline there. Route handlers call `build_thread_snapshot(state, aggregator)` and receive a ready `ThreadStateSnapshot`.

### Violation: thread-lifecycle orchestration duplicated across REST and WS paths
**Layer:** 2
**File(s):** `src/vaultspec_a2a/api/endpoints.py`, `src/vaultspec_a2a/api/app.py`
**Severity:** moderate
**Description:** The sequence "check idempotency → create control action → set repair state → dispatch to worker → update thread status → commit" is implemented independently in REST handlers and in the WS dispatch factories. Thread-status guard logic (INPUT_REQUIRED, terminal states) is also duplicated across both sites. Divergence between the two paths is a maintenance risk; changes must be applied in two places.
**Recommendation:** Extract a `ThreadDispatchService` in a support layer callable from both REST handlers and WS factories. The dispatch sequence and guard logic live in one place.

### Violation: worker subprocess lifecycle management in api/app.py
**Layer:** 2
**File(s):** `src/vaultspec_a2a/api/app.py` (`LazyWorkerSpawner`, `WorkerWatchdog`, `WorkerCircuitBreaker`, ~300 lines)
**Severity:** minor
**Description:** Three infrastructure classes are defined inside the application factory file. `WorkerCircuitBreaker` is a general reliability primitive with no FastAPI dependency. The file has grown to 1507 lines, mixing app construction with process supervision and network reliability concerns.
**Recommendation:** Extract to `api/worker_lifecycle.py` or a `gateway/` sub-module. `app.py` imports and wires them without defining them.

### Violation: _process_metadata business logic in route handler
**Layer:** 2
**File(s):** `src/vaultspec_a2a/api/endpoints.py` (lines 332–375)
**Severity:** minor
**Description:** `_process_metadata()` loads team config to derive topology, discovers `.vault/` context refs, and generates thread nicknames — application policy decisions unrelated to HTTP.
**Recommendation:** Move to `context/` or a thread-creation service. The route handler passes validated input and receives enriched metadata.

### Violation: worker/executor.py imports from api/schemas/ (inverted layer dependency)
**Layer:** 2
**File(s):** `src/vaultspec_a2a/worker/executor.py` (lines 24–28)
**Severity:** minor (architectural, deliberate but inverted)
**Description:** The worker imports `DispatchRequest` and execution projection payload types from `api/schemas/internal`, coupling a downstream process module to the gateway's schema namespace. If `api/schemas/` is reorganised, `worker/` breaks.
**Recommendation:** Move shared IPC types (`DispatchRequest`, `ExecutionStateProjectionPayload`, `ExecutionTaskProjectionPayload`) to a neutral location — `protocols/` or a new `ipc/` module — that neither `api/` nor `worker/` owns hierarchically. Both import from the shared contract location.

---

### layer 2 health assessment

**Could you swap FastAPI for another framework without touching business logic?**

**No — not in the current state.**

`endpoints.py` and `app.py` contain substantial business logic: checkpoint projection (~200 lines), thread lifecycle state machines, multi-step idempotency orchestration, and context-discovery rules. Swapping FastAPI for any other ASGI framework would require understanding and porting all of this. The `WorkerCircuitBreaker`, `LazyWorkerSpawner`, and `WorkerWatchdog` classes are wired to `app.state` and the FastAPI lifespan pattern, making them non-portable without significant refactoring.

`websocket.py` is closer to thin — `ConnectionManager` is a clean abstraction — but WS dispatch factories in `app.py` re-encode thread-status business rules that duplicate `endpoints.py`.

`worker/executor.py` is the most defensible entry point: it legitimately owns LangGraph lifecycle, though checkpoint-inspection and bridge coordination add domain weight.

**Root cause:** No service/use-case layer exists between Layer 2 entry points and Layer 3 domain modules. Route handlers reach directly into `database/crud`, `streaming/aggregator`, and `context/` and orchestrate multi-step operations inline. A thin service layer would allow entry points to become true protocol translators.

**Priority improvements:**

- Extract `ThreadDispatchService` to eliminate REST/WS orchestration duplication (moderate)
- Verify/complete extraction of snapshot projection logic to `api/projection.py` (moderate)
- Move shared IPC types out of `api/schemas/` to break the inverted worker→api dependency (minor)
- Extract `WorkerCircuitBreaker`/`LazyWorkerSpawner`/`WorkerWatchdog` from `app.py` (minor)
