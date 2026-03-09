# Integration Testing Stack Validation — 2026-03-08

## Context

VaultSpec A2A needs a multi-service integration test harness that spawns real
gateway + worker subprocesses, probes health, asserts distributed traces, and
enforces hard timeouts. This document validates each candidate library against
the installed environment (Python 3.13, Windows 11, pytest-asyncio strict mode).

Validated against installed source in `.venv/Lib/site-packages/` (context7
quota exceeded; library source is more authoritative anyway).

---

## 0. HARD-FAIL MANDATE

**Team-lead directive (2026-03-08): tests must HARD FAIL, never skip.**

Fixtures OWN the full service lifecycle:
- They START required services (subprocess or Docker container) in setup
- They STOP and CLEAN UP services in teardown
- If a service fails to start or become healthy, the fixture raises, the test
  FAILS. That failure is the correct signal.

**FORBIDDEN in test code:**
- `pytest.skip()` based on service availability
- `shutil.which()` checks that skip tests
- `@pytest.mark.requires_*` that gate on availability
- `MemorySaver`, `MockTransport`, `dependency_overrides` replacing real services
- Any "graceful degradation" or "self-healing skip" in test fixtures

**REQUIRED:**
- Always exercise real services
- Always hard-fail when real services are unavailable
- Own the full lifecycle (start -> test -> stop) in session-scoped fixtures
- `testcontainers` handles Docker lifecycle automatically
- `tenacity` with `reraise=True` for health polling -- `RetryError` propagates
  as hard failure if health never comes up

---

## 1. psutil — Process Tree Inspection

### Installation Status: NOT INSTALLED

psutil is not in `pyproject.toml` dependencies or dev dependencies. Must be
added to `[dependency-groups] dev`.

### Why psutil

The stdlib `asyncio.subprocess.Process` exposes only `pid`, `terminate()`,
`kill()`, and `wait()`. It cannot:
- List child processes (worker spawned by gateway)
- Check which process holds a port
- Inspect process CPU/memory for resource leak tests
- Recursively kill a process tree on POSIX (Windows has `taskkill /T`)

### API Validation (from psutil docs + PyPI metadata)

```python
import psutil

# Process tree inspection
proc = psutil.Process(pid)
children = proc.children(recursive=True)  # All descendants
for child in children:
    child.kill()
proc.kill()

# Port binding check
for conn in psutil.net_connections(kind="inet"):
    if conn.laddr.port == 8000 and conn.status == "LISTEN":
        proc = psutil.Process(conn.pid)
        # Found the process holding port 8000

# Alternative: per-process connections
proc = psutil.Process(pid)
connections = proc.net_connections()
```

### Python 3.13 + Windows Compatibility

- psutil supports Python 3.8-3.13 (confirmed in PyPI classifiers)
- Full Windows support including `Process.children()`, `net_connections()`
- `Process.kill()` on Windows calls `TerminateProcess` (same as stdlib)
- `Process.children(recursive=True)` uses `ppid` tracking — works on Windows

### Our Use Case: Test Fixture Cleanup

```python
import psutil

async def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its descendants."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for child in children:
        with contextlib.suppress(psutil.NoSuchProcess):
            child.kill()
    with contextlib.suppress(psutil.NoSuchProcess):
        parent.kill()
    # Wait for all to exit
    psutil.wait_procs(children + [parent], timeout=5)
```

### Port-Available Guard

```python
def _port_is_free(port: int) -> bool:
    """Check that no process is listening on the given port."""
    for conn in psutil.net_connections(kind="inet"):
        if conn.laddr.port == port and conn.status == "LISTEN":
            return False
    return True
```

### Conflicts with Existing Stack

None. psutil is a C extension with no Python dependency conflicts.

### Recommendation

**ADD** `psutil>=6.0.0` to `[dependency-groups] dev` in `pyproject.toml`.

---

## 2. opentelemetry-sdk InMemorySpanExporter — Trace Assertions

### Installation Status: INSTALLED

Source: `.venv/Lib/site-packages/opentelemetry/sdk/trace/export/in_memory_span_exporter.py`

### API (from installed source)

```python
class InMemorySpanExporter(SpanExporter):
    def __init__(self) -> None:
        self._finished_spans: list[ReadableSpan] = []
        self._stopped = False
        self._lock = threading.Lock()

    def clear(self) -> None:
        """Clear list of collected spans."""

    def get_finished_spans(self) -> tuple[ReadableSpan, ...]:
        """Get list of collected spans."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Stores a list of spans in memory."""

    def shutdown(self) -> None:
        """Shut downs the exporter."""

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
```

### Key Properties

- **Thread-safe**: All methods guarded by `threading.Lock`
- **NOT a mock**: This is a real `SpanExporter` implementation that receives
  real spans from a real `TracerProvider`. It just stores them in memory
  instead of sending to a collector. **Compliant with no-mock mandate.**
- **Resettable**: `clear()` method for between-test cleanup
- **Immutable snapshot**: `get_finished_spans()` returns a tuple (not a list)

### Wiring Alongside Real Exporters

`TracerProvider.add_span_processor()` is additive (confirmed in installed
source at `sdk/trace/__init__.py:1435`). Multiple processors run in
registration order:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

provider = TracerProvider()

# Production exporter (if configured)
# provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(...)))

# Test exporter — runs alongside, not instead of
exporter = InMemorySpanExporter()
provider.add_span_processor(SimpleSpanProcessor(exporter))
# SimpleSpanProcessor exports synchronously — spans are immediately available
# after span.end(). BatchSpanProcessor would delay export.
```

### Asserting Trace Parent Relationships

```python
spans = exporter.get_finished_spans()

gateway_span = next(s for s in spans if s.name == "POST /dispatch")
worker_span = next(s for s in spans if s.name == "worker.handle_dispatch")

# Parent-child: worker span's parent is the gateway span
assert worker_span.parent is not None
assert worker_span.parent.trace_id == gateway_span.context.trace_id
assert worker_span.parent.span_id == gateway_span.context.span_id

# Same trace: all spans share the same trace_id
trace_id = gateway_span.context.trace_id
assert all(s.context.trace_id == trace_id for s in spans)
```

### Resetting Between Tests

```python
@pytest.fixture(autouse=True)
def _reset_spans(otel_exporter):
    yield
    otel_exporter.clear()
```

### Cross-Process Limitation

**InMemorySpanExporter only captures spans from the process it's registered in.**
For our multi-process tests (gateway + worker are separate processes), each
process needs its own TracerProvider + InMemorySpanExporter. Options:

1. **In-process only**: Use InMemorySpanExporter in the test process (gateway
   via ASGI TestClient). Worker spans are not captured.
2. **OTLP to test collector**: Both processes export to a test OTLP collector
   (e.g., in-memory gRPC server or Jaeger). Test reads spans from collector.
3. **File exporter**: Both processes write spans to a shared JSON file. Test
   reads the file after execution.

**Recommendation**: For single-process gateway tests (ASGI TestClient),
InMemorySpanExporter is ideal. For true cross-process trace assertions,
use the Jaeger container from `docker-compose.dev.yml` and query its API.

### Conflicts with Existing Stack

None. Already installed as part of `opentelemetry-sdk>=1.39.1`.

### Recommendation

**USE** `SimpleSpanProcessor(InMemorySpanExporter())` for gateway integration
tests. For cross-process trace assertions, defer to Jaeger query API in
docker-based tests.

---

## 3. tenacity — Async Retry for Health Probing

### Installation Status: INSTALLED

Source: `.venv/Lib/site-packages/tenacity/__init__.py` + `tenacity/asyncio/__init__.py`

### Async Support (from installed source)

The `@retry` decorator **automatically detects async functions** and uses
`AsyncRetrying` instead of `Retrying`:

```python
# tenacity/__init__.py:670-673
if _utils.is_coroutine_callable(f) or (
    sleep is not None and _utils.is_coroutine_callable(sleep)
):
    r = AsyncRetrying(*dargs, **dkw)
```

`AsyncRetrying` (in `tenacity/asyncio/__init__.py:67`) uses `asyncio.sleep()`
by default (via `_portable_async_sleep` which also supports trio).

### Usage Pattern for Health Probing

```python
from tenacity import retry, stop_after_delay, wait_exponential, retry_if_exception_type
import httpx

@retry(
    stop=stop_after_delay(30),        # Give up after 30 seconds total
    wait=wait_exponential(
        multiplier=0.1,               # Start at 100ms
        max=2,                        # Cap at 2s between retries
    ),
    retry=retry_if_exception_type((
        httpx.ConnectError,
        httpx.ConnectTimeout,
    )),
    reraise=True,                     # Re-raise the last exception on give-up
)
async def _wait_for_healthy(base_url: str) -> None:
    """Wait for service to become healthy."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base_url}/health", timeout=2.0)
        resp.raise_for_status()
```

### Alternative: Inline Context Manager

```python
from tenacity import AsyncRetrying, stop_after_delay, wait_exponential

async for attempt in AsyncRetrying(
    stop=stop_after_delay(30),
    wait=wait_exponential(multiplier=0.1, max=2),
):
    with attempt:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/health", timeout=2.0)
            resp.raise_for_status()
```

### Fixture Pattern

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_url():
    """Spawn gateway, wait for health, yield URL, kill on teardown."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn",
        "vaultspec_a2a.api.app:create_app", "--factory",
        "--host", "127.0.0.1", "--port", str(port),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        await _wait_for_healthy(url)  # tenacity retry
        yield url
    finally:
        proc.terminate()
        await proc.wait()
```

### Python 3.13 + Windows Compatibility

- Pure Python, no C extensions, no platform-specific code
- Uses `asyncio.sleep()` on non-trio environments
- `is_coroutine_callable()` detection works with `async def` functions

### Conflicts with Existing Stack

None. tenacity is already installed (transitive dependency). No conflict with
pytest-asyncio or anyio.

### Recommendation

**USE** `@retry` decorator with `stop_after_delay` + `wait_exponential` for
all health probe fixtures. Already installed, no new dependency needed.

---

## 4. pytest-timeout — Per-Test Hard Timeouts

### Installation Status: INSTALLED

Source: `.venv/Lib/site-packages/pytest_timeout.py`
Already in dev deps: `pytest-timeout>=2.4.0`

### Current Configuration (pyproject.toml)

```toml
timeout = "300"  # 5 minutes global default
```

### Windows Behavior

From installed source (`pytest_timeout.py:26-29`):

```python
HAVE_SIGALRM = hasattr(signal, "SIGALRM")
if HAVE_SIGALRM:
    DEFAULT_METHOD = "signal"
else:
    DEFAULT_METHOD = "thread"
```

Windows does NOT have `SIGALRM`, so it defaults to `"thread"` method. The
thread method uses a `threading.Timer` that calls `os._exit(1)` on timeout.

### Per-Test Timeout

```python
@pytest.mark.timeout(60)
async def test_full_dispatch_cycle(gateway_url):
    """Integration test with 60s timeout (overrides global 300s)."""
    ...

@pytest.mark.timeout(120)
async def test_crash_recovery(gateway_url):
    """Crash recovery may need more time."""
    ...
```

### pyproject.toml Configuration

Already configured:

```toml
[tool.pytest.ini_options]
timeout = "300"              # Global default: 5 minutes
# timeout_method not set — defaults to "thread" on Windows, "signal" on POSIX
```

### Integration Test Override

For the integration test suite, consider a dedicated marker:

```toml
[tool.pytest.ini_options]
markers = [
    "live: marks tests requiring live ACP backend processes",
    "integration: marks multi-service integration tests",
]
```

### Conflicts with Existing Stack

None. Already configured and working.

### Recommendation

**ALREADY CONFIGURED**. Use `@pytest.mark.timeout(N)` for per-test overrides.
Consider increasing global timeout for integration tests via CLI:
`pytest --timeout=600 -m integration`.

---

## 5. httpx Event Hooks — Request/Response Interception

### Installation Status: INSTALLED (part of httpx)

Source: `.venv/Lib/site-packages/httpx/_client.py`

### API (from installed source)

The `AsyncClient` constructor accepts `event_hooks`:

```python
httpx.AsyncClient(
    event_hooks={
        "request": [list of callables],
        "response": [list of callables],
    }
)
```

In the async client, hooks are **awaited** (`_client.py:1691-1697`):

```python
for hook in self._event_hooks["request"]:
    await hook(request)
# ...
for hook in self._event_hooks["response"]:
    await hook(response)
```

Hooks receive the actual `httpx.Request` or `httpx.Response` object. They
run on **real outgoing requests** — no transport replacement needed.

### Our Use Case: Capture Trace Headers

```python
captured_headers: list[dict[str, str]] = []

async def capture_traceparent(request: httpx.Request) -> None:
    """Capture outgoing traceparent headers for assertion."""
    if "traceparent" in request.headers:
        captured_headers.append(dict(request.headers))

client = httpx.AsyncClient(
    event_hooks={"request": [capture_traceparent]},
    base_url="http://localhost:8001",
    timeout=httpx.Timeout(10.0, connect=5.0),
)
```

### Assertion Pattern

```python
# After dispatching work to the worker:
assert len(captured_headers) > 0
traceparent = captured_headers[0].get("traceparent", "")
assert traceparent.startswith("00-")  # W3C version
parts = traceparent.split("-")
assert len(parts) == 4
assert len(parts[1]) == 32  # trace_id
assert len(parts[2]) == 16  # span_id
```

### Advantage Over MockTransport

Event hooks intercept **real requests** to **real services**. No transport
replacement. The request actually goes out over the network. This is fully
compliant with the no-mock mandate.

### Conflicts with Existing Stack

None. Event hooks are a native httpx feature, no additional dependency.

### Recommendation

**USE** event hooks on the gateway's `worker_client` (in test fixtures) to
capture and assert traceparent propagation. Replace the existing
`MockTransport` in conftest with real httpx clients using event hooks for
header inspection.

---

## 6. structlog — Testing Utilities

### Installation Status: NOT INSTALLED

structlog is not in `pyproject.toml` dependencies or dev dependencies.

### Assessment

We use stdlib `logging` throughout the codebase (confirmed: `import logging`
in all modules). structlog would be a full logging framework migration, not
a testing utility.

### Alternative: stdlib logging capture

pytest provides built-in `caplog` fixture for capturing log output:

```python
def test_worker_startup(caplog):
    with caplog.at_level(logging.INFO, logger="vaultspec_a2a.worker"):
        # ... start worker ...
        assert "Worker started" in caplog.text
```

For structured assertions on log records:

```python
def test_dispatch_logged(caplog):
    with caplog.at_level(logging.INFO):
        # ... dispatch work ...
        dispatch_records = [
            r for r in caplog.records
            if r.name == "vaultspec_a2a.api.app"
            and "dispatch" in r.message.lower()
        ]
        assert len(dispatch_records) >= 1
        assert hasattr(dispatch_records[0], "dispatch_id")
```

### Recommendation

**SKIP** structlog. Use pytest's built-in `caplog` fixture for log assertions.
No new dependency needed.

---

## 7. pytest-asyncio Session-Scoped Fixtures

### Installation Status: INSTALLED

Source: `.venv/Lib/site-packages/pytest_asyncio/plugin.py`

### Current Configuration

```toml
asyncio_mode = "strict"
asyncio_default_fixture_loop_scope = "function"
```

### The Problem

If every integration test spawns its own gateway + worker subprocess:
- ~5-15s startup per test
- Port conflicts between concurrent spawns
- Wasted CI time

We need a **single** gateway+worker instance shared across the entire test
session.

### Session-Scoped Async Fixtures (from installed source)

pytest-asyncio supports `scope="session"` with `loop_scope="session"`:

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_process():
    """Spawn gateway once for entire test session."""
    ...
```

The `loop_scope` parameter (`plugin.py:162`) controls which event loop the
fixture runs on. When `loop_scope="session"`, the fixture shares the
session-level event loop.

### Critical: asyncio_default_fixture_loop_scope

From `plugin.py:222-228`:

```
The event loop scope for asynchronous fixtures will default to the fixture
caching scope. Future versions of pytest-asyncio will default the loop scope
for asynchronous fixtures to function scope.
Valid fixture loop scopes are: "function", "class", "module", "package", "session"
```

Our current setting `asyncio_default_fixture_loop_scope = "function"` means
session-scoped fixtures **must** explicitly set `loop_scope="session"` or
they will get a function-scoped event loop (mismatched with session scope).

### Recommended Fixture Pattern

```python
import asyncio
import sys
import pytest_asyncio
from tenacity import retry, stop_after_delay, wait_exponential, retry_if_exception_type
import httpx

# ---- Session-scoped subprocess fixtures ----

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _gateway_worker_stack():
    """Spawn gateway + worker as real subprocesses for the entire test session.

    Yields (gateway_url, worker_url) tuple.
    Kills both processes on teardown.
    """
    import socket

    # Dynamic port allocation
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    gw_port = _free_port()
    wk_port = _free_port()

    env = {
        **os.environ,
        "VAULTSPEC_WORKER_URL": f"http://127.0.0.1:{wk_port}",
        "VAULTSPEC_AUTO_SPAWN_WORKER": "false",  # We spawn worker separately
        "OTEL_SDK_DISABLED": "true",  # No OTel noise in tests
    }

    # Spawn worker first (gateway depends on it)
    worker_proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn",
        "vaultspec_a2a.worker.app:create_app", "--factory",
        "--host", "127.0.0.1", "--port", str(wk_port),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    # Spawn gateway
    gateway_proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn",
        "vaultspec_a2a.api.app:create_app", "--factory",
        "--host", "127.0.0.1", "--port", str(gw_port),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    gw_url = f"http://127.0.0.1:{gw_port}"
    wk_url = f"http://127.0.0.1:{wk_port}"

    try:
        # Wait for both to become healthy
        await _wait_for_healthy(wk_url)
        await _wait_for_healthy(gw_url)
        yield gw_url, wk_url
    finally:
        # Kill both (reverse dependency order)
        for proc in [gateway_proc, worker_proc]:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()


@retry(
    stop=stop_after_delay(30),
    wait=wait_exponential(multiplier=0.1, max=2),
    retry=retry_if_exception_type((
        httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError,
    )),
    reraise=True,
)
async def _wait_for_healthy(base_url: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{base_url}/health", timeout=2.0)
        resp.raise_for_status()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_url(_gateway_worker_stack):
    return _gateway_worker_stack[0]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def worker_url(_gateway_worker_stack):
    return _gateway_worker_stack[1]
```

### Event Loop Scope Warning

If tests use `scope="session"` fixtures but the test itself runs on a
function-scoped loop (the default), pytest-asyncio will raise:

```
ScopeMismatch: You tried to access a session scoped fixture from a
function scoped test
```

**Fix**: Tests using session-scoped fixtures must declare their loop scope:

```python
@pytest.mark.asyncio(loop_scope="session")
async def test_dispatch(gateway_url):
    ...
```

Or configure globally for integration tests via a conftest:

```python
# tests/integration/conftest.py
pytest_plugins = []

def pytest_collection_modifyitems(items):
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(pytest.mark.asyncio(loop_scope="session"))
```

### Conflicts with Existing Stack

**Requires care**. The existing test suite uses `asyncio_mode = "strict"` and
`asyncio_default_fixture_loop_scope = "function"`. Integration tests with
session scope must explicitly annotate `loop_scope="session"` everywhere.

### Recommendation

**USE** `scope="session"` + `loop_scope="session"` for subprocess fixtures.
Place integration tests in a dedicated `tests/integration/` directory with
their own conftest that sets the session loop scope. This isolates them from
the existing function-scoped unit tests.

---

## 8. testcontainers — Docker Service Lifecycle

### Installation Status: NOT INSTALLED

Must be added to `[dependency-groups] dev`.

### What It Is

`testcontainers` (v4.14.1, Python >=3.10, Windows supported) auto-manages
Docker container lifecycle in test fixtures: pull image, start container,
wait for readiness, yield to tests, stop + cleanup on teardown.

**If Docker is not available, `start()` raises immediately = hard test failure.**
This is the correct behavior per the hard-fail mandate.

### API (from GitHub source + PyPI)

```python
from testcontainers.core.container import DockerContainer

container = DockerContainer("jaegertracing/jaeger:latest")
container.with_exposed_ports(4317, 16686)
container.with_env("COLLECTOR_OTLP_ENABLED", "true")
container.start()  # Pulls image, starts container, raises on failure

# Get mapped host port (Docker assigns a random host port)
otlp_port = container.get_exposed_port(4317)
jaeger_ui_port = container.get_exposed_port(16686)
host = container.get_container_host_ip()

# When done:
container.stop()
```

Context manager:

```python
with DockerContainer("jaegertracing/jaeger:latest") as jaeger:
    jaeger.with_exposed_ports(4317, 16686)
    # Container is started in __enter__, stopped in __exit__
```

### Jaeger Fixture (Session-Scoped, Hard-Fail)

```python
import pytest_asyncio
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def jaeger():
    """Start Jaeger container for trace collection.

    Hard-fails if Docker is not available — no skip, no degradation.
    """
    container = DockerContainer("jaegertracing/jaeger:latest")
    container.with_exposed_ports(4317, 16686)
    container.with_env("COLLECTOR_OTLP_ENABLED", "true")
    container.start()

    # Wait for Jaeger to be ready (log sentinel)
    wait_for_logs(container, "Starting HTTP server", timeout=30)

    otlp_port = container.get_exposed_port(4317)
    ui_port = container.get_exposed_port(16686)
    host = container.get_container_host_ip()

    try:
        yield {
            "otlp_endpoint": f"http://{host}:{otlp_port}",
            "query_url": f"http://{host}:{ui_port}",
            "container": container,
        }
    finally:
        container.stop()
```

### otelcol Fixture (Session-Scoped, Hard-Fail)

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def otelcol(tmp_path_factory):
    """Start otelcol container for cross-process span collection.

    Hard-fails if Docker is not available.
    """
    traces_dir = tmp_path_factory.mktemp("otel-traces")

    container = DockerContainer("otel/opentelemetry-collector:latest")
    container.with_exposed_ports(4317)
    container.with_volume_mapping(str(traces_dir), "/traces", "rw")
    container.with_env("OTEL_CONFIG", "/etc/otelcol/config.yaml")
    # Use file exporter to write spans to /traces/traces.json
    container.start()

    wait_for_logs(container, "Everything is ready", timeout=30)

    otlp_port = container.get_exposed_port(4317)
    host = container.get_container_host_ip()

    try:
        yield {
            "otlp_endpoint": f"http://{host}:{otlp_port}",
            "traces_dir": traces_dir,
            "container": container,
        }
    finally:
        container.stop()
```

### Configuring Subprocesses to Export to Containerized Collector

When the Jaeger or otelcol fixture provides an OTLP endpoint, pass it to
subprocess env:

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _gateway_worker_stack(jaeger):
    env = {
        **os.environ,
        "OTEL_SDK_DISABLED": "false",
        "OTEL_EXPORTER_OTLP_ENDPOINT": jaeger["otlp_endpoint"],
        "OTEL_EXPORTER_OTLP_INSECURE": "true",
        "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
    }
    # ... spawn gateway + worker with this env ...
```

### Python 3.13 + Windows Compatibility

- Python: >=3.10, explicitly lists Windows in PyPI classifiers
- Requires Docker Desktop running on Windows
- Uses `docker-py` under the hood (TCP socket on Windows, Unix socket on POSIX)
- `get_container_host_ip()` handles Docker Desktop's `host.docker.internal`

### Conflicts with Existing Stack

None. Pure Python, no import conflicts with pytest-asyncio or anyio.

### Recommendation

**ADD** `testcontainers>=4.14.0` to `[dependency-groups] dev`. Use for Jaeger
and otelcol containers. Docker must be running for integration tests -- if
not, tests hard-fail (correct behavior per mandate).

---

## 9. Dependency Summary

### Already Installed (no changes needed)

| Library | Version | Use Case |
|---------|---------|----------|
| `opentelemetry-sdk` | `>=1.39.1` | `InMemorySpanExporter` for trace assertions |
| `tenacity` | (transitive) | `@retry` with `stop_after_delay` + `wait_exponential` + `reraise=True` |
| `pytest-timeout` | `>=2.4.0` | Per-test hard timeouts via `@pytest.mark.timeout(N)` |
| `httpx` | `>=0.28.1` | `event_hooks` for request/response interception |
| `pytest-asyncio` | `>=1.3.0` | `scope="session"` + `loop_scope="session"` for subprocess fixtures |

### Must Add to Dev Dependencies

| Library | Version | Use Case |
|---------|---------|----------|
| `psutil` | `>=6.0.0` | Process tree inspection, port checks, teardown cleanup |
| `testcontainers` | `>=4.14.0` | Docker container lifecycle for Jaeger, otelcol |

### Not Needed

| Library | Reason |
|---------|--------|
| `structlog` | Not installed, stdlib `logging` + pytest `caplog` is sufficient |
| `pytest-subprocess` | REJECTED (previous research) -- wraps subprocess with fakes |

### pyproject.toml Change

```toml
[dependency-groups]
dev = [
  # ... existing ...
  "psutil>=6.0.0",           # Process tree inspection for integration tests
  "testcontainers>=4.14.0",  # Docker container lifecycle (Jaeger, otelcol)
]
```

---

## 10. Recommended Test File Structure

```
src/vaultspec_a2a/
  api/tests/
    integration/
      conftest.py          # Session-scoped fixtures: gateway+worker subprocesses
      test_dispatch.py     # Real dispatch through live gateway
      test_crash.py        # Kill worker, assert recovery
      test_heartbeat.py    # Assert heartbeat events arrive
      test_traces.py       # Assert traceparent propagation (event hooks)
    test_endpoints.py      # Existing unit tests (function scope)
    conftest.py            # Existing conftest (MUST be rebuilt per mandate)
  worker/tests/
    integration/
      test_executor.py     # Real executor against live worker
```

### conftest.py (integration)

Uses the session-scoped fixture pattern from Section 7 above, plus:

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def api_client(gateway_url):
    """Real httpx client pointed at real gateway."""
    async with httpx.AsyncClient(
        base_url=gateway_url,
        timeout=httpx.Timeout(30.0, connect=5.0),
    ) as client:
        yield client
```

---

## 11. Compatibility Matrix

| Library | Python 3.13 | Windows 11 | asyncio | pytest-asyncio strict | anyio |
|---------|-------------|------------|---------|----------------------|-------|
| psutil | YES | YES (full) | N/A (sync) | N/A | N/A |
| testcontainers | YES (>=3.10) | YES (Docker Desktop) | N/A (sync) | Compatible | N/A |
| InMemorySpanExporter | YES | YES | N/A (sync export) | Compatible | N/A |
| tenacity | YES | YES | YES (auto-detect) | Compatible | Compatible (sniffio) |
| pytest-timeout | YES | YES (thread method) | Compatible | Compatible | Compatible |
| httpx event_hooks | YES | YES | YES (await hook) | Compatible | Compatible |
| pytest-asyncio session | YES | YES | YES | Native | N/A |

No conflicts detected. All libraries are compatible with our existing stack.
Docker Desktop is a prerequisite for integration tests (hard-fail if absent).

---

## 12. Quick Reference: Common Patterns

### Health probe with tenacity

```python
@retry(stop=stop_after_delay(30), wait=wait_exponential(multiplier=0.1, max=2),
       retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
       reraise=True)
async def _wait_healthy(url: str) -> None:
    async with httpx.AsyncClient() as c:
        (await c.get(f"{url}/health", timeout=2.0)).raise_for_status()
```

### Trace assertion with InMemorySpanExporter

```python
spans = exporter.get_finished_spans()
dispatch_span = next(s for s in spans if s.name == "POST /dispatch")
assert dispatch_span.status.is_ok
assert dispatch_span.attributes["thread_id"] == thread_id
```

### Process cleanup with psutil

```python
parent = psutil.Process(proc.pid)
for child in parent.children(recursive=True):
    child.kill()
parent.kill()
psutil.wait_procs(parent.children(recursive=True) + [parent], timeout=5)
```

### Per-test timeout

```python
@pytest.mark.timeout(60)
@pytest.mark.asyncio(loop_scope="session")
async def test_full_cycle(gateway_url): ...
```

### Header capture with event hooks

```python
headers_log = []
async def _log(req): headers_log.append(dict(req.headers))
client = httpx.AsyncClient(event_hooks={"request": [_log]}, base_url=url)
```

---

## 13. Trace Verification — Hard-Fail Architecture

### Design Principle

Trace verification uses a **tiered architecture** where each tier is
independently useful. All tiers are REQUIRED -- fixtures own the full
lifecycle and hard-fail if services cannot start.

```
TIER 1: httpx event_hooks        [ALWAYS WORKS — zero deps]
TIER 2: InMemorySpanExporter     [ALWAYS WORKS — zero deps]
TIER 3: testcontainers Jaeger    [HARD-FAIL if Docker unavailable]
```

---

### TIER 1: httpx Event Hooks for Traceparent Header Inspection

**Reliability: ALWAYS WORKS.** Zero external dependencies. Intercepts real
HTTP requests without replacing the transport.

#### API (confirmed from installed source: `httpx/_client.py:1691-1697`)

```python
# AsyncClient calls hooks with await:
for hook in self._event_hooks["request"]:
    await hook(request)
# ... actual HTTP request goes out ...
for hook in self._event_hooks["response"]:
    await hook(response)
```

Hooks receive the actual `httpx.Request` / `httpx.Response` objects. The
request is sent to the real server after hooks run. This is NOT interception
in the mock sense -- it is observation of real traffic.

#### Integration with worker_client fixture

The gateway creates a `worker_client` (`httpx.AsyncClient`) to talk to the
worker. In tests, we can inject event hooks into this client to capture
outgoing headers:

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def traced_worker_client(worker_url):
    """Real httpx client with traceparent capture hook."""
    captured: list[dict[str, str]] = []

    async def _capture_traceparent(request: httpx.Request) -> None:
        if "traceparent" in request.headers:
            captured.append({
                "traceparent": request.headers["traceparent"],
                "url": str(request.url),
                "method": request.method,
            })

    client = httpx.AsyncClient(
        base_url=worker_url,
        timeout=httpx.Timeout(10.0, connect=5.0),
        event_hooks={"request": [_capture_traceparent]},
    )
    client._captured_traces = captured  # Attach for test access
    try:
        yield client
    finally:
        await client.aclose()
```

#### Assertion pattern

```python
@pytest.mark.timeout(60)
@pytest.mark.asyncio(loop_scope="session")
async def test_traceparent_propagated(traced_worker_client):
    # ... trigger a dispatch that uses traced_worker_client ...

    assert len(traced_worker_client._captured_traces) > 0
    tp = traced_worker_client._captured_traces[0]["traceparent"]

    # W3C traceparent format: 00-{trace_id}-{span_id}-{flags}
    parts = tp.split("-")
    assert len(parts) == 4
    assert parts[0] == "00"          # version
    assert len(parts[1]) == 32       # trace_id (16 bytes hex)
    assert len(parts[2]) == 16       # span_id (8 bytes hex)
    assert parts[3] in ("00", "01")  # flags (sampled or not)
```

#### Why this always works

- No external service dependency (Jaeger, otelcol, etc.)
- No OTel SDK required -- we are inspecting HTTP headers, not spans
- Works even with `OTEL_SDK_DISABLED=true`
- Works on Windows, POSIX, Docker, CI

---

### TIER 2: InMemorySpanExporter for Gateway Spans

**Reliability: ALWAYS WORKS.** Uses the OTel SDK already installed in our
dependencies. NOT a mock -- it is a real `SpanExporter` that stores spans
in memory instead of sending to a collector.

#### Wiring as an ADDITIONAL exporter (not a replacement)

`TracerProvider.add_span_processor()` is additive (confirmed from installed
source: `sdk/trace/__init__.py:1435-1443`). Multiple processors run in
registration order. The test exporter runs ALONGSIDE production exporters:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry import trace

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def otel_test_exporter():
    """Wire InMemorySpanExporter into the existing TracerProvider.

    This does NOT replace any production exporter. It adds an additional
    exporter that captures spans in memory for test assertions.
    """
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)

    # Get the currently configured provider
    provider = trace.get_tracer_provider()

    # Add our test processor alongside any existing ones
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(processor)

    yield exporter

    # Cleanup
    processor.shutdown()
```

**Why SimpleSpanProcessor (not BatchSpanProcessor)**: `SimpleSpanProcessor`
exports synchronously in `on_end()`. Spans are immediately available in the
exporter after `span.end()` returns. `BatchSpanProcessor` exports
asynchronously in a daemon thread with configurable delay -- spans would not
be available immediately for assertion.

#### Resetting between tests

```python
@pytest.fixture(autouse=True)
def _reset_otel_spans(otel_test_exporter):
    """Clear captured spans before each test."""
    otel_test_exporter.clear()
    yield
    # Optionally clear after too, but before is sufficient
```

#### Asserting parent/child relationships

```python
def assert_trace_chain(exporter, parent_name: str, child_name: str) -> None:
    """Assert that child_name span is a child of parent_name span."""
    spans = exporter.get_finished_spans()

    parent = next((s for s in spans if s.name == parent_name), None)
    child = next((s for s in spans if s.name == child_name), None)

    assert parent is not None, f"No span named '{parent_name}' found"
    assert child is not None, f"No span named '{child_name}' found"

    # Same trace
    assert child.context.trace_id == parent.context.trace_id, (
        f"Spans are not in the same trace: "
        f"parent={parent.context.trace_id:#034x}, child={child.context.trace_id:#034x}"
    )

    # Parent-child link
    assert child.parent is not None, f"Span '{child_name}' has no parent"
    assert child.parent.span_id == parent.context.span_id, (
        f"Span '{child_name}' parent is not '{parent_name}': "
        f"expected={parent.context.span_id:#018x}, got={child.parent.span_id:#018x}"
    )
```

#### Cross-process limitation

**InMemorySpanExporter only captures spans from the process it runs in.**
For our architecture:
- Gateway spans: captured (gateway runs in the test process or a subprocess)
- Worker spans: NOT captured (worker is a separate subprocess with its own
  TracerProvider)

For worker span visibility, use TIER 3 (otelcol).

---

### TIER 3: testcontainers Jaeger for Cross-Process Span Collection

**Reliability: HARD-FAIL if Docker unavailable.** The fixture starts a Jaeger
container via testcontainers. If Docker is not running, `container.start()`
raises immediately and the test fails. This is the correct signal.

#### Session-scoped Jaeger fixture

```python
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def jaeger():
    """Start Jaeger container for cross-process trace collection.

    HARD-FAILS if Docker is not running. No skip. No degradation.
    """
    container = DockerContainer("jaegertracing/jaeger:latest")
    container.with_exposed_ports(4317, 16686)
    container.with_env("COLLECTOR_OTLP_ENABLED", "true")
    container.start()  # Raises if Docker unavailable

    wait_for_logs(container, "Starting HTTP server", timeout=30)

    otlp_port = container.get_exposed_port(4317)
    ui_port = container.get_exposed_port(16686)
    host = container.get_container_host_ip()

    try:
        yield {
            "otlp_endpoint": f"http://{host}:{otlp_port}",
            "query_url": f"http://{host}:{ui_port}",
        }
    finally:
        container.stop()
```

#### Test pattern (hard-fail, no skip)

```python
@pytest.mark.timeout(120)
@pytest.mark.asyncio(loop_scope="session")
async def test_cross_process_trace_chain(
    gateway_url, worker_url, jaeger
):
    """Assert that gateway and worker spans share the same trace_id.

    Jaeger fixture hard-fails if Docker is unavailable.
    """
    # ... trigger dispatch ...
    # ... wait for flush ...

    # Query Jaeger API for traces
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{jaeger['query_url']}/api/traces",
            params={"service": "vaultspec-a2a", "limit": 10},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    traces = data.get("data", [])
    assert len(traces) > 0, "No traces collected in Jaeger"

    # Find spans from both services
    all_spans = []
    for trace in traces:
        for span in trace.get("spans", []):
            all_spans.append(span)

    services = {s.get("processID") for s in all_spans}
    assert len(services) >= 2, f"Expected spans from 2+ services, got {services}"
```

#### Configuring subprocesses to export to Jaeger

The Jaeger fixture provides a dynamic OTLP endpoint. Pass it to subprocess
env vars:

```python
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _gateway_worker_stack(jaeger):
    env = {
        **os.environ,
        "OTEL_SDK_DISABLED": "false",
        "OTEL_EXPORTER_OTLP_ENDPOINT": jaeger["otlp_endpoint"],
        "OTEL_EXPORTER_OTLP_INSECURE": "true",
        "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
    }
    # ... spawn gateway + worker with this env ...
```

---

### OTel SDK Error Handling: Silent Drop Guarantee

**Confirmed from installed source.** The OTel SDK NEVER raises exceptions
when the OTLP endpoint is unreachable. The error is silently logged and
spans are dropped.

#### Evidence chain (from installed source)

**Layer 1: OTLPSpanExporter._export()** (`exporter/otlp/proto/grpc/exporter.py:419-488`)

```python
for retry_num in range(_MAX_RETRYS):  # 6 retries
    try:
        self._client.Export(request=..., timeout=...)
        return self._result.SUCCESS
    except RpcError as error:
        # Retry on UNAVAILABLE, RESOURCE_EXHAUSTED, etc.
        if error.code() not in _RETRYABLE_ERROR_CODES or retry_num + 1 == _MAX_RETRYS:
            logger.error("Failed to export %s to %s, error code: %s", ...)
            return self._result.FAILURE   # <-- returns FAILURE, never raises
        logger.warning("Transient error ... retrying in %.2fs.", ...)
```

The exporter catches `RpcError` (gRPC connection refused, timeout, etc.),
retries up to 6 times with exponential backoff + jitter, then returns
`SpanExportResult.FAILURE`. **It never raises.**

**Layer 2: BatchProcessor._export()** (`sdk/_shared_internal/__init__.py:172-197`)

```python
def _export(self, batch_strategy):
    with self._export_lock:
        while self._should_export_batch(...):
            try:
                self._exporter.export([...])
            except Exception:   # <-- catches ALL exceptions
                _logger.exception("Exception while exporting %s.", self._exporting)
```

Even if an exporter violates the contract and raises, `BatchProcessor`
catches `Exception` and logs it. **It never propagates.**

**Layer 3: BatchProcessor.worker()** (`sdk/_shared_internal/__init__.py:156-169`)

```python
def worker(self):
    while not self._shutdown:
        self._worker_awaken.wait(self._schedule_delay)
        self._export(...)
```

The worker runs in a **daemon thread**. Any unhandled exception would kill
only the daemon thread, not the main thread. But as shown above, `_export()`
catches everything, so the daemon thread never dies.

**Layer 4: SimpleSpanProcessor.on_end()** (`sdk/trace/export/__init__.py:108-116`)

```python
def on_end(self, span):
    try:
        self.span_exporter.export((span,))
    except Exception:   # <-- catches ALL exceptions
        logger.exception("Exception while exporting Span.")
```

Same pattern. **Never raises.** The span is silently dropped if export fails.

#### Queue overflow behavior

When the queue is full (`_max_queue_size` default: 2048 spans), new spans
are silently dropped with a warning log:

```python
if len(self._queue) == self._max_queue_size:
    _logger.warning("Queue full, dropping %s.", self._exporting)
self._queue.appendleft(data)  # drops oldest from right side
```

#### Summary: OTel never breaks your tests

| Failure Mode | SDK Behavior | Test Impact |
|-------------|-------------|-------------|
| OTLP endpoint unreachable | Log error, return FAILURE, retry 6x | NONE |
| OTLP endpoint timeout | Same as unreachable | NONE |
| Exporter raises exception | Caught by processor, logged | NONE |
| Queue full (>2048 spans) | Drop oldest, log warning | NONE |
| SDK disabled (`OTEL_SDK_DISABLED=true`) | No-op tracer, no spans emitted | NONE |

**Tests will NEVER fail because Jaeger/otelcol is not running.** The SDK
silently absorbs all export failures.

---

### Hard-Fail Lifecycle Pattern (Replaces Skip Guards)

**DEPRECATED**: All `pytest.skip()`, `@pytest.mark.skipif`, and
`@pytest.mark.requires_*` patterns are FORBIDDEN per team-lead mandate.

Fixtures own the full lifecycle. If infrastructure is unavailable, the
fixture raises and the test fails. Example:

```python
# WRONG (deprecated):
requires_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="no docker"
)

# CORRECT (hard-fail):
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def jaeger():
    container = DockerContainer("jaegertracing/jaeger:latest")
    container.with_exposed_ports(4317, 16686)
    container.start()  # Raises if Docker not available = test FAILS
    # ...
```

The hard-fail signal tells the developer: "Docker is a prerequisite for
integration tests. Install and start it before running the suite."

---

### Tier Summary

| Tier | What It Verifies | Dependencies | Failure Mode |
|------|-----------------|-------------|-------------|
| 1 | traceparent headers injected in HTTP requests | httpx (installed) | ALWAYS passes |
| 2 | Gateway spans have correct parent-child relationships | OTel SDK (installed) | ALWAYS passes |
| 3 | Gateway + Worker spans share the same trace_id | Docker + testcontainers | HARD-FAIL if no Docker |

All three tiers are REQUIRED. Tier 3 requires Docker Desktop running.
If Docker is not available, the test suite FAILS -- that is the correct
signal to the developer.

---

Sources:
- Installed library source: `.venv/Lib/site-packages/` (all libraries above)
- psutil documentation: https://psutil.readthedocs.io/
- pytest-timeout PyPI: https://pypi.org/project/pytest-timeout/
- tenacity documentation: https://tenacity.readthedocs.io/
- httpx documentation: https://www.python-httpx.org/
- pytest-asyncio docs: https://pytest-asyncio.readthedocs.io/
- testcontainers-python: https://testcontainers-python.readthedocs.io/ + GitHub source
- testcontainers PyPI: https://pypi.org/project/testcontainers/ (v4.14.1)
- OpenTelemetry Collector: https://opentelemetry.io/docs/collector/
- OTel Python SDK source: `opentelemetry/sdk/_shared_internal/__init__.py` (BatchProcessor error handling)
- OTel OTLP gRPC exporter source: `opentelemetry/exporter/otlp/proto/grpc/exporter.py` (retry + error handling)
