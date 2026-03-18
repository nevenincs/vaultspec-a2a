"""Smoke tests for the live gateway + worker stack.

Every test here runs against real subprocesses — no mocks, no fakes.
The ``service_stack`` and ``gateway_client`` fixtures from conftest.py
spawn a real gateway (which auto-spawns a worker) on free ports with
an isolated temporary database.

Marked ``@pytest.mark.live`` so the default test run (``-m "not live"``)
skips these.  Run explicitly::

    pytest src/vaultspec_a2a/tests/ -m live -x
"""

import asyncio
import os

import httpx
import pytest

from .conftest import _find_free_port, _start_uvicorn, _stop_process


pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Gateway health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_gateway_health_returns_ok(gateway_client: httpx.AsyncClient):
    """GET /api/health on the gateway returns status=ok for the live stack."""
    resp = await gateway_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["gateway"]["status"] == "ok"
    assert body["database_backend"] == "postgres"
    assert body["checkpoint_backend"] == "postgres"
    assert body["postgres_required"] is False


@pytest.mark.asyncio(loop_scope="session")
async def test_gateway_health_reports_worker_spawned(
    gateway_client: httpx.AsyncClient,
):
    """Gateway /api/health should report worker readiness details."""
    resp = await gateway_client.get("/api/health")
    body = resp.json()
    checks = body["checks"]
    assert "worker_spawned" in checks
    assert "circuit_breaker" in checks
    assert "checkpoint" in checks
    assert checks["circuit_breaker"]["status"] in ("closed", "half_open", "open")
    assert checks["database"]["backend"] == "postgres"
    assert checks["checkpoint"]["backend"] == "postgres"


# ---------------------------------------------------------------------------
# Worker health (direct probe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_worker_health_returns_ok(service_stack: tuple[str, str]):
    """GET /health on the worker returns status=ok."""
    _gateway_url, worker_url = service_stack
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{worker_url}/health", timeout=5.0)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "worker"
    assert body["database_backend"] == "postgres"
    assert body["checkpoint_backend"] == "postgres"


# ---------------------------------------------------------------------------
# API health (aggregated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_api_health_returns_checks(gateway_client: httpx.AsyncClient):
    """GET /api/health on the gateway returns the aggregated health check."""
    resp = await gateway_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    # Overall status may be "degraded" when worker_spawned=no (we spawn
    # the worker externally, not via the gateway's LazyWorkerSpawner).
    assert body["status"] in ("ok", "degraded")
    checks = body["checks"]
    assert checks["gateway"]["status"] == "ok"
    assert checks["database"]["status"] == "ok"
    assert checks["checkpoint"]["status"] == "ok"
    # Worker is running (we spawned it ourselves) — the gateway's httpx
    # client can reach it via the configured VAULTSPEC_WORKER_URL.
    assert checks["worker"]["status"] == "ok"


@pytest.mark.asyncio(loop_scope="session")
async def test_gateway_fails_fast_when_postgres_required_but_sqlite_selected(
    tmp_path,
):
    """Gateway startup must fail loudly on a backend mismatch."""
    gateway_port = _find_free_port()
    worker_port = _find_free_port()
    sqlite_db = tmp_path / "postgres-required-mismatch.db"
    env = {
        **os.environ,
        "VAULTSPEC_HOST": "127.0.0.1",
        "VAULTSPEC_PORT": str(gateway_port),
        "VAULTSPEC_WORKER_PORT": str(worker_port),
        "VAULTSPEC_WORKER_URL": f"http://127.0.0.1:{worker_port}",
        "VAULTSPEC_DATABASE_BACKEND": "sqlite",
        "VAULTSPEC_CHECKPOINT_BACKEND": "sqlite",
        "VAULTSPEC_DATABASE_URL": f"sqlite+aiosqlite:///{sqlite_db}",
        "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
        "VAULTSPEC_POSTGRES_REQUIRED": "true",
        "VAULTSPEC_INTERNAL_TOKEN": "",
        "LANGSMITH_TRACING": "false",
    }
    process = await _start_uvicorn(env, "vaultspec_a2a.api.app:create_app", gateway_port)
    try:
        return_code = await asyncio.wait_for(process.wait(), timeout=10.0)
        stderr = b""
        if process.stderr is not None:
            stderr = await process.stderr.read()
        error_text = stderr.decode(errors="replace")
        assert return_code != 0
        assert "VAULTSPEC_POSTGRES_REQUIRED=true requires" in error_text
    finally:
        await _stop_process(process)


# ---------------------------------------------------------------------------
# Basic REST endpoints (read-only, no worker needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
async def test_list_threads_empty(gateway_client: httpx.AsyncClient):
    """GET /api/threads on a fresh database returns an empty list."""
    resp = await gateway_client.get("/api/threads")
    assert resp.status_code == 200
    body = resp.json()
    assert body["threads"] == []
    assert body["total"] == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_list_team_presets(gateway_client: httpx.AsyncClient):
    """GET /api/teams returns available team presets."""
    resp = await gateway_client.get("/api/teams")
    assert resp.status_code == 200
    body = resp.json()
    assert "presets" in body
    assert isinstance(body["presets"], list)
