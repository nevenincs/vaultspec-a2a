"""Crash recovery integration tests for the worker watchdog.

These tests verify the gateway watchdog can detect worker crashes and
auto-restart the worker process.  Unlike the smoke tests, these use
``VAULTSPEC_AUTO_SPAWN_WORKER=true`` so the gateway owns the worker
subprocess handle and the watchdog can detect process exit.

Each test function gets its own gateway+worker stack to avoid cross-test
pollution from crash/restart state.

Marked ``@pytest.mark.live`` -- skipped by default ``-m "not live"``.
Run explicitly::

    pytest src/vaultspec_a2a/tests/test_crash_recovery.py -m live -x -v
"""

import asyncio
import os
import sys
from datetime import datetime

import httpx
import pytest
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_delay,
    wait_exponential,
)

from .conftest import (
    _find_free_port,
    _HealthCheckError,
    _kill_process_tree,
    _stop_process,
    _wait_for_health,
)

pytestmark = pytest.mark.live

# Watchdog poll interval is 5s, backoff restart is 2+4+8=14s worst case.
# Give ample room for the full cycle.
_CRASH_RECOVERY_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# Per-test stack: gateway with auto-spawn, fresh ports, isolated DB
# ---------------------------------------------------------------------------


async def _create_autospawn_gateway(
    label: str,
    postgres_sqlalchemy_url: str,
    postgres_checkpoint_url: str,
) -> tuple[asyncio.subprocess.Process, str, int, int]:
    """Start a gateway with auto-spawn enabled on fresh ports.

    Returns (process, gateway_url, gateway_port, worker_port).
    """
    gw_port = _find_free_port()
    wk_port = _find_free_port()

    env = {
        **os.environ,
        "VAULTSPEC_HOST": "127.0.0.1",
        "VAULTSPEC_PORT": str(gw_port),
        "VAULTSPEC_WORKER_PORT": str(wk_port),
        "VAULTSPEC_WORKER_URL": f"http://127.0.0.1:{wk_port}",
        "VAULTSPEC_DATABASE_BACKEND": "postgres",
        "VAULTSPEC_CHECKPOINT_BACKEND": "postgres",
        "VAULTSPEC_DATABASE_URL": postgres_sqlalchemy_url,
        "VAULTSPEC_CHECKPOINT_DATABASE_URL": postgres_checkpoint_url,
        # Auto-spawn ON -- gateway owns the worker process handle
        "VAULTSPEC_AUTO_SPAWN_WORKER": "true",
        "VAULTSPEC_INTERNAL_TOKEN": "",
        "VAULTSPEC_MCP_API_BASE_URL": f"http://127.0.0.1:{gw_port}",
        "LANGSMITH_TRACING": "false",
    }

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from vaultspec_a2a.api.app import main; main()",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    gateway_url = f"http://127.0.0.1:{gw_port}"
    await _wait_for_health(gateway_url)
    return process, gateway_url, gw_port, wk_port


async def _trigger_worker_spawn(gateway_url: str, worker_url: str) -> None:
    """Force the lazy worker spawner to start the worker.

    POST to create a thread with a preset -- this triggers a dispatch
    which calls ``LazyWorkerSpawner.ensure_worker()``.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create a thread to trigger the lazy spawn.
        await client.post(
            f"{gateway_url}/api/threads",
            json={"team_preset": "default", "initial_message": "test trigger"},
        )
        # Wait for the worker to become healthy.
        await _wait_for_health(worker_url)


async def _kill_gateway_owned_worker(gateway_url: str) -> int:
    """Kill the exact worker PID owned by the auto-spawn gateway."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{gateway_url}/health")
        resp.raise_for_status()
        body = resp.json()
    worker_pid = body.get("worker_pid")
    if not isinstance(worker_pid, int):
        raise AssertionError(f"gateway did not report an owned worker pid: {body!r}")
    await _kill_process_tree(worker_pid)
    return worker_pid


@retry(
    retry=retry_if_exception_type(_HealthCheckError),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=3.0),
    stop=stop_after_delay(_CRASH_RECOVERY_TIMEOUT),
    reraise=True,
)
async def _wait_for_worker_status(
    gateway_url: str,
    target_status: str,
) -> dict:
    """Poll gateway /health until worker_status matches target."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{gateway_url}/health", timeout=2.0)
            body = resp.json()
            current = body.get("worker_status", "unknown")
            if current != target_status:
                msg = f"worker_status={current!r}, want {target_status!r}"
                raise _HealthCheckError(msg)
            return body
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise _HealthCheckError(str(exc)) from exc


@retry(
    retry=retry_if_exception_type(_HealthCheckError),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=3.0),
    stop=stop_after_delay(_CRASH_RECOVERY_TIMEOUT),
    reraise=True,
)
async def _wait_for_restart_count(
    gateway_url: str,
    minimum_count: int,
) -> dict:
    """Poll gateway /health until a latched restart record is present."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{gateway_url}/health", timeout=2.0)
            body = resp.json()
            current = int(body.get("worker_restart_count", 0))
            if current < minimum_count:
                raise _HealthCheckError(
                    f"worker_restart_count={current!r}, want >= {minimum_count!r}"
                )
            if body.get("worker_last_restart_succeeded") is not True:
                raise _HealthCheckError("worker restart record not completed yet")
            return body
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise _HealthCheckError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(90)
async def test_gateway_survives_worker_death(
    postgres_sqlalchemy_url, postgres_checkpoint_url
):
    """Gateway read-only endpoints keep working when the worker is dead."""
    process, gateway_url, _gw_port, wk_port = await _create_autospawn_gateway(
        "crash_survives",
        postgres_sqlalchemy_url,
        postgres_checkpoint_url,
    )
    worker_url = f"http://127.0.0.1:{wk_port}"

    try:
        # Trigger worker spawn
        await _trigger_worker_spawn(gateway_url, worker_url)

        # Kill the worker
        await _kill_gateway_owned_worker(gateway_url)

        # Small delay for the process to exit
        await asyncio.sleep(1.0)

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Read-only endpoints still work
            resp = await client.get(f"{gateway_url}/api/threads")
            assert resp.status_code == 200

            # Top-level health still returns (gateway itself is ok)
            resp = await client.get(f"{gateway_url}/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["service"] == "gateway"
    finally:
        await _stop_process(process)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(90)
async def test_worker_crash_triggers_watchdog_restart(
    postgres_sqlalchemy_url, postgres_checkpoint_url
):
    """Watchdog detects worker crash and auto-restarts it."""
    process, gateway_url, _gw_port, wk_port = await _create_autospawn_gateway(
        "crash_restart",
        postgres_sqlalchemy_url,
        postgres_checkpoint_url,
    )
    worker_url = f"http://127.0.0.1:{wk_port}"

    try:
        # Trigger worker spawn and verify it's healthy
        await _trigger_worker_spawn(gateway_url, worker_url)

        # Kill the worker
        previous_pid = await _kill_gateway_owned_worker(gateway_url)
        await asyncio.sleep(1.0)

        # Wait for watchdog to detect crash and restart.
        # The watchdog polls every 5s, then does backoff restart (2s first).
        # Total expected time: ~7-12s.
        body = await _wait_for_worker_status(gateway_url, "up")
        assert body["worker_status"] == "up"
        assert body["worker_pid"] != previous_pid

        # Verify the worker is actually healthy again
        await _wait_for_health(worker_url)

    finally:
        await _stop_process(process)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(120)
async def test_worker_status_transitions_during_crash_recovery(
    postgres_sqlalchemy_url, postgres_checkpoint_url
):
    """Crash recovery produces a durable restart record after worker death."""
    process, gateway_url, _gw_port, wk_port = await _create_autospawn_gateway(
        "crash_status",
        postgres_sqlalchemy_url,
        postgres_checkpoint_url,
    )
    worker_url = f"http://127.0.0.1:{wk_port}"

    try:
        # Trigger worker spawn
        await _trigger_worker_spawn(gateway_url, worker_url)

        # Verify initial state is up
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{gateway_url}/health")
            body = resp.json()
            # Status may still be "pending" if watchdog hasn't polled yet.
            assert body["worker_status"] in ("up", "pending")
            initial_restart_count = int(body.get("worker_restart_count", 0))

        # Kill the worker
        previous_pid = await _kill_gateway_owned_worker(gateway_url)
        await asyncio.sleep(1.0)

        # Verify the watchdog leaves behind a durable restart record,
        # then confirm the worker has returned to ``up``.
        body = await _wait_for_restart_count(gateway_url, initial_restart_count + 1)
        assert body["worker_restart_count"] >= initial_restart_count + 1
        assert body["worker_last_restart_reason"] == "process_exited"
        assert "stderr_log=" in body["worker_last_restart_detail"]
        assert body["worker_stderr_log_path"].endswith(".stderr.log")
        assert body["worker_last_restart_succeeded"] is True
        assert body["worker_last_restart_attempts"] >= 1
        assert body["worker_last_restart_started_at"] is not None
        assert body["worker_last_restart_completed_at"] is not None
        assert body["worker_pid"] != previous_pid
        started_at = datetime.fromisoformat(body["worker_last_restart_started_at"])
        completed_at = datetime.fromisoformat(body["worker_last_restart_completed_at"])
        assert completed_at >= started_at

        body = await _wait_for_worker_status(gateway_url, "up")
        assert body["worker_status"] == "up"
        assert body["circuit_breaker"] in ("closed", "half_open")
        await _wait_for_health(worker_url)

    finally:
        await _stop_process(process)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(90)
async def test_dispatch_works_after_crash_recovery(
    postgres_sqlalchemy_url, postgres_checkpoint_url
):
    """Dispatch requests work normally after watchdog recovers the worker.

    Verifies the full cycle: worker up -> crash -> watchdog restart ->
    new dispatch succeeds.  This confirms the circuit breaker closes
    properly and the worker is fully functional post-recovery.
    """
    process, gateway_url, _gw_port, wk_port = await _create_autospawn_gateway(
        "crash_dispatch",
        postgres_sqlalchemy_url,
        postgres_checkpoint_url,
    )
    worker_url = f"http://127.0.0.1:{wk_port}"

    try:
        # Trigger worker spawn
        await _trigger_worker_spawn(gateway_url, worker_url)

        # Kill the worker
        previous_pid = await _kill_gateway_owned_worker(gateway_url)
        await asyncio.sleep(1.0)

        # Wait for watchdog to restore the worker
        body = await _wait_for_worker_status(gateway_url, "up")
        assert body["worker_status"] == "up"
        assert body["worker_pid"] != previous_pid

        # Verify the worker health endpoint is reachable
        await _wait_for_health(worker_url)

        # Create a new thread (dispatch) after recovery — should succeed
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{gateway_url}/api/threads",
                json={
                    "team_preset": "default",
                    "initial_message": "post-recovery test",
                },
            )
            assert resp.status_code == 201

            # Verify threads are accessible
            resp = await client.get(f"{gateway_url}/api/threads")
            assert resp.status_code == 200
            body = resp.json()
            # Should have at least 2 threads (the trigger + the post-recovery one)
            assert body["total"] >= 2

    finally:
        await _stop_process(process)
