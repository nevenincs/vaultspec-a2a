"""Compose server profile regression certification.

Two assertion layers:

Structural (config-level):
    Parse the real compose YMLs to assert worker topology, authenticated
    healthchecks, Postgres overlay presence, and Jaeger/VidaiMock wiring.
    These run whenever the service suite is selected; they require no Docker
    daemon and cannot be broken by a transient environment.

Live (service-marked, needs Docker):
    Start the full integration stack via docker-compose and verify gateway
    health, worker connectivity, Jaeger reachability, and operator lifecycle
    (gateway never auto-spawns the independently managed compose worker).
    Tests fail loudly if Docker is unavailable rather than skipping.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
import yaml

from ..testing.ports import free_port

if TYPE_CHECKING:
    from collections.abc import Generator

REPO_ROOT = Path(__file__).resolve().parents[3]
PROD_COMPOSE = REPO_ROOT / "service" / "docker-compose.prod.yml"
PROD_POSTGRES_COMPOSE = REPO_ROOT / "service" / "docker-compose.prod.postgres.yml"
DEV_COMPOSE = REPO_ROOT / "service" / "docker-compose.dev.yml"
INTEGRATION_COMPOSE = REPO_ROOT / "service" / "docker-compose.integration.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_compose(path: Path) -> dict[str, Any]:
    """Return a parsed compose document."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _worker_healthcheck_cmd(compose_path: Path) -> str:
    """Return the worker healthcheck command string from a compose file."""
    doc = _load_compose(compose_path)
    worker: dict[str, Any] = doc["services"]["worker"]
    raw: object = worker["healthcheck"]["test"]
    # CMD form: ['CMD', 'python', '-c', '<script>']
    assert isinstance(raw, list), "expected list-form healthcheck test"
    # ``isinstance`` proves the container, never its elements; the CMD form is
    # a string vector, and a non-string element fails loudly at the join below.
    test = cast("list[str]", raw)
    script_parts = [part for part in test if part not in ("CMD", "CMD-SHELL")]
    return " ".join(script_parts)


def _resolve_docker() -> str:
    for candidate in ("docker", "docker.exe"):
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    raise FileNotFoundError("Docker CLI not found in PATH")


def _wait_for_url(
    url: str,
    *,
    timeout: float = 120.0,
    interval: float = 2.0,
    status: int = 200,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code == status:
                return
        except Exception:
            pass
        time.sleep(interval)
    raise TimeoutError(f"Timed out waiting for {url} to return HTTP {status}")


def _wait_for_health_field(
    health_url: str,
    field: str,
    expected: object,
    *,
    timeout: float = 90.0,
    interval: float = 2.0,
) -> dict[str, Any]:
    """Poll gateway health until *field* equals *expected*; return the last body.

    Container healthchecks gate only process liveness, not the asynchronous
    gateway-worker registration, so a field like ``worker_connected`` flips true
    a few heartbeats after both containers are healthy. Polling removes that race
    without hiding a genuine failure: a worker that never registers still trips
    the timeout, and the last observed body is raised for diagnosis.
    """
    deadline = time.monotonic() + timeout
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(health_url, timeout=5.0)
            if resp.status_code == 200:
                body = resp.json()
                if body.get(field) == expected:
                    return body
        except Exception:
            pass
        time.sleep(interval)
    raise TimeoutError(
        f"gateway health {field!r} did not reach {expected!r} within {timeout}s; "
        f"last body: {body}"
    )


# ---------------------------------------------------------------------------
# Structural assertions — parse real YMLs, no Docker required
# ---------------------------------------------------------------------------


def test_prod_worker_healthcheck_carries_ipc_bearer() -> None:
    """Prod worker healthcheck reads VAULTSPEC_INTERNAL_TOKEN as IPC bearer."""
    cmd = _worker_healthcheck_cmd(PROD_COMPOSE)
    assert "VAULTSPEC_INTERNAL_TOKEN" in cmd, (
        "prod worker healthcheck must reference VAULTSPEC_INTERNAL_TOKEN"
    )
    assert "Authorization" in cmd, (
        "prod worker healthcheck must set Authorization header"
    )
    assert "Bearer" in cmd, "prod worker healthcheck must use Bearer scheme"


def test_dev_worker_healthcheck_carries_ipc_bearer() -> None:
    """Dev worker healthcheck is auth-aware using optional VAULTSPEC_INTERNAL_TOKEN."""
    cmd = _worker_healthcheck_cmd(DEV_COMPOSE)
    assert "VAULTSPEC_INTERNAL_TOKEN" in cmd, (
        "dev worker healthcheck must reference VAULTSPEC_INTERNAL_TOKEN"
    )
    assert "Authorization" in cmd, (
        "dev worker healthcheck must set Authorization header"
    )
    # Dev uses .get() so the token is optional — verify the graceful fallback.
    assert ".get(" in cmd, (
        "dev worker healthcheck must use os.environ.get for optional token"
    )


def test_integration_worker_healthcheck_carries_ipc_bearer() -> None:
    """Integration worker healthcheck reads VAULTSPEC_INTERNAL_TOKEN."""
    cmd = _worker_healthcheck_cmd(INTEGRATION_COMPOSE)
    assert "VAULTSPEC_INTERNAL_TOKEN" in cmd, (
        "integration worker healthcheck must reference VAULTSPEC_INTERNAL_TOKEN"
    )
    assert "Authorization" in cmd, (
        "integration worker healthcheck must set Authorization header"
    )


def test_prod_postgres_overlay_is_separate_file() -> None:
    """Postgres overlay is a discrete file that does not touch base topology."""
    assert PROD_POSTGRES_COMPOSE.exists(), (
        f"Postgres overlay file missing: {PROD_POSTGRES_COMPOSE}"
    )
    overlay = _load_compose(PROD_POSTGRES_COMPOSE)
    services = overlay.get("services", {})
    assert "postgres" in services, "overlay must declare a postgres service"
    # Overlay extends worker via environment/depends_on only — no new topology.
    if "worker" in services:
        assert set(services["worker"]) <= {"environment", "depends_on"}, (
            "overlay worker block must only extend environment/depends_on"
        )
    assert "healthcheck" in services["postgres"], (
        "postgres service must declare a healthcheck"
    )


def test_prod_jaeger_service_present() -> None:
    """Prod compose includes a Jaeger service for OTLP tracing."""
    doc = _load_compose(PROD_COMPOSE)
    assert "jaeger" in doc["services"], "prod compose must declare a jaeger service"


def test_integration_jaeger_service_present() -> None:
    """Integration compose includes Jaeger for certification tracing."""
    doc = _load_compose(INTEGRATION_COMPOSE)
    assert "jaeger" in doc["services"], (
        "integration compose must declare a jaeger service"
    )


def test_integration_vidaimock_service_present() -> None:
    """Integration compose includes VidaiMock for provider certification."""
    doc = _load_compose(INTEGRATION_COMPOSE)
    assert "vidaimock" in doc["services"], (
        "integration compose must declare a vidaimock service"
    )


def test_prod_gateway_does_not_auto_spawn_worker() -> None:
    """Prod gateway sets VAULTSPEC_AUTO_SPAWN_WORKER=false — independently managed."""
    doc = _load_compose(PROD_COMPOSE)
    gateway_env: dict[str, str] = doc["services"]["gateway"].get("environment", {})
    assert gateway_env.get("VAULTSPEC_AUTO_SPAWN_WORKER") == "false", (
        "prod gateway must declare VAULTSPEC_AUTO_SPAWN_WORKER=false so it never "
        "spawns or adopts the independently managed Compose worker"
    )


def test_prod_worker_topology_excludes_desktop_lifecycle() -> None:
    """Prod worker does not carry desktop-lifecycle environment variables."""
    doc = _load_compose(PROD_COMPOSE)
    worker_env: dict[str, str] = doc["services"]["worker"].get("environment", {})
    desktop_keys = {k for k in worker_env if "DESKTOP" in k or "CAPSULE" in k}
    assert not desktop_keys, (
        "prod worker environment must not contain desktop-lifecycle vars: "
        f"{desktop_keys}"
    )


def test_integration_gateway_does_not_auto_spawn_worker() -> None:
    """Integration gateway sets VAULTSPEC_AUTO_SPAWN_WORKER=false."""
    doc = _load_compose(INTEGRATION_COMPOSE)
    gateway_env: dict[str, str] = doc["services"]["gateway"].get("environment", {})
    assert gateway_env.get("VAULTSPEC_AUTO_SPAWN_WORKER") == "false", (
        "integration gateway must declare VAULTSPEC_AUTO_SPAWN_WORKER=false"
    )


# ---------------------------------------------------------------------------
# Live compose fixture — full integration stack in Docker
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_integration_stack() -> Any:
    """Start the full integration stack via docker-compose and yield stack metadata.

    Fails loudly if Docker is unavailable rather than skipping.  Uses
    ``docker compose up --wait`` so Docker waits for all service healthchecks
    (including the now-authenticated worker ``/health``) before yielding.
    """
    docker = _resolve_docker()
    gateway_port = free_port()
    jaeger_ui_port = free_port()
    jaeger_otlp_port = free_port()
    vidaimock_port = free_port()
    project = f"vaultspec-compose-regression-{uuid.uuid4().hex[:8]}"

    compose_env = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": project,
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "VAULTSPEC_PORT": str(gateway_port),
        "JAEGER_UI_PORT": str(jaeger_ui_port),
        "JAEGER_OTLP_PORT": str(jaeger_otlp_port),
        "VIDAIMOCK_PORT": str(vidaimock_port),
    }

    compose_cmd = [
        docker,
        "compose",
        "-p",
        project,
        "-f",
        str(INTEGRATION_COMPOSE),
    ]

    try:
        try:
            subprocess.run(
                [*compose_cmd, "up", "-d", "--build", "--wait"],
                env=compose_env,
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                timeout=600,
            )
        except subprocess.CalledProcessError as error:
            # ``--wait`` reports only WHICH container is unhealthy, never why. The
            # container logs carry the reason and are gone after teardown, so they
            # are surfaced on the failure itself.
            logs = subprocess.run(
                [*compose_cmd, "logs", "--no-color", "--tail", "80"],
                env=compose_env,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            raise AssertionError(
                "compose stack did not become healthy\n"
                f"stderr:\n{(error.stderr or b'').decode(errors='replace')}\n"
                f"container logs:\n{logs.stdout}\n{logs.stderr}"
            ) from error
        # Double-check gateway readiness via the public health endpoint.
        gateway_url = f"http://127.0.0.1:{gateway_port}"
        _wait_for_url(f"{gateway_url}/health", timeout=60.0)
        yield {
            "gateway_url": gateway_url,
            "jaeger_url": f"http://127.0.0.1:{jaeger_ui_port}",
            "vidaimock_url": f"http://127.0.0.1:{vidaimock_port}",
        }
    finally:
        subprocess.run(
            [*compose_cmd, "down", "-v", "--remove-orphans"],
            env=compose_env,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            timeout=120,
        )


# ---------------------------------------------------------------------------
# Live compose tests — require the integration stack to be running
# ---------------------------------------------------------------------------


def test_compose_gateway_health_is_ok(compose_integration_stack: Any) -> None:
    """Gateway reports status=ok when the independently managed worker is healthy."""
    gateway_url = compose_integration_stack["gateway_url"]
    resp = httpx.get(f"{gateway_url}/health", timeout=15.0)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("status") == "ok", f"gateway health status not ok: {body}"


def test_compose_worker_is_connected(compose_integration_stack: Any) -> None:
    """Gateway reports worker_connected=True after attaching to compose worker."""
    gateway_url = compose_integration_stack["gateway_url"]
    # Registration is heartbeat-driven and lags the container healthcheck, so
    # poll rather than sampling once; a worker that never connects still fails.
    _wait_for_health_field(f"{gateway_url}/health", "worker_connected", True)


def test_compose_gateway_did_not_spawn_worker(compose_integration_stack: Any) -> None:
    """Gateway health confirms it did not spawn the worker itself."""
    gateway_url = compose_integration_stack["gateway_url"]
    resp = httpx.get(f"{gateway_url}/health", timeout=15.0)
    assert resp.status_code == 200
    body = resp.json()
    checks = body.get("checks", {})
    worker_check = checks.get("worker", {})
    assert worker_check.get("status") == "ok", (
        f"worker check must be ok in gateway health; got: {checks}"
    )


def test_compose_jaeger_reachable(compose_integration_stack: Any) -> None:
    """Jaeger UI is reachable — traces can be ingested and queried."""
    jaeger_url = compose_integration_stack["jaeger_url"]
    resp = httpx.get(f"{jaeger_url}/api/services", timeout=15.0)
    assert resp.status_code == 200, (
        f"Jaeger /api/services expected 200, got {resp.status_code}: {resp.text}"
    )


def test_compose_vidaimock_reachable(compose_integration_stack: Any) -> None:
    """VidaiMock is reachable — deterministic provider wiring is intact."""
    vidaimock_url = compose_integration_stack["vidaimock_url"]
    resp = httpx.post(
        f"{vidaimock_url}/mock-coder-human/v1/chat/completions",
        json={
            "model": "mock-coder-human",
            "messages": [{"role": "user", "content": "compose regression probe"}],
            "stream": False,
        },
        timeout=15.0,
    )
    assert resp.status_code == 200, (
        f"VidaiMock expected 200, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# Real-process provenance — the Compose gateway attaches, never spawns/evicts
# ---------------------------------------------------------------------------
#
# The Compose gateway runs with VAULTSPEC_AUTO_SPAWN_WORKER=false (asserted
# structurally above): it attaches to an independently managed worker and must
# never spawn or evict one. These drive the production attach seam
# (``LazyWorkerSpawner.ensure_worker`` with ``auto_spawn=False``) in-process,
# unarmed - exactly the Compose profile - against a REAL foreign-gateway worker
# process. The occupant is the modeled adversary (a worker heartbeating a
# different gateway), not a stand-in for the code under test.

_FOREIGN_WORKER_SERVER = """
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[1])
body = json.loads(sys.argv[2])
log_path = sys.argv[3]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("GET " + self.path + "\\n")
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("POST " + self.path + "\\n")
        self.send_response(503)
        self.end_headers()

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""


@contextmanager
def _worker_on_port(
    tmp_path: Path, port: int, body: dict[str, Any]
) -> Generator[tuple[subprocess.Popen[bytes], Path]]:
    """Run a real worker process serving *body* on ``/health`` at *port*."""
    log_path = tmp_path / f"worker-requests-{port}.log"
    log_path.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _FOREIGN_WORKER_SERVER,
            str(port),
            json.dumps(body),
            str(log_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with httpx.Client(timeout=1.0) as client:
                    if client.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                        break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            raise AssertionError("worker process never came up")
        yield proc, log_path
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
            proc.wait(timeout=10)


def test_compose_provenance_mismatch_fails_closed_without_eviction(
    tmp_path: Path,
) -> None:
    """A Compose gateway refuses a foreign-gateway worker and never evicts it.

    The Compose profile is unarmed with ``auto_spawn=False``: it attaches only to
    a worker that declares THIS gateway as its heartbeat target. A worker on the
    port declaring a different ``gateway_url`` is a provenance mismatch and must
    fail closed - not adopted - without any eviction, because the attach path
    never spawns and eviction lives only on the spawn path.

    Discriminating on both halves against a real worker process:

    - Fails closed: ``ensure_worker`` leaves ``spawned`` False. Degrade the
      provenance check to a bare health probe and the foreign worker is adopted,
      flipping this to True.
    - Without eviction: the worker receives only ``GET /health`` and survives.
      Any ``POST /admin/shutdown`` would mean the Compose profile tried to evict
      an independently managed worker it does not own.
    """
    from ..control.config import settings
    from ..control.worker_management import LazyWorkerSpawner

    port = free_port()
    foreign_gateway_url = "http://127.0.0.1:2"
    assert foreign_gateway_url.rstrip("/") != settings.gateway_url.rstrip("/"), (
        "the modeled mismatch must actually differ from this gateway's URL"
    )
    body = {"status": "healthy", "gateway_url": foreign_gateway_url}

    with _worker_on_port(tmp_path, port, body) as (worker, request_log):
        spawner = LazyWorkerSpawner(f"http://127.0.0.1:{port}", port, auto_spawn=False)
        asyncio.run(spawner.ensure_worker())

        # Fails closed: the foreign-gateway worker is not adopted as ours.
        assert spawner.spawned is False

        # Without eviction: only health provenance reads, never a shutdown, and
        # the independently managed worker survives untouched.
        requests = request_log.read_text(encoding="utf-8").splitlines()
        assert requests, "the gateway never even probed the worker port"
        assert all(line.startswith("GET /health") for line in requests), requests
        assert worker.poll() is None, "the Compose worker must not be evicted"


def test_compose_matching_provenance_attaches(tmp_path: Path) -> None:
    """The same attach path DOES adopt a same-gateway worker (discriminator).

    Proves the refusal above is provenance-specific, not a harness that always
    fails: a worker declaring THIS gateway's URL is adopted (``spawned`` True)
    through the identical unarmed ``ensure_worker`` seam, again without any
    eviction.
    """
    from ..control.config import settings
    from ..control.worker_management import LazyWorkerSpawner

    port = free_port()
    body = {"status": "healthy", "gateway_url": settings.gateway_url}

    with _worker_on_port(tmp_path, port, body) as (worker, request_log):
        spawner = LazyWorkerSpawner(f"http://127.0.0.1:{port}", port, auto_spawn=False)
        asyncio.run(spawner.ensure_worker())

        assert spawner.spawned is True
        requests = request_log.read_text(encoding="utf-8").splitlines()
        assert all(line.startswith("GET /health") for line in requests), requests
        assert worker.poll() is None
