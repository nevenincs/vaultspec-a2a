"""Live Postgres verification for explicit degraded snapshot responses."""

import asyncio
import time

import httpx
import pytest

from testcontainers.core.container import DockerContainer

from .conftest import (
    _POSTGRES_DB,
    _POSTGRES_IMAGE,
    _POSTGRES_PASSWORD,
    _POSTGRES_PORT,
    _POSTGRES_USER,
    _probe_postgres_ready,
    _stop_process,
)
from .test_permission_durability_live import (
    _create_approval_thread,
    _prepare_workspace,
    _select_certifying_provider,
    _start_manual_stack,
)


pytestmark = pytest.mark.live


async def _start_checkpoint_postgres_container() -> tuple[DockerContainer, str]:
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
    sqlalchemy_url = (
        "postgresql+asyncpg://"
        f"{_POSTGRES_USER}:{_POSTGRES_PASSWORD}@{host}:{port}/{_POSTGRES_DB}"
    )
    checkpoint_url = (
        "postgresql://"
        f"{_POSTGRES_USER}:{_POSTGRES_PASSWORD}@{host}:{port}/{_POSTGRES_DB}"
        "?sslmode=disable"
    )

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            await _probe_postgres_ready(sqlalchemy_url)
            return container, checkpoint_url
        except Exception:
            await asyncio.sleep(0.5)

    container.stop()
    pytest.fail("Checkpoint Postgres container did not become ready within 30s")


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(480)
async def test_snapshot_reports_explicit_degradation_when_checkpoint_backend_is_unavailable(
    postgres_sqlalchemy_url,
    tmp_path,
):
    provider = _select_certifying_provider()
    feature_tag = "snapshot-degradation"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    checkpoint_container = None
    gateway = None
    worker = None

    try:
        checkpoint_container, checkpoint_url = await _start_checkpoint_postgres_container()
        gateway, worker, gateway_url, _env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=checkpoint_url,
        )
        thread_id, paused_snapshot = await _create_approval_thread(
            gateway_url=gateway_url,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )

        request_id = paused_snapshot["approval_request_id"]
        assert paused_snapshot["status"] == "input_required"
        assert paused_snapshot["approval_status"] == "pending"
        assert request_id is not None

        checkpoint_container.stop()
        checkpoint_container = None

        timeout = httpx.Timeout(30.0, connect=5.0, read=20.0, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{gateway_url}/api/threads/{thread_id}/state")
            resp.raise_for_status()
            snapshot = resp.json()

        assert snapshot["thread_id"] == thread_id
        assert snapshot["status"] == "input_required"
        assert snapshot["approval_status"] == "pending"
        assert snapshot["approval_request_id"] == request_id
        assert snapshot["pause_cause"] == "plan_approval_request"
        assert snapshot["snapshot_complete"] is False
        assert snapshot["replay_status"] == "unknown"
        assert set(snapshot["degraded_reasons"]) & {
            "checkpoint_unavailable",
            "checkpoint_timeout",
        }
        assert snapshot["pending_permissions"], "durable permission truth was lost"
        assert snapshot["pending_permissions"][0]["request_id"] == request_id
        assert snapshot["pending_permissions"][0]["tool_call"] == "plan_approval"
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)
        if checkpoint_container is not None:
            checkpoint_container.stop()
