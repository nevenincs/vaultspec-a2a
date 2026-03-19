"""Live Postgres verification for worker IPC heartbeat and active-thread truth."""

import asyncio
import time

import httpx
import pytest

from .conftest import _stop_process
from .test_permission_durability_live import (
    _prepare_workspace,
    _select_certifying_provider,
    _start_manual_stack,
)

pytestmark = pytest.mark.live

_ACTIVE_THREAD_TIMEOUT = 180.0


async def _create_autonomous_thread(
    *,
    gateway_url: str,
    workspace_root: str,
    feature_tag: str,
) -> str:
    timeout = httpx.Timeout(60.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{gateway_url}/api/threads",
            json={
                "initial_message": (
                    "Implement a backend improvement and report progress."
                ),
                "team_preset": "vaultspec-adaptive-coder",
                "autonomous": True,
                "metadata": {
                    "workspace_root": workspace_root,
                    "feature_tag": feature_tag,
                },
            },
        )
        resp.raise_for_status()
        return resp.json()["thread_id"]


async def _wait_for_thread_activity(
    gateway_url: str, thread_id: str
) -> tuple[dict, dict]:
    timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
    deadline = time.monotonic() + _ACTIVE_THREAD_TIMEOUT
    last_health = None
    last_team_status = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.monotonic() < deadline:
            health_resp = await client.get(f"{gateway_url}/health")
            health_resp.raise_for_status()
            team_resp = await client.get(f"{gateway_url}/api/team/status")
            team_resp.raise_for_status()
            health = health_resp.json()
            team_status = team_resp.json()

            if health.get("worker_connected") is True and thread_id in team_status.get(
                "active_threads", []
            ):
                return health, team_status

            last_health = health
            last_team_status = team_status
            await asyncio.sleep(1.0)

    raise AssertionError(
        "Timed out waiting for live IPC heartbeat activity "
        f"(health={last_health!r}, team_status={last_team_status!r})"
    )


async def _request_cancel(gateway_url: str, thread_id: str) -> dict:
    timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{gateway_url}/api/threads/{thread_id}/cancel")
        resp.raise_for_status()
        return resp.json()


async def _wait_for_thread_to_settle_after_cancel(
    gateway_url: str, thread_id: str
) -> dict:
    timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
    deadline = time.monotonic() + _ACTIVE_THREAD_TIMEOUT
    last_snapshot = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{gateway_url}/api/threads/{thread_id}/state")
            resp.raise_for_status()
            snapshot = resp.json()
            if snapshot.get("status") in {
                "cancelling",
                "cancelled",
                "completed",
                "failed",
            }:
                return snapshot
            last_snapshot = snapshot
            await asyncio.sleep(1.0)

    raise AssertionError(
        f"Timed out waiting for cancel-visible snapshot: {last_snapshot!r}"
    )


async def _wait_for_active_threads_to_clear(gateway_url: str, thread_id: str) -> dict:
    timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
    deadline = time.monotonic() + _ACTIVE_THREAD_TIMEOUT
    last_team_status = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{gateway_url}/api/team/status")
            resp.raise_for_status()
            team_status = resp.json()
            if thread_id not in team_status.get("active_threads", []):
                return team_status
            last_team_status = team_status
            await asyncio.sleep(1.0)

    raise AssertionError(
        f"Timed out waiting for active thread to clear: {last_team_status!r}"
    )


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(480)
async def test_live_worker_heartbeat_tracks_active_thread_and_clears_after_completion(
    postgres_sqlalchemy_url,
    postgres_checkpoint_url,
    tmp_path,
):
    provider = _select_certifying_provider()
    feature_tag = "ipc-heartbeat-live"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    gateway = None
    worker = None

    try:
        gateway, worker, gateway_url, _env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=postgres_checkpoint_url,
        )
        thread_id = await _create_autonomous_thread(
            gateway_url=gateway_url,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )

        health, team_status = await _wait_for_thread_activity(gateway_url, thread_id)
        assert health["status"] == "ok"
        assert health["worker_connected"] is True
        assert health["database_backend"] == "postgres"
        assert health["checkpoint_backend"] == "postgres"
        assert thread_id in team_status["active_threads"]

        cancel_result = await _request_cancel(gateway_url, thread_id)
        assert cancel_result["thread_id"] == thread_id
        assert cancel_result["accepted"] is True
        assert cancel_result["cancelled"] is True
        assert cancel_result["action_status"] == "accepted_not_applied"
        assert cancel_result["status"] == "cancelling"

        snapshot = await _wait_for_thread_to_settle_after_cancel(gateway_url, thread_id)
        cleared_team_status = await _wait_for_active_threads_to_clear(
            gateway_url, thread_id
        )
        assert snapshot["thread_id"] == thread_id
        assert snapshot["status"] in {"cancelling", "cancelled", "completed", "failed"}
        assert thread_id not in cleared_team_status["active_threads"]
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)
