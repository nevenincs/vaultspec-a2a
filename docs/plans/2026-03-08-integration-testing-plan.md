# Integration Testing Plan — 2026-03-08

## Overview

Implementation plan for tasks TESTING-01 through TESTING-04 + VERIFY-01.
Covers the full integration test suite for VaultSpec A2A's multi-service
architecture (MCP Server, Gateway, Worker).

**Research inputs:**

- `docs/research/2026-03-08-integration-testing-stack.md` — library validation
- `docs/research/2026-03-08-cross-process-tracing.md` — W3C traceparent propagation
- `docs/research/2026-03-08-multi-service-integration-testing.md` — framework survey
- `docs/research/2026-03-08-process-supervision-models.md` — supervision patterns

---

## Hard-Fail Mandate

**Non-negotiable:** Tests must HARD FAIL, never skip.

Fixtures own the full service lifecycle. If a service fails to start, the
fixture raises, the test fails. That failure is the correct signal.

**FORBIDDEN:**

- `pytest.skip()` based on service availability
- `shutil.which()` skip guards
- `@pytest.mark.requires_*` markers that gate on availability
- `MemorySaver`, `MockTransport`, `dependency_overrides` replacing real services
- Any "graceful degradation" in test fixtures

**REQUIRED:**

- Real services exercised in every test
- Hard failure when services are unavailable
- Full lifecycle (start -> health-check -> test -> teardown) in session-scoped fixtures
- `tenacity` with `reraise=True` for health polling — last exception propagates
- `testcontainers-python` for Docker-based services (Jaeger, otelcol) when needed

---

## Architecture

### Two Test Tiers

```
TIER 1: Unit Tests (rust-style)
  Location: src/vaultspec_a2a/{module}/tests/
  Scope:    Individual functions/classes
  DB:       Real in-memory SQLite (AsyncSqliteSaver with :memory:)
  Services: None — test logic, not wiring
  Mocks:    FORBIDDEN

TIER 2: Integration Tests
  Location: src/vaultspec_a2a/tests/
  Scope:    Full service stack (gateway + worker subprocesses)
  DB:       Real SQLite on temp filesystem
  Services: Real subprocess-based gateway + worker
  Mocks:    FORBIDDEN
  Transport: Real HTTP via httpx.AsyncClient
```

### Fixture Dependency Graph

```
tmp_path_factory (session, built-in)
  └── service_env (session)
        ├── gateway_process (session, async) ←── _start_and_wait()
        │     └── _wait_for_health() [tenacity, reraise=True]
        └── worker_process (session, async) ←── _start_and_wait()
              └── _wait_for_health() [tenacity, reraise=True]

gateway_process + worker_process
  └── service_stack (session) → (gateway_url, worker_url)
        └── gateway_client (session) → httpx.AsyncClient
              └── event_hooks: [_log_request, _log_response]

span_collector (function) → (TracerProvider, InMemorySpanExporter)
  └── collected_spans (function, convenience alias)
```

### Session-Scoped Event Loop

All async fixtures use `scope="session", loop_scope="session"`. All async tests
declare `@pytest.mark.asyncio(loop_scope="session")`. This ensures one event
loop for the entire integration test session — subprocesses start once, shared
across all tests.

---

## Tool Choices with Rationale

### 1. asyncio.subprocess (stdlib) — Process Lifecycle

**Choice over:** multiprocessing, psutil-only, testcontainers

**Rationale:** Gateway and Worker are uvicorn ASGI apps. We start them as real
`uvicorn` subprocesses via `asyncio.create_subprocess_exec()`. This is the
exact same launch mechanism as production. No Docker needed for Python services.

```python
process = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "uvicorn",
    "vaultspec_a2a.api.app:create_app",
    "--factory", "--host", "127.0.0.1", "--port", str(port),
    env=env,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```

**Teardown:** Windows uses `taskkill /T /F /PID {pid}` for tree kill. POSIX uses
`os.killpg()`. Implemented in `_kill_process_tree()` in conftest.py.

**Future:** psutil (`Process.children(recursive=True)`) would be a cleaner
cross-platform tree kill. Not yet installed — add `psutil>=6.0.0` to dev deps
when needed.

### 2. tenacity with `reraise=True` — Health Polling

**Choice over:** manual polling loops, asyncio.wait_for

**Rationale:** Exponential backoff with hard-fail semantics. The `reraise=True`
flag is critical — without it, tenacity swallows the final exception and returns
`RetryError`. With it, the actual `_HealthCheckError` propagates, which becomes
a `pytest.fail()` in the caller.

```python
@retry(
    retry=retry_if_exception_type(_HealthCheckError),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
    stop=stop_after_delay(30.0),
    reraise=True,  # CRITICAL: propagates → hard failure
)
async def _wait_for_health(url: str) -> None:
    ...
```

Auto-detects async: tenacity uses `AsyncRetrying` + `asyncio.sleep()` when the
decorated function is a coroutine. No special configuration needed.

### 3. httpx.AsyncClient — Test Transport

**Choice over:** requests, aiohttp, TestClient

**Rationale:** httpx is already the production HTTP client. Same library for
tests means identical timeout/retry behavior. `event_hooks` provide request/
response trace logging without transport replacement.

```python
async with httpx.AsyncClient(
    base_url=gateway_url,
    timeout=httpx.Timeout(30.0, connect=5.0),
    event_hooks={"request": [_log_request], "response": [_log_response]},
) as client:
    yield client
```

### 4. InMemorySpanExporter (OTel SDK) — Span Assertions

**Choice over:** mock exporters, log parsing, external Jaeger queries

**Rationale:** Real OTel exporter (not a mock) that stores spans in a thread-safe
list. Wired via `SimpleSpanProcessor` for synchronous export. Can run alongside
production exporters — `TracerProvider.add_span_processor()` is additive.

OTel SDK silently drops export failures (4-layer error handling chain in
BatchProcessor/SimpleSpanProcessor). Tests never fail because OTLP endpoint is
unreachable — they only fail when spans don't match assertions.

### 5. testcontainers-python — Docker Service Lifecycle (Future)

**When:** Needed for Jaeger/otelcol in trace verification tests.

**Rationale:** `DockerContainer.start()` raises if Docker is unavailable = hard
fail (mandate compliant). Manages port mapping, health waiting, teardown.

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def jaeger():
    container = DockerContainer("jaegertracing/jaeger:latest")
    container.with_exposed_ports(4317, 16686)
    container.with_env("COLLECTOR_OTLP_ENABLED", "true")
    container.start()  # Raises if Docker unavailable = hard-fail
    wait_for_logs(container, "Starting HTTP server", timeout=30)
    otlp_port = container.get_exposed_port(4317)
    host = container.get_container_host_ip()
    try:
        yield {"otlp_endpoint": f"http://{host}:{otlp_port}"}
    finally:
        container.stop()
```

**Not yet installed.** Add `testcontainers>=4.14.0` to dev deps when implementing
trace verification tests.

### 6. pytest-timeout — Hard Deadline Enforcement

**Already configured:** 300s global timeout in pyproject.toml. Windows uses
`thread` method (no SIGALRM). Per-test override via `@pytest.mark.timeout(60)`.

---

## Test Tiers — Implementation Plan

### TESTING-01: Multi-service Integration Test Harness (COMPLETED)

**Status:** Task #33 completed. Harness operational.

**Location:** `src/vaultspec_a2a/tests/conftest.py`

**Deliverables:**

- Session-scoped fixtures: `free_port`, `worker_free_port`, `service_env`,
  `gateway_process`, `worker_process`, `service_stack`, `gateway_client`
- Health polling: `_wait_for_health()` with tenacity `reraise=True`
- Process management: `_start_uvicorn()`, `_stop_process()`, `_kill_process_tree()`
- OTel fixtures: `span_collector`, `collected_spans`
- 6 smoke tests passing against live stack

**Location of smoke tests:** `src/vaultspec_a2a/tests/test_smoke.py`

Tests:

1. `test_gateway_health_returns_ok` — GET /health returns status=ok
2. `test_gateway_health_reports_worker_spawned` — worker_spawned + circuit_breaker present
3. `test_worker_health_returns_ok` — direct worker /health probe
4. `test_api_health_returns_checks` — aggregated /api/health
5. `test_list_threads_empty` — GET /api/threads returns empty list
6. `test_list_team_presets` — GET /api/teams returns presets

### TESTING-02: Crash Recovery Integration Tests (IN PROGRESS)

**Status:** Task #34 in progress (coder).

**Location:** `src/vaultspec_a2a/tests/test_crash_recovery.py`

**Architecture decision:** Per-test stack (not session-scoped). Each crash test
gets its own gateway+worker because crash/restart mutates process state. Uses
`VAULTSPEC_AUTO_SPAWN_WORKER=true` so the gateway owns the worker subprocess
and the watchdog can detect exit.

Tests:

1. `test_gateway_survives_worker_death` — read-only endpoints work after worker kill
2. `test_worker_crash_triggers_watchdog_restart` — watchdog detects crash, restarts
3. `test_circuit_breaker_opens_during_worker_crash` — CB opens on crash, closes on restart
4. `test_exhausted_restart_retries` — port-blocked worker, watchdog gives up after 3 retries

**Key patterns:**

- `_create_autospawn_gateway()` — per-test gateway with auto-spawn=true
- `_kill_worker_on_port()` — Windows `netstat`/POSIX `fuser` to find and kill worker
- `_wait_for_worker_status()` — tenacity poll of /health until worker_status matches
- Port blocking with `socket.bind()` to simulate persistent failure

**Timeouts:** 90s per test (120s for exhausted retries). Global 300s session.

### TESTING-03: IPC and Heartbeat Integration Tests (PENDING)

**Status:** Task #35 pending. Blocked by #33 (now resolved).

**Location:** `src/vaultspec_a2a/tests/test_ipc_integration.py`

**Fixtures needed:** Session-scoped `service_stack` from conftest.py.

Tests:

1. `test_heartbeat_updates_gateway_state`
   - Start full stack, wait 15s (heartbeat interval 10s)
   - GET /health, assert `worker_last_heartbeat` is recent (<15s old)
   - Assert `worker_connected = true`

2. `test_heartbeat_stale_detection`
   - Start full stack, verify heartbeat arriving
   - Windows: cannot SIGSTOP. Alternative: accelerate `_WORKER_HEARTBEAT_TIMEOUT`
     to 5s via env var, then kill the worker's heartbeat sender without killing
     the whole worker. Fallback: kill worker, assert stale detection before
     watchdog restart.
   - Assert /health shows worker stale/error state

3. `test_event_batch_delivery_ordering`
   - Start full stack
   - POST /api/threads with preset + content
   - Connect WebSocket, collect events
   - Assert events arrive in monotonic timestamp order (IPC-01)
   - Assert events include `dispatch_id` (IPC-04)

4. `test_dispatch_under_transient_worker_unavailability`
   - Start full stack, kill worker
   - POST /api/threads immediately
   - Expect 500/503
   - Assert thread status = "failed" (PROD-012)

**Windows caveat for test 2:** No SIGSTOP on Windows. Options:

- (a) Kill worker and check stale detection in the window before watchdog restart
- (b) Add `VAULTSPEC_HEARTBEAT_TIMEOUT` env var override for testing
- (c) Accept that this specific test only works on POSIX

### TESTING-04: MCP End-to-End Integration Test (PENDING)

**Status:** Task #36 pending. Blocked by #33 (now resolved).

**Location:** `src/vaultspec_a2a/tests/test_mcp_e2e.py`

**Architecture:** MCP tools are plain async functions decorated with `@mcp.tool()`.
They call loopback REST at `settings.api_base_url`. Can be called directly
without stdio transport.

Tests:

1. `test_mcp_list_threads_without_worker`
   - Start only gateway (no worker)
   - Set `_gateway_connected = True`, configure `_mcp_settings` to point at test gateway
   - Call `list_threads()` directly
   - Assert returns empty list (PHASE-1b: read-only works without worker)

2. `test_mcp_start_thread_dispatches_to_worker`
   - Start full stack
   - Configure MCP settings to point at test gateway
   - Call `start_thread()` directly
   - Verify response contains thread_id
   - GET /api/threads/{thread_id}/state — verify thread exists

3. `test_mcp_degraded_mode_error_messages`
   - Do NOT start gateway
   - Call `start_thread()` — expect ToolError with actionable message
   - Verify message contains "uv run vaultspec service start"
   - Call `list_threads()` — expect connection error message

4. `test_mcp_circuit_breaker_503_translation`
   - Start gateway, do NOT start worker
   - Drive circuit breaker open (3 failed dispatches)
   - Call `start_thread()` via MCP — expect ToolError mentioning "circuit breaker"

### VERIFY-01: Live Stack E2E Smoke Test (IN PROGRESS)

**Status:** Task #38 in progress (coder).

**Location:** `src/vaultspec_a2a/tests/test_verify_e2e.py`

**Purpose:** North star test — prove the entire production hypothesis works.

**The hypothesis:**
> IDE starts MCP server -> gateway auto-starts -> worker auto-starts -> agent
> tools work -> worker crash detected -> watchdog restarts worker -> system
> recovers -> tools work again

**Phase A — Startup Chain:**

1. Start gateway subprocess (auto-spawn enabled)
2. Poll /health until status=ok
3. POST /api/threads with vaultspec-solo-coder preset
4. Assert 201 with thread_id
5. Poll thread status until terminal

**Phase B — Crash Recovery:**
6. Kill worker process
7. Poll /health until worker_status = "restarting"
8. Wait for watchdog restart, poll until worker_status = "up"
9. Assert circuit_breaker returns to "closed"
10. POST /api/threads again — assert dispatch succeeds

---

## Execution Order

```
TESTING-01 (harness) ─── COMPLETED
    │
    ├── TESTING-02 (crash recovery) ─── IN PROGRESS (coder)
    │
    ├── TESTING-03 (IPC/heartbeat) ─── PENDING
    │
    ├── TESTING-04 (MCP e2e) ─── PENDING
    │
    └── VERIFY-01 (north star e2e) ─── IN PROGRESS (coder)
              │
              └── MANDATE #56 (replace mock conftest) ─── BLOCKED ON VERIFY-01
```

TESTING-02 through TESTING-04 are independent of each other (all depend only on
TESTING-01). VERIFY-01 depends on TESTING-01 + MCP-UX-01. Task #56 (mock
replacement) is blocked on VERIFY-01 proving the live harness works.

---

## Environment Requirements

### Currently Installed

- httpx (production + test transport)
- tenacity (health polling with `reraise=True`)
- pytest-asyncio (async fixtures, session scope)
- pytest-timeout (300s global, per-test overrides)
- opentelemetry-sdk (InMemorySpanExporter, TracerProvider, SimpleSpanProcessor)

### To Be Added (`[dependency-groups] dev`)

```toml
[dependency-groups]
dev = [
  "psutil>=6.0.0",          # Process tree inspection + cross-platform kill
  "testcontainers>=4.14.0", # Docker container lifecycle for Jaeger/otelcol
]
```

### Runtime

- Python 3.13 on Windows 11
- No WSL dependency
- SQLite (temp filesystem, isolated per session/test)
- Docker Desktop (only for testcontainers-based trace tests, not for gateway/worker)

---

## Configuration

### pyproject.toml Integration Test Settings

```toml
[tool.pytest.ini_options]
markers = [
    "live: integration tests requiring real service stack",
]
asyncio_mode = "strict"
timeout = 300
```

### Running Integration Tests

```bash
# All integration tests (requires services to start)
pytest src/vaultspec_a2a/tests/ -m live -x -v

# Smoke only
pytest src/vaultspec_a2a/tests/test_smoke.py -m live -x -v

# Crash recovery only (slower — per-test stack)
pytest src/vaultspec_a2a/tests/test_crash_recovery.py -m live -x -v

# Default run excludes integration tests
pytest -m "not live"
```

---

## Remaining Work After Task Completion

1. **Task #56 — Mock Replacement:** Once VERIFY-01 passes, migrate
   `src/vaultspec_a2a/api/tests/conftest.py` to use real services. Remove
   MockTransport, MemorySaver, all dependency_overrides. Unit tests stay in
   module subdirs with in-memory SQLite.

2. **Trace Verification Tests:** Add testcontainers-based Jaeger/otelcol
   fixtures. Assert W3C traceparent propagation across gateway->worker HTTP
   boundary. Validate span names, attributes, parent-child relationships.

3. **psutil Integration:** Replace Windows `taskkill /T` + POSIX `os.killpg()`
   with `psutil.Process.children(recursive=True)` for cleaner cross-platform
   tree kill. Also enables port-binding assertions in tests.
