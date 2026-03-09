# Multi-Service Integration Testing Research — 2026-03-08

## Context

VaultSpec A2A runs a 3-process chain: MCP Server -> Gateway (FastAPI :8000) ->
Worker (FastAPI :8001). Integration tests must exercise the real process
boundaries, HTTP IPC, SQLite WAL sharing, and subprocess lifecycle. The team
mandate prohibits mocks, fakes, stubs, and monkeypatching.

This document evaluates frameworks and patterns for live multi-service
integration testing.

---

## 1. Framework Evaluation

### 1.1 pytest-subprocess

**What it does**: Intercepts `subprocess.Popen` / `asyncio.create_subprocess_exec`
calls and returns fake processes.

**Verdict: REJECTED.** This is a mocking library for subprocess calls. It
replaces real subprocesses with fakes, violating the live-test mandate. The
entire point of our integration tests is to verify real subprocess lifecycle.

### 1.2 testcontainers-python

**What it does**: Spins up Docker containers as test fixtures. Each container
runs a real service image.

**Pros**:
- Real process isolation
- Reproducible environments
- Network namespace separation

**Cons**:
- Requires Docker daemon running (not always available in CI on Windows)
- Significant startup overhead per container (2-5s each)
- Our services are not Dockerized for local dev (only for prod)
- Adds complexity that subprocess spawning already solves

**Verdict: DEFERRED.** Useful for Docker-specific integration tests (e.g.,
testing the prod Dockerfile), but not suitable as the primary test harness
for local development testing.

### 1.3 Real Subprocess Spawning (asyncio + httpx)

**What it does**: Tests spawn gateway and worker as real `asyncio.subprocess`
processes, wait for health endpoints, then exercise HTTP APIs with `httpx`.

**Pros**:
- Zero external dependencies beyond what the project already uses
- Tests exercise the exact same code paths as production
- No Docker daemon requirement
- Process lifecycle (spawn, health, crash, cleanup) is directly testable
- Works on Windows (our primary platform)

**Cons**:
- Slower than in-process tests (2-5s startup per service)
- Port conflicts if multiple test sessions run concurrently
- Must handle process cleanup carefully to avoid orphans

**Verdict: RECOMMENDED.** This is the primary approach. All integration tests
should use this pattern.

### 1.4 OTel InMemorySpanExporter

**What it does**: Captures spans in-memory for assertion without requiring
a running collector.

**Verdict: RECOMMENDED as companion.** Use alongside subprocess spawning to
verify trace propagation. Set `OTEL_SDK_DISABLED=false` and
`OTEL_EXPORTER_CONSOLE=true` or use InMemorySpanExporter in the test process.

---

## 2. Recommended Test Harness Pattern

### 2.1 Fixture: Gateway + Worker Subprocess

```python
import asyncio
import httpx
import pytest_asyncio

@pytest_asyncio.fixture
async def services():
    """Start gateway and worker as real subprocesses."""
    gateway_port = _find_free_port()
    worker_port = _find_free_port()

    gateway_proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn",
        "vaultspec_a2a.api.app:create_app",
        "--factory",
        "--host", "127.0.0.1",
        "--port", str(gateway_port),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={
            **os.environ,
            "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
            "VAULTSPEC_WORKER_URL": f"http://127.0.0.1:{worker_port}",
        },
    )

    worker_proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn",
        "vaultspec_a2a.worker.app:create_worker_app",
        "--factory",
        "--host", "127.0.0.1",
        "--port", str(worker_port),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Wait for both services to be healthy
    await _wait_for_health(f"http://127.0.0.1:{gateway_port}/internal/health")
    await _wait_for_health(f"http://127.0.0.1:{worker_port}/health")

    yield {
        "gateway_url": f"http://127.0.0.1:{gateway_port}",
        "worker_url": f"http://127.0.0.1:{worker_port}",
        "gateway_proc": gateway_proc,
        "worker_proc": worker_proc,
    }

    # Cleanup: kill process trees
    for proc in [gateway_proc, worker_proc]:
        if proc.returncode is None:
            if sys.platform == "win32":
                await asyncio.create_subprocess_exec(
                    "taskkill", "/T", "/F", "/PID", str(proc.pid)
                )
            else:
                proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=10.0)
```

### 2.2 Health Probe Helper

```python
async def _wait_for_health(url: str, timeout: float = 15.0) -> None:
    """Poll a health endpoint until it returns 200 or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    async with httpx.AsyncClient() as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(url, timeout=2.0)
                if resp.status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.25)
    raise TimeoutError(f"Service at {url} did not become healthy in {timeout}s")
```

### 2.3 Port Allocation

```python
import socket

def _find_free_port() -> int:
    """Find a free TCP port by binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
```

---

## 3. Crash Simulation Patterns

### 3.1 Worker Crash Recovery

```python
async def test_worker_crash_recovery(services):
    """Kill the worker and verify the gateway circuit breaker opens."""
    gateway_url = services["gateway_url"]
    worker_proc = services["worker_proc"]

    # Kill worker
    worker_proc.kill()
    await worker_proc.wait()

    # Verify circuit breaker opens after failed dispatches
    async with httpx.AsyncClient() as client:
        for _ in range(3):  # Circuit breaker threshold
            resp = await client.post(
                f"{gateway_url}/api/threads",
                json={"preset": "default"},
            )
        # After 3 failures, circuit should be open
        resp = await client.get(f"{gateway_url}/internal/health")
        health = resp.json()
        assert health["circuit_breaker"]["status"] == "open"
```

### 3.2 Gateway Crash (MCP Perspective)

```python
async def test_mcp_gateway_unreachable():
    """MCP tools return actionable errors when gateway is down."""
    # Start MCP server without gateway
    # Invoke a write tool (start_thread)
    # Verify ToolError contains "Gateway is not running"
```

### 3.3 Graceful Shutdown

```python
async def test_graceful_shutdown(services):
    """Verify shutdown sequence: worker flushes events, gateway closes cleanly."""
    gateway_proc = services["gateway_proc"]
    gateway_proc.terminate()
    returncode = await asyncio.wait_for(gateway_proc.wait(), timeout=15.0)
    assert returncode == 0  # Clean exit
```

---

## 4. Circuit Breaker Test Patterns

The `WorkerCircuitBreaker` (`api/app.py:78`) has three states:

| State | Behavior | Transition |
|-------|----------|------------|
| CLOSED | All dispatches pass through | 3 consecutive failures -> OPEN |
| OPEN | All dispatches rejected (503) | 30s timeout -> HALF_OPEN |
| HALF_OPEN | Next dispatch is a probe | Success -> CLOSED, Failure -> OPEN |

### Live Test Strategy

1. Start gateway + worker normally (CLOSED state)
2. Kill worker process
3. Send 3 dispatch requests (expect failures, circuit opens)
4. Verify next dispatch returns 503 (OPEN state)
5. Wait 30s (or adjust config for test)
6. Restart worker
7. Send 1 dispatch (HALF_OPEN -> CLOSED on success)
8. Verify dispatches flow normally

**Timing consideration**: The 30s recovery window makes this test slow.
Consider exposing a test-only configuration for shorter recovery windows,
or accept the 30s wait as the cost of live testing.

---

## 5. IPC and Heartbeat Test Patterns

### 5.1 Event Batch Relay

The `WorkerBridge` (`worker/ipc.py:36`) batches events every 50ms and sends
them via HTTP POST to `/internal/events/batch`.

**Test**: Start both services, create a thread, send a message, and verify
that events arrive at the gateway's aggregator within the batch window.

### 5.2 Heartbeat Staleness

The gateway tracks `worker_last_heartbeat_ts` (`api/app.py:697`). The worker
sends heartbeats every 10s (`worker/app.py:85`).

**Test**: Start both services, wait for 2 heartbeats (20s), verify
`/internal/health` reports the worker as alive. Kill the worker, wait 90s
(staleness threshold), verify health reports worker as stale.

### 5.3 Event Retry

The `WorkerBridge` retries failed event flushes 3 times with exponential
backoff (`worker/ipc.py:30-33`).

**Test**: Start both services, temporarily block the gateway's
`/internal/events/batch` endpoint (e.g., by killing and restarting gateway),
verify events are re-queued and eventually delivered.

---

## 6. W3C Traceparent Propagation in Tests

### 6.1 Current Implementation

- **Gateway HTTP middleware** (`telemetry/middleware.py:77`): Extracts
  `traceparent` from incoming HTTP headers, creates a span, propagates context.
- **WebSocket frames** (`api/websocket.py:476`): `inject_trace_context()`
  adds `_trace.traceparent` to outgoing WS JSON frames.
- **Worker IPC**: Events include `ts` (monotonic timestamp) but **no
  traceparent**. This is a gap (see Telemetry Tracing Gaps research).

### 6.2 Test Pattern: End-to-End Trace Verification

```python
async def test_trace_propagation(services):
    """Verify W3C traceparent flows through the full request chain."""
    gateway_url = services["gateway_url"]

    # Send request with a known traceparent
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{gateway_url}/api/threads",
            json={"preset": "default"},
            headers={"traceparent": traceparent},
        )
        assert resp.status_code == 200
        # The trace ID should propagate to the gateway span
        # and onward to the worker dispatch
```

For full verification, use `InMemorySpanExporter` in the test process or
check `OTEL_EXPORTER_CONSOLE=true` output in subprocess stderr.

---

## 7. Test Organization

Following the project's rust-style convention (tests in source module
subdirectories), integration tests should live in:

```
tests/                          # Top-level: cross-module integration
  test_e2e_smoke.py             # VERIFY-01: full chain smoke test
  test_crash_recovery.py        # Worker crash + circuit breaker
  test_ipc_heartbeat.py         # IPC batch relay + heartbeat staleness
  test_mcp_e2e.py               # MCP stdio -> gateway -> worker
  conftest.py                   # Shared fixtures (subprocess spawning)
```

These are the **only** tests that belong in the top-level `tests/` directory.
Unit and module-level tests remain in their respective `tests/` subdirectories.

---

## 8. Recommendations

| Priority | Recommendation | Rationale |
|----------|---------------|-----------|
| P0 | Use real subprocess spawning for all integration tests | Exercises production code paths exactly |
| P0 | Dynamic port allocation via `_find_free_port()` | Prevents port conflicts in parallel CI |
| P0 | `taskkill /T /F /PID` cleanup on Windows | Prevents orphaned processes |
| P1 | Health probe with exponential backoff in fixtures | Reliable startup detection |
| P1 | OTel InMemorySpanExporter for trace assertions | Verifies W3C propagation without collector |
| P2 | Configurable circuit breaker thresholds for tests | Reduces test duration for state transition tests |
| P2 | Test-specific SQLite DB path per test session | Prevents WAL contention between parallel tests |
