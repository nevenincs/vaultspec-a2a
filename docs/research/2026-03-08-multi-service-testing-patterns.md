# Multi-Service Lifecycle Testing Patterns — 2026-03-08

## Context

VaultSpec A2A's integration tests spawn real gateway + worker subprocesses and
exercise them via HTTP. This document researches how production Python projects
test multi-process service stacks without mocks, focusing on fixture patterns,
lifecycle management, and real-world precedents.

**Related documents:**
- `2026-03-08-multiservice-testing-research.md` — Framework evaluation
- `2026-03-08-integration-testing-stack.md` — Library-by-library API validation
- `docs/plans/2026-03-08-integration-testing-plan.md` — Implementation plan

---

## 1. Session-Scoped Subprocess Fixtures

### 1.1 The Core Pattern

The fundamental pattern for testing multi-service stacks: session-scoped async
fixtures that own the entire lifecycle — start, health-check, yield, teardown.

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_process(service_env, free_port):
    process = await _start_and_wait(
        env=service_env,
        module="myapp.gateway:create_app",
        port=free_port,
        label="Gateway",
    )
    yield process
    await _stop_process(process)
```

**Why session-scoped:**
- Services take 2-5s to start. Starting per-test wastes 90%+ of test time.
- Session scope means one startup for the entire test suite.
- Tradeoff: tests must not mutate shared state destructively (or must clean up).

**Why `loop_scope="session"`:**
- pytest-asyncio strict mode requires explicit loop scope declaration.
- Session-scoped async fixtures MUST use `loop_scope="session"` — otherwise
  pytest-asyncio creates a new event loop per test, breaking subprocess handles.
- All async tests must also declare `@pytest.mark.asyncio(loop_scope="session")`.

### 1.2 Our Implementation

`src/vaultspec_a2a/tests/conftest.py` implements this pattern with:

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `free_port` / `worker_free_port` | session | Dynamic port allocation |
| `service_env` | session | Isolated env (tmp DB, unique ports, no auth) |
| `gateway_process` | session | Gateway subprocess lifecycle |
| `worker_process` | session | Worker subprocess lifecycle |
| `service_stack` | session | Bundle: `(gateway_url, worker_url)` |
| `gateway_client` | session | httpx.AsyncClient with event_hook tracing |
| `span_collector` | function | InMemorySpanExporter per test |

### 1.3 Fixture Dependency Graph

```
tmp_path_factory (session, built-in)
  └── service_env (session) ← env isolation
        ├── gateway_process (session, async)
        │     └── _start_and_wait() → _wait_for_health() [tenacity]
        └── worker_process (session, async)
              └── _start_and_wait() → _wait_for_health() [tenacity]

gateway_process + worker_process + free_port + worker_free_port
  └── service_stack (session) → (gateway_url, worker_url)
        └── gateway_client (session) → httpx.AsyncClient
              └── event_hooks: [_log_request, _log_response]

span_collector (function) → (TracerProvider, InMemorySpanExporter)
```

---

## 2. Environment Isolation

### 2.1 The Problem

Integration tests must not interfere with the developer's running instance.
Port conflicts, database corruption, and stale state are all failure modes.

### 2.2 Full Isolation Strategy

```python
@pytest.fixture(scope="session")
def service_env(free_port, worker_free_port, tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("integration")
    return {
        **os.environ,
        # Unique ports — no collision with dev server
        "MYAPP_PORT": str(free_port),
        "MYAPP_WORKER_PORT": str(worker_free_port),
        # Temp database — auto-cleaned by pytest
        "MYAPP_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_dir / 'test.db'}",
        # Disable features that interfere with testing
        "MYAPP_AUTO_SPAWN_WORKER": "false",  # We spawn explicitly
        "MYAPP_INTERNAL_TOKEN": "",           # No auth in tests
        "LANGSMITH_TRACING": "false",         # No external calls
    }
```

**Key decisions:**
- `**os.environ` inherits PATH, PYTHONPATH, etc. — required for subprocess
- Dynamic ports via `socket.bind(("127.0.0.1", 0))`
- `tmp_path_factory.mktemp()` provides pytest-managed temp directories
- Auto-spawn disabled because tests manage the worker explicitly
- External service tracing disabled to prevent flaky tests

### 2.3 Database Isolation Patterns

| Pattern | Pros | Cons |
|---------|------|------|
| Temp file per session | Simple, pytest manages cleanup | WAL mode may leave -wal/-shm files |
| `:memory:` | Zero I/O, fastest | Can't share across processes |
| Named temp with cleanup | Full control | Manual cleanup needed |
| Docker volume mount | Full isolation | Requires Docker |

**Our choice:** Temp file per session (`tmp_path_factory`). SQLite WAL mode
allows the gateway and worker to share the same database file. The pytest
temp directory is cleaned up after the session.

---

## 3. Health Polling Patterns

### 3.1 tenacity with `reraise=True`

The recommended pattern for health polling with hard-fail semantics:

```python
from tenacity import (
    retry, retry_if_exception_type,
    wait_exponential, stop_after_delay,
)

class _HealthCheckError(Exception):
    pass

@retry(
    retry=retry_if_exception_type(_HealthCheckError),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
    stop=stop_after_delay(30.0),
    reraise=True,  # CRITICAL: propagates actual exception on final failure
)
async def _wait_for_health(url: str) -> None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/health", timeout=2.0)
            if resp.status_code != 200:
                raise _HealthCheckError(f"HTTP {resp.status_code}")
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise _HealthCheckError(str(exc)) from exc
```

**Why `reraise=True`:**
- Without it: tenacity wraps the final exception in `RetryError`, losing context
- With it: the actual `_HealthCheckError` propagates with the real failure message
- This becomes a `pytest.fail()` in the fixture, giving the developer actionable output

**Why exponential backoff (not fixed interval):**
- Initial polls at 100ms catch fast startups (service ready in <1s)
- Backoff to 2s avoids hammering during slow startups
- Total budget: 30s (sufficient for uvicorn + database init + migrations)

### 3.2 Hard-Fail on Health Timeout

```python
async def _start_and_wait(env, module, port, label):
    process = await _start_uvicorn(env, module, port)
    try:
        await _wait_for_health(f"http://127.0.0.1:{port}")
    except (_HealthCheckError, Exception):
        # Capture stderr for diagnostics
        stderr_data = b""
        if process.stderr:
            stderr_data = await asyncio.wait_for(
                process.stderr.read(4096), timeout=2.0,
            )
        await _stop_process(process)
        pytest.fail(
            f"{label} did not start on port {port} within 30s.\n"
            f"stderr: {stderr_data.decode()[:1000]}"
        )
    return process
```

**Key principles:**
- Fixture RAISES on failure — test FAILS (not skips)
- stderr capture provides diagnostic context
- Process is killed on failure (no orphans)
- Truncate stderr to 1000 chars to prevent pytest output explosion

---

## 4. Process Cleanup Patterns

### 4.1 Platform-Aware Process Tree Kill

```python
async def _kill_process_tree(pid: int) -> None:
    if sys.platform == "win32":
        proc = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    else:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
```

### 4.2 Defense-in-Depth Cleanup

```python
async def _stop_process(process):
    if process.returncode is not None:
        return  # Already dead
    try:
        await _kill_process_tree(process.pid)
    except Exception:
        process.kill()  # Fallback
    try:
        await asyncio.wait_for(process.wait(), timeout=10.0)
    except TimeoutError:
        process.kill()  # Nuclear option
```

**Why defense-in-depth:**
- `taskkill` may fail (process already dead, access denied)
- `process.kill()` as fallback catches all edge cases
- Final `wait()` with timeout prevents hanging test session
- Dead process check (`returncode is not None`) avoids killing PID 0

### 4.3 Orphan Prevention

Tests that crash mid-execution can leave orphaned subprocesses. Mitigations:

| Strategy | How | Our Status |
|----------|-----|------------|
| Fixture teardown | pytest calls `yield` cleanup | IMPLEMENTED |
| `atexit` handler | Register `_stop_process` at module level | NOT NEEDED (pytest handles) |
| Process group | `CREATE_NEW_PROCESS_GROUP` + group kill | PARTIAL (Windows only) |
| pytest-timeout | Hard deadline kills test process | CONFIGURED (300s) |
| CI timeout | GitHub Actions `timeout-minutes` | RECOMMENDED |

---

## 5. Per-Test vs Session-Scoped Service Stacks

### 5.1 When to Use Session Scope

- **Smoke tests**: Read-only queries against a stable service stack
- **Endpoint tests**: CRUD operations that don't corrupt shared state
- **IPC/heartbeat tests**: Observing service behavior without mutation

### 5.2 When to Use Per-Test Scope

- **Crash recovery tests**: Killing the worker mutates process state irreversibly
- **Circuit breaker state tests**: State transitions need clean initial state
- **Auto-spawn tests**: Testing the gateway's worker auto-spawn requires
  `VAULTSPEC_AUTO_SPAWN_WORKER=true`, which changes the stack behavior

**Our crash recovery tests** (`test_crash_recovery.py`) use per-test fixtures:

```python
@pytest_asyncio.fixture
async def autospawn_gateway():
    """Per-test gateway with auto-spawn enabled."""
    gw_port = _find_free_port()
    wk_port = _find_free_port()
    env = {
        **os.environ,
        "VAULTSPEC_PORT": str(gw_port),
        "VAULTSPEC_WORKER_PORT": str(wk_port),
        "VAULTSPEC_AUTO_SPAWN_WORKER": "true",  # Gateway owns the worker
    }
    process = await _start_and_wait(env, "gateway:create_app", gw_port, "GW")
    yield process, gw_port, wk_port
    await _stop_process(process)
```

---

## 6. How Real Projects Test Multi-Process Stacks

### 6.1 FastAPI TestClient (in-process, no subprocess)

FastAPI's `TestClient` uses Starlette's `TestClient` which wraps the ASGI app
in a synchronous test transport. No real HTTP, no real subprocess.

**Not applicable to us:** We need real subprocess boundaries for IPC testing.

### 6.2 Locust / pytest-benchmark (load testing)

Locust spawns real HTTP traffic against a running service. Tests start the
service as a subprocess, then run Locust against it.

**Partially applicable:** We use the same "start subprocess, hit HTTP" pattern
but for correctness testing, not load testing.

### 6.3 Docker Compose Test Stacks

Projects like Sentry, GitLab, and Airflow use docker-compose to spin up
test stacks:

```yaml
# test-compose.yml
services:
  gateway:
    build: .
    ports: ["8000:8000"]
  worker:
    build: .
    depends_on: [gateway]
    ports: ["8001:8001"]
  db:
    image: postgres:16
```

**Not applicable for local dev:** Requires Docker, adds 10-30s startup overhead.
Better for CI pipelines. We use subprocess spawning for local dev, Docker for
CI/prod testing.

### 6.4 pytest-docker-compose

Wraps docker-compose in pytest fixtures:

```python
@pytest.fixture(scope="session")
def docker_services(docker_ip, docker_services):
    port = docker_services.port_for("gateway", 8000)
    docker_services.wait_until_responsive(
        timeout=30.0,
        check=lambda: is_healthy(f"http://{docker_ip}:{port}/health")
    )
```

**Verdict:** Useful for projects already Dockerized for testing. We prefer
subprocess spawning (faster, no Docker dependency).

### 6.5 testcontainers-python

Programmatic Docker container management:

```python
from testcontainers.core.container import DockerContainer

@pytest_asyncio.fixture(scope="session")
async def jaeger():
    container = DockerContainer("jaegertracing/jaeger:latest")
    container.with_exposed_ports(4317, 16686)
    container.start()  # Raises if Docker unavailable = hard-fail
    yield container
    container.stop()
```

**Our plan:** Use for Jaeger/otelcol in trace verification tests (Phase 2).
Not for gateway/worker (subprocess is better for Python services).

### 6.6 Hypothesis Stateful Testing

Hypothesis can generate sequences of API calls to find state machine bugs:

```python
from hypothesis.stateful import RuleBasedStateMachine, rule

class ThreadStateMachine(RuleBasedStateMachine):
    @rule()
    def create_thread(self):
        resp = self.client.post("/api/threads", json={...})
        assert resp.status_code == 201

    @rule()
    def cancel_thread(self):
        resp = self.client.post(f"/api/threads/{self.thread_id}/cancel")
        # Should not crash regardless of current state
```

**Verdict:** Valuable for state machine correctness (thread status transitions,
circuit breaker states). Deferred to Phase 3.

---

## 7. Three-Tier Trace Testing Architecture

Our conftest implements a three-tier tracing strategy:

### Tier 1: httpx Event Hooks (Request/Response Logging)

```python
gateway_client = httpx.AsyncClient(
    event_hooks={
        "request": [_log_request],
        "response": [_log_response],
    },
)
```

**What it captures:** Every HTTP request/response between test and gateway.
Logged at DEBUG level. No external dependency.

### Tier 2: InMemorySpanExporter (In-Process Spans)

```python
exporter = InMemorySpanExporter()
provider = TracerProvider(resource=Resource.create({...}))
provider.add_span_processor(SimpleSpanProcessor(exporter))
```

**What it captures:** OTel spans created within the test process. Does NOT
capture spans from subprocess gateway/worker.

**Use case:** Verify that test-side instrumentation produces correct spans.
Assert span names, attributes, parent-child relationships.

### Tier 3: otelcol + Jaeger (Full Distributed Tracing)

```python
@pytest.mark.requires_otelcol
async def test_trace_propagation(gateway_client):
    # Send request with traceparent header
    resp = await gateway_client.post(
        "/api/threads",
        headers={"traceparent": "00-..."},
    )
    # Query Jaeger API for the trace
```

**What it captures:** Full W3C traceparent propagation across process boundaries.
Requires running Jaeger + otelcol. Uses `@requires_otelcol` marker that
hard-fails (not skips) when collector is unavailable.

**Status:** Marker and probe implemented. Jaeger fixture via testcontainers
deferred to Phase 2.

---

## 8. Anti-Patterns in Multi-Service Testing

### 8.1 Mocking the Service Boundary

```python
# WRONG: replaces real HTTP with fake transport
app.dependency_overrides[get_worker_client] = lambda: MockClient()

# CORRECT: spawn real worker, hit it with real HTTP
process = await _start_uvicorn(env, "worker:create_app", port)
```

### 8.2 Skipping on Service Unavailability

```python
# WRONG: masks failures
if not shutil.which("uvicorn"):
    pytest.skip("uvicorn not available")

# CORRECT: fixture owns lifecycle, fails if broken
process = await _start_and_wait(env, module, port, label)
# If this fails, the test fails. That's the correct signal.
```

### 8.3 Sharing State Between Tests Without Cleanup

```python
# WRONG: test B depends on test A's side effects
def test_create_thread():
    resp = client.post("/api/threads", json={...})
    # Leaves thread in database

def test_list_threads():
    resp = client.get("/api/threads")
    assert len(resp.json()) == 1  # Depends on test_create!

# CORRECT: each test creates its own state
def test_list_threads():
    client.post("/api/threads", json={...})  # Create locally
    resp = client.get("/api/threads")
    assert len(resp.json()) >= 1  # >= not ==
```

### 8.4 Fixed Ports

```python
# WRONG: collides with dev server
PORT = 8000

# CORRECT: dynamic allocation
def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
```

---

## 9. Recommendations

| Priority | Pattern | Status |
|----------|---------|--------|
| P0 | Session-scoped subprocess fixtures | IMPLEMENTED |
| P0 | Dynamic port allocation | IMPLEMENTED |
| P0 | tenacity health polling with reraise=True | IMPLEMENTED |
| P0 | Platform-aware process tree kill | IMPLEMENTED |
| P0 | Hard-fail on fixture setup (no skip) | IMPLEMENTED |
| P0 | Environment isolation (tmp DB, unique ports) | IMPLEMENTED |
| P1 | Per-test fixtures for crash recovery | IMPLEMENTED |
| P1 | Three-tier trace testing architecture | IMPLEMENTED (Tier 1+2) |
| P2 | testcontainers for Jaeger/otelcol | DEFERRED (Phase 2) |
| P2 | Hypothesis stateful testing | DEFERRED (Phase 3) |
| P3 | Docker-compose test stack for CI | DEFERRED |

---

## 10. Sources

- pytest-asyncio: session-scoped async fixtures with `loop_scope`
- tenacity: retry with `reraise=True` for hard-fail health polling
- testcontainers-python: programmatic Docker container lifecycle
- FastAPI TestClient: Starlette ASGI test transport (in-process only)
- Our implementation: `src/vaultspec_a2a/tests/conftest.py` (428 lines)
- Our crash recovery tests: `src/vaultspec_a2a/tests/test_crash_recovery.py`
- pytest documentation: fixture scoping, `tmp_path_factory`
