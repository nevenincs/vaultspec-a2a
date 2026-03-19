"""Live Postgres verification for startup reconciliation of active threads."""

import asyncio
import time

import httpx
import pytest

from .conftest import _stop_process
from .test_permission_durability_live import (
    _prepare_workspace,
    _restart_gateway,
    _select_certifying_provider,
    _start_manual_stack,
)

pytestmark = pytest.mark.live

_THREAD_STATE_TIMEOUT = 180.0


async def _create_active_autonomous_thread(
    *,
    gateway_url: str,
    workspace_root: str,
    feature_tag: str,
) -> str:
    timeout = httpx.Timeout(60.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        create_resp = await client.post(
            f"{gateway_url}/api/threads",
            json={
                "initial_message": "Implement a small backend improvement.",
                "team_preset": "vaultspec-adaptive-coder",
                "autonomous": True,
                "metadata": {
                    "workspace_root": workspace_root,
                    "feature_tag": feature_tag,
                },
            },
        )
        create_resp.raise_for_status()
        thread_id = create_resp.json()["thread_id"]

        message_resp = await client.post(
            f"{gateway_url}/api/threads/{thread_id}/messages",
            json={"content": "Continue implementing the requested backend work."},
        )
        message_resp.raise_for_status()
        assert message_resp.json()["accepted"] is True

    return thread_id


async def _wait_for_thread_state(
    gateway_url: str,
    thread_id: str,
    *,
    expected_status: str,
    expected_repair_status: str,
    expected_execution_readiness: str,
) -> dict:
    timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
    deadline = time.monotonic() + _THREAD_STATE_TIMEOUT
    last_detail = "no snapshot collected"

    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.monotonic() < deadline:
            resp = await client.get(f"{gateway_url}/api/threads/{thread_id}/state")
            resp.raise_for_status()
            snapshot = resp.json()
            if (
                snapshot.get("status") == expected_status
                and snapshot.get("repair_status") == expected_repair_status
                and snapshot.get("execution_readiness") == expected_execution_readiness
            ):
                return snapshot

            last_detail = (
                f"thread not yet reconciled as "
                f"{expected_status}/{expected_repair_status} "
                f"(status={snapshot.get('status')!r}, "
                f"repair_status={snapshot.get('repair_status')!r}, "
                f"execution_readiness={snapshot.get('execution_readiness')!r}, "
                f"pause_cause={snapshot.get('pause_cause')!r}, "
                f"approval_status={snapshot.get('approval_status')!r})"
            )
            await asyncio.sleep(1.0)

    raise AssertionError(last_detail)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(360)
async def test_running_thread_reconciles_after_gateway_restart(
    postgres_sqlalchemy_url,
    postgres_checkpoint_url,
    tmp_path,
):
    provider = _select_certifying_provider()
    feature_tag = "reconcile-running"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    gateway = None
    worker = None

    try:
        gateway, worker, gateway_url, env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=postgres_checkpoint_url,
        )
        thread_id = await _create_active_autonomous_thread(
            gateway_url=gateway_url,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )

        gateway = await _restart_gateway(gateway, env, gateway_url)
        reconciled = await _wait_for_thread_state(
            gateway_url,
            thread_id,
            expected_status="reconciling",
            expected_repair_status="needs_reconciliation",
            expected_execution_readiness="needs_reconciliation",
        )
        assert reconciled["replay_status"] == "durable"
        assert reconciled["pause_cause"] is None
        assert reconciled["approval_status"] is None
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(360)
async def test_cancelling_thread_reconciles_after_gateway_restart(
    postgres_sqlalchemy_url,
    postgres_checkpoint_url,
    tmp_path,
):
    provider = _select_certifying_provider()
    feature_tag = "reconcile-cancelling"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    gateway = None
    worker = None

    try:
        gateway, worker, gateway_url, env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=postgres_checkpoint_url,
        )
        thread_id = await _create_active_autonomous_thread(
            gateway_url=gateway_url,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )

        timeout = httpx.Timeout(60.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            cancel_resp = await client.post(
                f"{gateway_url}/api/threads/{thread_id}/cancel"
            )
            cancel_resp.raise_for_status()
            cancel_body = cancel_resp.json()
            assert cancel_body["accepted"] is True
            assert cancel_body["status"] == "cancelling"

        await _stop_process(worker)
        worker = None
        gateway = await _restart_gateway(
            gateway,
            env,
            gateway_url,
            health_path="/health",
            require_status_ok=False,
        )
        reconciled = await _wait_for_thread_state(
            gateway_url,
            thread_id,
            expected_status="cancelling",
            expected_repair_status="cancel_pending",
            expected_execution_readiness="cancel_pending",
        )
        assert reconciled["pause_cause"] is None
        timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            health_resp = await client.get(f"{gateway_url}/health")
            health_resp.raise_for_status()
            health_body = health_resp.json()
            assert health_body["status"] == "ok"
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)
