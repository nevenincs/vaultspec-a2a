# Multi-Service Integration Testing Research — 2026-03-08

## Context

VaultSpec A2A runs a 3-process chain: MCP Server -> Gateway (FastAPI :8000) ->
Worker (FastAPI :8001). Integration tests must exercise the real process
boundaries, HTTP IPC, SQLite WAL sharing, and subprocess lifecycle. The project
mandate prohibits mocks, fakes, stubs, and monkeypatching.

This document consolidates the framework evaluation from Task #21 and the
library validation from the integration testing stack research.

**Related documents:**

- `2026-03-08-integration-testing-stack.md` — Detailed library-by-library API validation
- `2026-03-08-multi-service-integration-testing.md` — Test harness patterns and crash simulation
- `2026-03-08-cross-process-tracing.md` — W3C traceparent propagation testing

---

## 1. Frameworks Evaluated

### 1.1 testcontainers-python (v4.14+)

**What it does:** Spins up Docker containers as pytest fixtures. Each container
runs a real service image with lifecycle managed by the test framework.

**Key APIs:**

```python
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

container = DockerContainer("jaegertracing/jaeger:latest")
container.with_exposed_ports(4317, 16686)
container.with_env("COLLECTOR_OTLP_ENABLED", "true")
container.start()  # Raises if Docker unavailable = hard-fail (mandate compliant)
wait_for_logs(container, "Starting HTTP server", timeout=30)
otlp_port = container.get_exposed_port(4317)
```text

**Pros:**

- Real process isolation via Docker namespaces
- Reproducible environments (pinned image tags)
- Port mapping handled automatically (`get_exposed_port()`)
- `start()` raises on Docker daemon unavailable = hard-fail compliant
- Built-in log waiting (`wait_for_logs`)

**Cons:**

- Requires Docker Desktop running (not always available in Windows CI)
- 2-5s startup overhead per container
- Our gateway/worker are not Dockerized for local dev
- Adds `testcontainers>=4.14.0` dev dependency

**Windows compatibility:** Requires Docker Desktop for Windows. Works with
both Hyper-V and WSL2 backends. `get_container_host_ip()` returns `localhost`
on Docker Desktop (no bridge network like Linux).

**Verdict: DEFERRED.** Best for Docker-specific tests (prod Dockerfile
validation, Jaeger/otelcol trace verification). Not suitable as primary harness
for local dev testing where Docker may not be available.

### 1.2 pytest-docker (v3.1+)

**What it does:** Manages docker-compose services as pytest fixtures. Starts
services defined in a `docker-compose.yml` before tests, stops after.

**Key pattern:**

```python
@pytest.fixture(scope="session")
def docker_services(docker_ip, docker_services):
    port = docker_services.port_for("gateway", 8000)
    docker_services.wait_until_responsive(
        timeout=30.0, pause=0.5,
        check=lambda: _is_healthy(f"http://{docker_ip}:{port}/health")
    )
    return {"gateway_url": f"http://{docker_ip}:{port}"}
```text

**Pros:**

- Uses existing docker-compose files (no custom container config)
- `wait_until_responsive()` with custom health check
- Session-scoped by default (services shared across tests)

**Cons:**

- Requires docker-compose installed and Docker daemon running
- Slower than subprocess spawning (Docker overhead)
- Less control over individual service lifecycle than testcontainers
- No crash simulation support (can't kill individual containers mid-test)

**Windows compatibility:** Same as testcontainers — requires Docker Desktop.

**Verdict: NOT RECOMMENDED.** testcontainers provides better granularity for
individual container lifecycle. pytest-docker is better for pre-existing
docker-compose setups, which we don't use for testing.

### 1.3 Toxiproxy (v2.9+)

**What it does:** TCP proxy that simulates network conditions (latency, packet
loss, connection reset, bandwidth throttling). Sits between test client and
service.

**Key pattern:**

```python
from toxiproxy import Toxiproxy

toxiproxy = Toxiproxy()
proxy = toxiproxy.create(
    name="gateway",
    listen="127.0.0.1:18000",
    upstream="127.0.0.1:8000",
)
# Simulate network partition
proxy.add_toxic(type="timeout", attributes={"timeout": 0})
# Test circuit breaker behavior
```text

**Pros:**

- Fine-grained network fault injection (latency, jitter, reset, timeout)
- No code changes to services (transparent proxy)
- Useful for testing circuit breaker, retry, and timeout behavior

**Cons:**

- Requires Toxiproxy daemon running (Go binary, ~10MB)
- Additional dependency and infrastructure
- Only simulates network faults, not process crashes
- Windows support exists but less tested

**Windows compatibility:** Official Windows binaries available. Runs as a
standalone process. No Docker required.

**Verdict: DEFERRED to Phase 3.** Valuable for network fault injection tests
(circuit breaker, IPC retry), but not needed for initial harness. Process
crashes are more important to test first.

### 1.4 asyncio subprocess (stdlib) — RECOMMENDED

**What it does:** Spawns gateway and worker as real `asyncio.subprocess`
processes, identical to production. Health-checks via HTTP, cleanup via
platform-specific process tree kill.

**Key APIs:**

```python
process = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "uvicorn",
    "vaultspec_a2a.api.app:create_app",
    "--factory", "--host", "127.0.0.1", "--port", str(port),
    env=env,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
```text

**Pros:**

- Zero external dependencies beyond stdlib
- Tests exercise exact production code paths
- No Docker daemon requirement
- Process lifecycle (spawn, health, crash, cleanup) directly testable
- Works on Windows 11 (our primary platform)
- `process.returncode` for crash detection
- `PIPE` for stderr capture on crash

**Cons:**

- Slower than in-process tests (2-5s startup per service)
- Port conflicts if multiple test sessions run concurrently
- Must handle process cleanup carefully (orphan prevention)

**Windows compatibility:** Full support via ProactorEventLoop (default since
Python 3.8). `CREATE_NEW_PROCESS_GROUP` for process tree management.
`taskkill /T /F /PID` for tree kill.

**Verdict: RECOMMENDED as primary harness.** All TESTING-01 through TESTING-04
use this pattern.

### 1.5 OTel InMemorySpanExporter (opentelemetry-sdk)

**What it does:** Captures spans in-memory for assertion. Real OTel exporter
(not a mock) wired via `SimpleSpanProcessor`.

**Key APIs:**

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))

# After test:
spans = exporter.get_finished_spans()
assert any(s.name == "POST /api/threads" for s in spans)
```text

**Pros:**

- Real exporter (mandate compliant — not a mock)
- Thread-safe span list
- Synchronous export via SimpleSpanProcessor (no batching delay)
- Can run alongside production exporters (additive)
- OTel SDK silently drops export failures (tests never fail from missing OTLP endpoint)

**Cons:**

- Only captures spans from the test process, not from subprocess gateway/worker
- For cross-process trace verification, need Jaeger + testcontainers

**Windows compatibility:** Full support. No platform-specific behavior.

**Verdict: RECOMMENDED as companion.** Use for in-process span assertions.
Pair with Jaeger (testcontainers) for cross-process trace verification.

### 1.6 Hypothesis (property-based testing)

**What it does:** Generates random test inputs and finds edge cases via
shrinking. Useful for testing input validation, state machines, and protocol
compliance.

**Key pattern:**

```python
from hypothesis import given, strategies as st

@given(st.text(min_size=1, max_size=1000))
async def test_message_content_roundtrip(content):
    """Any valid string round-trips through the message pipeline."""
    resp = await client.post("/api/threads/.../messages", json={"content": content})
    assert resp.status_code == 200
```text

**Pros:**

- Finds edge cases humans miss (unicode, empty strings, very long inputs)
- Shrinking gives minimal reproducing examples
- Stateful testing for state machine verification

**Cons:**

- Slow (generates many test cases)
- Not suitable for integration tests with real services (too many requests)
- Better for unit tests on pure functions

**Windows compatibility:** Full support. No platform-specific behavior.

**Verdict: DEFERRED.** Useful for unit-level input validation, not for
integration tests. Consider for CRUD/state machine property tests later.

### 1.7 pytest-anyio

**What it does:** Alternative to pytest-asyncio that supports both asyncio
and trio backends. Provides `@pytest.mark.anyio` for async tests.

**Verdict: NOT RECOMMENDED.** We use pytest-asyncio with strict mode and
session-scoped event loops. Switching would require migrating all existing
async fixtures and tests. No benefit for our asyncio-only codebase.

---

## 2. Ranked Recommendation

| Rank | Framework | Use Case | Phase | Status |
|------|-----------|----------|-------|--------|
| 1 | asyncio subprocess (stdlib) | Primary harness for all integration tests | Phase 1 (TESTING-01) | IMPLEMENTED |
| 2 | tenacity (`reraise=True`) | Health polling with hard-fail semantics | Phase 1 (TESTING-01) | IMPLEMENTED |
| 3 | httpx.AsyncClient | Test HTTP transport (same as production) | Phase 1 (TESTING-01) | IMPLEMENTED |
| 4 | InMemorySpanExporter | In-process span assertions | Phase 1 (TESTING-01) | IMPLEMENTED |
| 5 | pytest-timeout | Hard deadline enforcement (300s global) | Phase 1 | CONFIGURED |
| 6 | testcontainers-python | Docker-based Jaeger/otelcol for trace tests | Phase 2 | DEFERRED |
| 7 | psutil | Cross-platform process tree kill | Phase 2 | DEFERRED |
| 8 | Toxiproxy | Network fault injection | Phase 3 | DEFERRED |
| 9 | Hypothesis | Property-based input validation | Phase 3 | DEFERRED |
| 10 | pytest-docker | Docker-compose-based testing | — | REJECTED |
| 11 | pytest-anyio | Alternative async test runner | — | REJECTED |
| 12 | pytest-subprocess | Subprocess mocking | — | REJECTED (violates mandate) |

---

## 3. Decision: TESTING-01 through TESTING-04 Framework Choices

### TESTING-01: Integration Test Harness

- **asyncio subprocess** for gateway + worker lifecycle
- **tenacity** with `reraise=True` for health polling
- **httpx.AsyncClient** for test transport
- **Dynamic port allocation** via `socket.bind(("127.0.0.1", 0))`
- **Session-scoped fixtures** with `loop_scope="session"`

### TESTING-02: Crash Recovery

- **asyncio subprocess** per-test (not session-scoped — crash mutates state)
- **`process.kill()`** for crash simulation
- **`taskkill /T /F /PID`** on Windows for tree kill
- **tenacity** for restart detection polling

### TESTING-03: IPC and Heartbeat

- **Session-scoped stack** from TESTING-01 fixtures
- **WebSocket client** (httpx or websockets) for event stream
- **Event ordering assertions** (monotonic timestamps from IPC-01)
- **Heartbeat staleness** via worker kill + health poll

### TESTING-04: MCP End-to-End

- **Direct function calls** to `@mcp.tool()` decorated functions
- **Session-scoped stack** for write tools (start_thread)
- **No-stack tests** for degraded mode error messages
- **Circuit breaker 503 translation** via successive failed dispatches

---

## 4. Windows Compatibility Summary

| Component | Windows Support | Notes |
|-----------|----------------|-------|
| asyncio subprocess | Full | ProactorEventLoop default, `CREATE_NEW_PROCESS_GROUP` |
| Process tree kill | `taskkill /T /F /PID` | No `os.killpg()` on Windows |
| Dynamic ports | Full | `socket.bind(("127.0.0.1", 0))` works identically |
| tenacity | Full | Uses `asyncio.sleep()` internally |
| httpx | Full | No platform-specific behavior |
| InMemorySpanExporter | Full | No platform-specific behavior |
| testcontainers | Docker Desktop required | Works with Hyper-V or WSL2 backend |
| pytest-timeout | `thread` method | No SIGALRM on Windows; uses `threading.Timer` |

---

## 5. Sources

- asyncio subprocess: Python 3.13 stdlib (`asyncio.create_subprocess_exec`)
- testcontainers-python: PyPI `testcontainers>=4.14.0`
- pytest-docker: PyPI `pytest-docker>=3.1.0`
- Toxiproxy: GitHub `Shopify/toxiproxy` v2.9+
- OTel SDK: `opentelemetry-sdk>=1.39.1` (installed)
- tenacity: `tenacity>=9.0.0` (installed)
- httpx: `httpx>=0.28.1` (installed)
- Hypothesis: PyPI `hypothesis>=6.0`
- pytest-anyio: PyPI `anyio[trio]`
- Validated against installed source in `.venv/Lib/site-packages/`
