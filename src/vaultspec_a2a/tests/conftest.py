"""Session-scoped fixtures for multi-service integration tests.

Spawns a real gateway + worker stack as child processes with isolated
ports and a live Postgres database. Every test in this directory
exercises the full production code path -- NO mocks, NO fakes, NO stubs.

Fixtures OWN the full service lifecycle:
- They START required services (subprocess or Docker container) in setup
- They STOP and CLEAN UP services in teardown
- If a service fails to start → fixture raises → test HARD FAILS

Trace testing:
    1. **httpx event_hooks** -- request/response logging on ``gateway_client``
    2. **Jaeger testcontainer** -- full OTLP pipeline via Docker
       (InMemorySpanExporter is BANNED — it is a fake)

Fixtures:
    free_port            -- allocate an unused TCP port
    service_env          -- environment variables for an isolated test stack
    gateway_process      -- session-scoped gateway subprocess
    worker_process       -- session-scoped worker subprocess
    service_stack        -- gateway + worker ready, returns (gateway_url, worker_url)
    gateway_client       -- httpx.AsyncClient with event_hook tracing
    jaeger_container     -- session-scoped Jaeger all-in-one Docker container
    jaeger_otlp_endpoint -- OTLP gRPC endpoint from the Jaeger container
    jaeger_query_url     -- HTTP query API base URL (port 16686)
"""

import asyncio
import contextlib
import logging
import os
import socket
import sys

import httpx
import psutil
import pytest
import pytest_asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)
from testcontainers.core.container import DockerContainer


__all__: list[str] = []

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Port allocation
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Bind to port 0 and return the OS-assigned port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def free_port():
    """Return a free TCP port for the gateway."""
    return _find_free_port()


@pytest.fixture(scope="session")
def worker_free_port():
    """Return a free TCP port for the worker."""
    return _find_free_port()


# ---------------------------------------------------------------------------
# Jaeger testcontainer -- Tier 3 OTLP pipeline
# ---------------------------------------------------------------------------

_JAEGER_IMAGE = "jaegertracing/jaeger:2"  # Jaeger v2 (v1 EOL Dec 2025)
_JAEGER_OTLP_GRPC_PORT = 4317
_JAEGER_OTLP_HTTP_PORT = 4318
_JAEGER_UI_PORT = 16686
_JAEGER_ADMIN_PORT = 14269  # Admin HTTP server — GET / returns 204 when ready
_POSTGRES_IMAGE = "postgres:16-alpine"
_POSTGRES_PORT = 5432
_POSTGRES_USER = "vaultspec"
_POSTGRES_PASSWORD = "vaultspec"
_POSTGRES_DB = "vaultspec"


async def _probe_postgres_ready(database_url: str) -> None:
    """Open a real async connection and execute a trivial query."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def jaeger_container():
    """Start a Jaeger v2 container with OTLP receiver.

    Session-scoped: one container shared across all tests.
    Hard-fails if Docker is unavailable or the container fails to become healthy.
    Uses the admin HTTP port (14269) for readiness — GET / → 204.
    """
    import time

    container = (
        DockerContainer(_JAEGER_IMAGE)
        .with_exposed_ports(
            _JAEGER_OTLP_GRPC_PORT,
            _JAEGER_OTLP_HTTP_PORT,
            _JAEGER_UI_PORT,
            _JAEGER_ADMIN_PORT,
        )
        .with_env("COLLECTOR_OTLP_ENABLED", "true")
    )
    container.start()

    # Poll the admin endpoint until it returns 204 (real readiness signal)
    host = container.get_container_host_ip()
    admin_port = container.get_exposed_port(_JAEGER_ADMIN_PORT)
    admin_url = f"http://{host}:{admin_port}/"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(admin_url, timeout=2.0)
            if resp.status_code == 204:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        container.stop()
        pytest.fail(
            f"Jaeger container did not become healthy within 30s (admin: {admin_url})",
            pytrace=False,
        )

    yield container
    container.stop()


@pytest.fixture(scope="session")
def jaeger_otlp_endpoint(jaeger_container):
    """Return the OTLP gRPC endpoint for the running Jaeger container.

    Format: ``http://<host>:<mapped_port>``
    """
    host = jaeger_container.get_container_host_ip()
    port = jaeger_container.get_exposed_port(_JAEGER_OTLP_GRPC_PORT)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def jaeger_query_url(jaeger_container):
    """Return the Jaeger HTTP query API base URL (port 16686).

    Use to query ``/api/traces?service=...`` for span assertions.
    """
    host = jaeger_container.get_container_host_ip()
    port = jaeger_container.get_exposed_port(_JAEGER_UI_PORT)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def postgres_container():
    """Start a live Postgres container for production-certifying tests."""
    import time

    container = (
        DockerContainer(_POSTGRES_IMAGE)
        .with_exposed_ports(_POSTGRES_PORT)
        .with_env("POSTGRES_USER", _POSTGRES_USER)
        .with_env("POSTGRES_PASSWORD", _POSTGRES_PASSWORD)
        .with_env("POSTGRES_DB", _POSTGRES_DB)
    )
    container.start()

    host = container.get_container_host_ip()
    port = container.get_exposed_port(_POSTGRES_PORT)
    db_url = (
        "postgresql+asyncpg://"
        f"{_POSTGRES_USER}:{_POSTGRES_PASSWORD}@{host}:{port}/{_POSTGRES_DB}"
    )
    deadline = time.monotonic() + 30.0

    while time.monotonic() < deadline:
        try:
            asyncio.run(_probe_postgres_ready(db_url))
            break
        except Exception:
            time.sleep(0.5)
    else:
        container.stop()
        pytest.fail("Postgres container did not become ready within 30s", pytrace=False)

    yield container
    container.stop()


@pytest.fixture(scope="session")
def postgres_sqlalchemy_url(postgres_container):
    """Return the SQLAlchemy async URL for the live Postgres container."""
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(_POSTGRES_PORT)
    return (
        "postgresql+asyncpg://"
        f"{_POSTGRES_USER}:{_POSTGRES_PASSWORD}@{host}:{port}/{_POSTGRES_DB}"
    )


@pytest.fixture(scope="session")
def postgres_checkpoint_url(postgres_container):
    """Return the LangGraph checkpoint DSN for the live Postgres container."""
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(_POSTGRES_PORT)
    return (
        "postgresql://"
        f"{_POSTGRES_USER}:{_POSTGRES_PASSWORD}@{host}:{port}/{_POSTGRES_DB}"
        "?sslmode=disable"
    )


# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def service_env(
    free_port,
    worker_free_port,
    jaeger_otlp_endpoint,
    postgres_sqlalchemy_url,
    postgres_checkpoint_url,
):
    """Build an env dict for an isolated gateway + worker pair.

    - Unique ports (no collision with dev server)
    - Live Postgres database
    - Auto-spawn DISABLED -- we spawn the worker ourselves
    - No internal token (dev mode)
    - Real OTLP endpoint wired to the Jaeger testcontainer (no fakes)
    """
    return {
        **os.environ,
        # Gateway binding
        "VAULTSPEC_HOST": "127.0.0.1",
        "VAULTSPEC_PORT": str(free_port),
        # Worker binding
        "VAULTSPEC_WORKER_PORT": str(worker_free_port),
        "VAULTSPEC_WORKER_URL": f"http://127.0.0.1:{worker_free_port}",
        # Postgres is the certifying backend for this suite.
        "VAULTSPEC_DATABASE_BACKEND": "postgres",
        "VAULTSPEC_CHECKPOINT_BACKEND": "postgres",
        "VAULTSPEC_DATABASE_URL": postgres_sqlalchemy_url,
        "VAULTSPEC_CHECKPOINT_DATABASE_URL": postgres_checkpoint_url,
        # Disable auto-spawn -- we manage the worker subprocess explicitly
        "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
        # Dev mode -- no auth token required
        "VAULTSPEC_INTERNAL_TOKEN": "",
        # MCP loopback URL -- point at our test gateway
        "VAULTSPEC_MCP_API_BASE_URL": f"http://127.0.0.1:{free_port}",
        # Disable LangSmith tracing in tests
        "LANGSMITH_TRACING": "false",
        # Real OTLP pipeline -- gateway and worker export to Jaeger testcontainer
        "OTEL_EXPORTER_OTLP_ENDPOINT": jaeger_otlp_endpoint,
        "OTEL_EXPORTER_OTLP_INSECURE": "true",
    }


# ---------------------------------------------------------------------------
# requires_jaeger fail-fast hook
# ---------------------------------------------------------------------------


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Fail (not skip) any test marked requires_jaeger when Jaeger is unreachable.

    Checks Jaeger's admin health endpoint (port 14269, GET / → 204).
    pytest.fail() produces a hard ERROR in the report, not a silent SKIP.
    """
    if item.get_closest_marker("requires_jaeger"):
        try:
            resp = httpx.get(
                f"http://localhost:{_JAEGER_ADMIN_PORT}/",
                timeout=2.0,
            )
            if resp.status_code != 204:
                pytest.fail(
                    f"Jaeger admin endpoint returned HTTP {resp.status_code} "
                    f"(expected 204). Run `just jaeger-up` to start Jaeger.",
                    pytrace=False,
                )
        except Exception as exc:
            pytest.fail(
                f"Jaeger is not reachable at http://localhost:{_JAEGER_ADMIN_PORT}/: {exc}. "
                "Run `just jaeger-up` to start Jaeger.",
                pytrace=False,
            )


# ---------------------------------------------------------------------------
# Health polling (tenacity-based)
# ---------------------------------------------------------------------------

_HEALTH_TIMEOUT = 30.0  # seconds


class _HealthCheckError(Exception):
    """Raised when a health check probe fails (retried by tenacity)."""


@retry(
    retry=retry_if_exception_type(_HealthCheckError),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
    stop=stop_after_delay(_HEALTH_TIMEOUT),
    reraise=True,
)
async def _wait_for_health(
    url: str,
    *,
    health_path: str = "/health",
    require_status_ok: bool = False,
) -> None:
    """Poll the selected health endpoint until it returns a ready response.

    Uses tenacity exponential backoff.  Raises ``_HealthCheckError``
    (retried) on transient failures.  On timeout, tenacity's
    ``RetryError`` propagates as a hard failure (``reraise=True``).
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}{health_path}", timeout=2.0)
            if resp.status_code != 200:
                msg = f"{url}{health_path} returned {resp.status_code}"
                raise _HealthCheckError(msg)
            if require_status_ok and resp.json().get("status") != "ok":
                raise _HealthCheckError(f"{url}{health_path} is not ready")
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise _HealthCheckError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Process management (psutil-based teardown)
# ---------------------------------------------------------------------------


async def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children using psutil.

    psutil handles cross-platform process tree enumeration reliably.
    Falls back to platform-specific commands if psutil can't find the
    process (already exited).
    """
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        # Kill children first, then parent
        for child in children:
            with contextlib.suppress(psutil.NoSuchProcess):
                child.kill()
        with contextlib.suppress(psutil.NoSuchProcess):
            parent.kill()
        # Wait for all to exit
        psutil.wait_procs([*children, parent], timeout=5)
    except psutil.NoSuchProcess:
        # Process already exited — nothing to do
        pass
    except psutil.AccessDenied:
        # Fallback to platform-specific tree kill
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                "taskkill",
                "/T",
                "/F",
                "/PID",
                str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)
        else:
            import signal

            os.killpg(os.getpgid(pid), signal.SIGTERM)


async def _start_uvicorn(
    env: dict[str, str],
    module: str,
    port: int,
) -> asyncio.subprocess.Process:
    """Start a uvicorn subprocess for the given app factory module."""
    entrypoint = (
        "from vaultspec_a2a.api.app import main; main()"
        if module == "vaultspec_a2a.api.app:create_app"
        else "from vaultspec_a2a.worker.app import main; main()"
    )
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        entrypoint,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    """Stop a subprocess, using psutil tree kill."""
    if process.returncode is not None:
        return
    try:
        await _kill_process_tree(process.pid)
    except Exception:
        process.kill()
    try:
        await asyncio.wait_for(process.wait(), timeout=10.0)
    except TimeoutError:
        process.kill()


def _verify_no_orphans(pids: list[int]) -> None:
    """Assert that none of the given PIDs are still running.

    Called in teardown to verify clean process cleanup.
    """
    orphans = []
    for pid in pids:
        if psutil.pid_exists(pid):
            try:
                proc = psutil.Process(pid)
                if proc.status() != psutil.STATUS_ZOMBIE:
                    orphans.append(pid)
            except psutil.NoSuchProcess:
                pass
    if orphans:
        pytest.fail(
            f"Orphan processes detected after teardown: {orphans}. "
            "Process cleanup is broken."
        )


async def _start_and_wait(
    env: dict[str, str],
    module: str,
    port: int,
    label: str,
) -> asyncio.subprocess.Process:
    """Start a service subprocess and wait for it to become healthy.

    Returns the process handle.  Raises ``pytest.fail`` on timeout —
    this is a HARD FAILURE, not a skip.
    """
    process = await _start_uvicorn(env, module, port)
    url = f"http://127.0.0.1:{port}"

    try:
        await _wait_for_health(url)
    except (_HealthCheckError, Exception):
        stderr_data = b""
        if process.stderr:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                stderr_data = await asyncio.wait_for(
                    process.stderr.read(4096),
                    timeout=2.0,
                )
        await _stop_process(process)
        pytest.fail(
            f"{label} did not start on port {port} within "
            f"{_HEALTH_TIMEOUT}s.\nstderr: "
            f"{stderr_data.decode(errors='replace')[:1000]}"
        )

    return process


# ---------------------------------------------------------------------------
# Session-scoped fixtures (gateway + worker stack)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_process(service_env, free_port):
    """Start the gateway subprocess and wait for it to be healthy.

    Yields the ``asyncio.subprocess.Process`` handle.
    Hard-fails if the gateway does not start within timeout.
    """
    process = await _start_and_wait(
        service_env,
        "vaultspec_a2a.api.app:create_app",
        free_port,
        "Gateway",
    )
    pid = process.pid
    yield process
    await _stop_process(process)
    _verify_no_orphans([pid])


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def worker_process(service_env, worker_free_port):
    """Start the worker subprocess and wait for it to be healthy.

    Yields the ``asyncio.subprocess.Process`` handle.
    Hard-fails if the worker does not start within timeout.
    """
    process = await _start_and_wait(
        service_env,
        "vaultspec_a2a.worker.app:create_worker_app",
        worker_free_port,
        "Worker",
    )
    pid = process.pid
    yield process
    await _stop_process(process)
    _verify_no_orphans([pid])


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def service_stack(
    gateway_process,
    worker_process,
    free_port,
    worker_free_port,
):
    """Full gateway + worker stack, both healthy.

    Both processes are started and health-checked by their respective
    fixtures.  This fixture just bundles the URLs.

    Returns ``(gateway_url, worker_url)`` tuple.
    """
    gateway_url = f"http://127.0.0.1:{free_port}"
    worker_url = f"http://127.0.0.1:{worker_free_port}"
    await _wait_for_health(
        gateway_url,
        health_path="/api/health",
        require_status_ok=True,
    )
    return gateway_url, worker_url


# ---------------------------------------------------------------------------
# Tier 1: httpx event_hooks -- request/response trace logging
# ---------------------------------------------------------------------------


async def _log_request(request: httpx.Request) -> None:
    """Log outgoing HTTP requests for test trace visibility."""
    logger.debug("-> %s %s", request.method, request.url)


async def _log_response(response: httpx.Response) -> None:
    """Log incoming HTTP responses for test trace visibility."""
    logger.debug(
        "<- %s %s %d",
        response.request.method,
        response.request.url,
        response.status_code,
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def gateway_client(service_stack):
    """Async httpx client pointed at the live test gateway.

    Session-scoped: reused across all integration tests.
    Includes event_hooks for Tier-1 request/response trace logging.
    """
    gateway_url, _worker_url = service_stack
    async with httpx.AsyncClient(
        base_url=gateway_url,
        timeout=httpx.Timeout(30.0, connect=5.0),
        event_hooks={
            "request": [_log_request],
            "response": [_log_response],
        },
    ) as client:
        yield client


# InMemorySpanExporter fixtures have been removed.
# MANDATE: All OTel span assertions must go through a live Jaeger instance.
# Use jaeger_container + jaeger_query_url fixtures for real trace verification.
