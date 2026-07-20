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

import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

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
    worker = doc["services"]["worker"]
    test = worker["healthcheck"]["test"]
    # CMD form: ['CMD', 'python', '-c', '<script>']
    assert isinstance(test, list), "expected list-form healthcheck test"
    script_parts = [part for part in test if part not in ("CMD", "CMD-SHELL")]
    return " ".join(script_parts)


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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
    gateway_port = _pick_free_port()
    jaeger_ui_port = _pick_free_port()
    jaeger_otlp_port = _pick_free_port()
    vidaimock_port = _pick_free_port()
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
        _wait_for_url(f"{gateway_url}/api/health", timeout=60.0)
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
    resp = httpx.get(f"{gateway_url}/api/health", timeout=15.0)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("status") == "ok", f"gateway health status not ok: {body}"


def test_compose_worker_is_connected(compose_integration_stack: Any) -> None:
    """Gateway reports worker_connected=True after attaching to compose worker."""
    gateway_url = compose_integration_stack["gateway_url"]
    # Registration is heartbeat-driven and lags the container healthcheck, so
    # poll rather than sampling once; a worker that never connects still fails.
    _wait_for_health_field(f"{gateway_url}/api/health", "worker_connected", True)


def test_compose_gateway_did_not_spawn_worker(compose_integration_stack: Any) -> None:
    """Gateway health confirms it did not spawn the worker itself."""
    gateway_url = compose_integration_stack["gateway_url"]
    resp = httpx.get(f"{gateway_url}/api/health", timeout=15.0)
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
