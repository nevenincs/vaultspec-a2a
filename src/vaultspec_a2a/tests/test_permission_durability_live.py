"""Live Postgres verification for paused-thread durability across restart.

These tests run against a real gateway, real worker, live Postgres, and a
real healthy provider probe selected at runtime from the supported providers.
They validate that a durably paused approval request remains discoverable
after gateway restart and that duplicate approval responses remain idempotent.
"""

import asyncio
import os
import subprocess
import sys
import time

from pathlib import Path

import httpx
import pytest

from .conftest import (
    _find_free_port,
    _start_and_wait,
    _stop_process,
    _wait_for_health,
)


pytestmark = pytest.mark.live

_THREAD_READY_TIMEOUT = 180.0
_LIVE_PROVIDER_ENV = "VAULTSPEC_LIVE_TEST_PROVIDER"
_SUPPORTED_CERTIFYING_PROVIDERS = {"claude", "openai", "gemini", "zhipu"}


def _select_certifying_provider() -> str:
    preset_provider = os.environ.get(_LIVE_PROVIDER_ENV)
    if preset_provider:
        provider = preset_provider.strip().lower()
        if provider in _SUPPORTED_CERTIFYING_PROVIDERS:
            return provider
        pytest.fail(
            f"{_LIVE_PROVIDER_ENV}={preset_provider!r} is not a supported live "
            "provider override.",
            pytrace=False,
        )

    probe = subprocess.run(
        [
            sys.executable,
            "-m",
            "vaultspec_a2a.providers.probes.certifying",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    detail = (probe.stdout + probe.stderr).strip()
    if probe.returncode == 0:
        provider = probe.stdout.strip().splitlines()[-1].strip()
        if provider:
            return provider
        pytest.fail(
            "Certifying provider selector exited successfully without returning "
            "a provider name.",
            pytrace=False,
        )
    pytest.fail(
        "Live plan-approval recovery test requires at least one passing real "
        "provider probe because the workspace override forces the adaptive-"
        "coder stack onto the selected live provider path. Run "
        "`uv run python -m vaultspec_a2a.providers.probes.certifying` or "
        "`just verify-live-provider-certifying` first.\n"
        f"{detail[-4000:]}",
        pytrace=False,
    )


def _build_service_env(
    *,
    gateway_port: int,
    worker_port: int,
    postgres_sqlalchemy_url: str,
    postgres_checkpoint_url: str,
) -> dict[str, str]:
    return {
        **os.environ,
        "VAULTSPEC_HOST": "127.0.0.1",
        "VAULTSPEC_PORT": str(gateway_port),
        "VAULTSPEC_WORKER_PORT": str(worker_port),
        "VAULTSPEC_WORKER_URL": f"http://127.0.0.1:{worker_port}",
        "VAULTSPEC_DATABASE_BACKEND": "postgres",
        "VAULTSPEC_CHECKPOINT_BACKEND": "postgres",
        "VAULTSPEC_DATABASE_URL": postgres_sqlalchemy_url,
        "VAULTSPEC_CHECKPOINT_DATABASE_URL": postgres_checkpoint_url,
        "VAULTSPEC_AUTO_SPAWN_WORKER": "false",
        "VAULTSPEC_INTERNAL_TOKEN": "",
        "VAULTSPEC_MCP_API_BASE_URL": f"http://127.0.0.1:{gateway_port}",
        "LANGSMITH_TRACING": "false",
    }


async def _start_manual_stack(
    *,
    postgres_sqlalchemy_url: str,
    postgres_checkpoint_url: str,
) -> tuple[
    asyncio.subprocess.Process,
    asyncio.subprocess.Process,
    str,
    dict[str, str],
]:
    gateway_port = _find_free_port()
    worker_port = _find_free_port()
    env = _build_service_env(
        gateway_port=gateway_port,
        worker_port=worker_port,
        postgres_sqlalchemy_url=postgres_sqlalchemy_url,
        postgres_checkpoint_url=postgres_checkpoint_url,
    )
    worker = await _start_and_wait(
        env,
        "vaultspec_a2a.worker.app:create_worker_app",
        worker_port,
        "Worker",
    )
    gateway = await _start_and_wait(
        env,
        "vaultspec_a2a.api.app:create_app",
        gateway_port,
        "Gateway",
    )
    gateway_url = f"http://127.0.0.1:{gateway_port}"
    await _wait_for_health(gateway_url, health_path="/api/health", require_status_ok=True)
    return gateway, worker, gateway_url, env


def _prepare_workspace(tmp_path: Path, feature_tag: str, provider: str) -> str:
    plan_dir = tmp_path / ".vault" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_file = plan_dir / f"{feature_tag}-plan.md"
    plan_file.write_text(
        "# Execution Plan\n\n- Build the requested feature.\n",
        encoding="utf-8",
    )
    override_dir = tmp_path / ".vaultspec" / "teams"
    override_dir.mkdir(parents=True, exist_ok=True)
    agent_override_dir = tmp_path / ".vaultspec" / "agents"
    agent_override_dir.mkdir(parents=True, exist_ok=True)
    team_override = override_dir / "vaultspec-adaptive-coder.toml"
    team_override.write_text(
        f'''
[team]
id = "vaultspec-adaptive-coder"
display_name = "Vaultspec Adaptive Coder (Certifying Live Test Override)"
description = "Workspace override for deterministic live Postgres approval durability tests."

[team.defaults]
provider = "{provider}"
capability = "low"

[team.supervisor]
provider = "{provider}"
capability = "low"

[team.topology]
type = "star"

[team.permissions]
auto_approve = false

[team.persona]
directive = """
Route directly to vaultspec-coder for implementation tasks. Do not route to
FINISH until the work is complete. Keep the routing decision deterministic.
"""

[team.graph]
step_timeout_seconds = 300
recursion_limit = 50

[[team.workers]]
agent_id = "vaultspec-coder"
model.provider = "{provider}"
model.capability = "low"
'''.strip(),
        encoding="utf-8",
    )
    supervisor_override = agent_override_dir / "vaultspec-supervisor.toml"
    supervisor_override.write_text(
        f'''
[agent]
id = "vaultspec-supervisor"
display_name = "Vaultspec Supervisor (Certifying Live Test Override)"
role = "supervisor"
description = "Minimal supervisor override for deterministic plan-approval live tests."

[agent.persona]
system_prompt = """
You are a routing supervisor for a single-worker implementation team.
If the user asks for implementation work, respond with exactly: vaultspec-coder
Only respond with FINISH when the request is already complete.
"""

[agent.model]
provider = "{provider}"
capability = "low"

[agent.capabilities]
filesystem_read = false
filesystem_write = false
terminal = false

[agent.permissions]
require_approval_for = []
'''.strip(),
        encoding="utf-8",
    )
    return str(tmp_path.resolve())


async def _wait_for_paused_plan_approval(
    gateway_url: str,
    thread_id: str,
) -> dict:
    timeout = httpx.Timeout(30.0, connect=5.0, read=5.0, write=5.0, pool=5.0)
    deadline = time.monotonic() + _THREAD_READY_TIMEOUT
    last_detail = "no snapshot collected"

    async with httpx.AsyncClient(timeout=timeout) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(f"{gateway_url}/api/threads/{thread_id}/state")
                resp.raise_for_status()
                snapshot = resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_detail = str(exc)
                await asyncio.sleep(1.0)
                continue

            pending_permissions = snapshot.get("pending_permissions", [])
            approval_request = next(
                (
                    permission
                    for permission in pending_permissions
                    if permission.get("tool_call") == "plan_approval"
                ),
                None,
            )
            if (
                snapshot.get("status") == "input_required"
                and snapshot.get("approval_status") == "pending"
                and approval_request is not None
            ):
                return snapshot

            last_detail = (
                "thread not yet paused for durable plan approval "
                f"(status={snapshot.get('status')!r}, "
                f"approval_status={snapshot.get('approval_status')!r}, "
                f"pause_cause={snapshot.get('pause_cause')!r}, "
                f"pending_permissions={len(pending_permissions)}, "
                f"repair_status={snapshot.get('repair_status')!r}, "
                f"execution_readiness={snapshot.get('execution_readiness')!r})"
            )
            await asyncio.sleep(1.0)

    raise AssertionError(last_detail)


async def _create_approval_thread(
    *,
    gateway_url: str,
    workspace_root: str,
    feature_tag: str,
) -> tuple[str, dict]:
    timeout = httpx.Timeout(60.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        create_resp = await client.post(
            f"{gateway_url}/api/threads",
            json={
                "initial_message": "Implement a REST API for user authentication.",
                "team_preset": "vaultspec-adaptive-coder",
                "autonomous": False,
                "metadata": {
                    "workspace_root": workspace_root,
                    "feature_tag": feature_tag,
                },
            },
        )
        create_resp.raise_for_status()
        thread_id = create_resp.json()["thread_id"]
    paused_snapshot = await _wait_for_paused_plan_approval(gateway_url, thread_id)
    return thread_id, paused_snapshot


async def _restart_gateway(
    gateway: asyncio.subprocess.Process,
    env: dict[str, str],
    gateway_url: str,
    *,
    health_path: str = "/api/health",
    require_status_ok: bool = True,
) -> asyncio.subprocess.Process:
    await _stop_process(gateway)
    restarted_gateway = await _start_and_wait(
        env,
        "vaultspec_a2a.api.app:create_app",
        int(env["VAULTSPEC_PORT"]),
        "Gateway",
    )
    await _wait_for_health(
        gateway_url,
        health_path=health_path,
        require_status_ok=require_status_ok,
    )
    return restarted_gateway


async def _submit_duplicate_approval_response(
    *,
    gateway_url: str,
    request_id: str,
    retry_key: str,
) -> tuple[dict, dict]:
    timeout = httpx.Timeout(60.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        first_response = await client.post(
            f"{gateway_url}/api/permissions/{request_id}/respond",
            json={"option_id": "approve"},
            headers={"Idempotency-Key": retry_key},
        )
        first_response.raise_for_status()
        second_response = await client.post(
            f"{gateway_url}/api/permissions/{request_id}/respond",
            json={"option_id": "approve"},
            headers={"Idempotency-Key": retry_key},
        )
        second_response.raise_for_status()
    return first_response.json(), second_response.json()


def _assert_execution_state_projection(snapshot: dict) -> None:
    """Assert the normalized execution-state projection is durably present."""
    degraded_reasons = set(snapshot.get("degraded_reasons", []))
    assert "execution_state_projection_missing" not in degraded_reasons
    assert "execution_state_projection_stale" not in degraded_reasons
    assert snapshot.get("snapshot_complete") is True
    assert snapshot.get("pending_interrupt_count", 0) >= 1
    assert snapshot.get("task_count", 0) >= 1
    execution_tasks = snapshot.get("execution_tasks", [])
    assert execution_tasks
    assert any(
        "plan_approval_request" in task.get("interrupt_types", [])
        for task in execution_tasks
    )


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(360)
async def test_plan_approval_survives_gateway_restart_and_response_retry(
    isolated_postgres_urls,
    tmp_path,
):
    postgres_sqlalchemy_url, postgres_checkpoint_url = isolated_postgres_urls
    provider = _select_certifying_provider()
    feature_tag = "auth-flow"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    gateway = None
    worker = None

    try:
        gateway, worker, gateway_url, env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=postgres_checkpoint_url,
        )
        thread_id, paused_before_restart = await _create_approval_thread(
            gateway_url=gateway_url,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )
        approval_request = paused_before_restart["pending_permissions"][0]
        request_id = approval_request["request_id"]
        assert paused_before_restart["approval_request_id"] == request_id
        assert paused_before_restart["pause_cause"] == "plan_approval_request"

        gateway = await _restart_gateway(gateway, env, gateway_url)
        paused_after_restart = await _wait_for_paused_plan_approval(gateway_url, thread_id)
        pending_after_restart = paused_after_restart["pending_permissions"][0]
        assert paused_after_restart["approval_status"] == "pending"
        assert paused_after_restart["approval_request_id"] == request_id
        assert pending_after_restart["request_id"] == request_id
        assert pending_after_restart["tool_call"] == "plan_approval"

        retry_key = "plan-approval-retry-key"
        first_body, second_body = await _submit_duplicate_approval_response(
            gateway_url=gateway_url,
            request_id=request_id,
            retry_key=retry_key,
        )
        assert first_body["request_id"] == request_id
        assert first_body["thread_id"] == thread_id
        assert first_body["accepted"] is True
        assert first_body["approval_status"] == "pending"
        assert first_body["idempotency_key"] == retry_key

        assert second_body["request_id"] == request_id
        assert second_body["thread_id"] == thread_id
        assert second_body["accepted"] is True
        assert second_body["action_id"] == first_body["action_id"]
        assert second_body["action_status"] == first_body["action_status"]
        assert second_body["idempotency_key"] == retry_key
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(360)
async def test_execution_state_projection_survives_gateway_restart_for_paused_thread(
    isolated_postgres_urls,
    tmp_path,
):
    """Paused-thread reconnect snapshots should retain durable execution-state truth."""
    postgres_sqlalchemy_url, postgres_checkpoint_url = isolated_postgres_urls
    provider = _select_certifying_provider()
    feature_tag = "execution-state-restart"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    gateway = None
    worker = None

    try:
        gateway, worker, gateway_url, env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=postgres_checkpoint_url,
        )
        thread_id, paused_before_restart = await _create_approval_thread(
            gateway_url=gateway_url,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )
        _assert_execution_state_projection(paused_before_restart)

        gateway = await _restart_gateway(gateway, env, gateway_url)
        paused_after_restart = await _wait_for_paused_plan_approval(gateway_url, thread_id)
        _assert_execution_state_projection(paused_after_restart)
        assert paused_after_restart["approval_request_id"] == paused_before_restart[
            "approval_request_id"
        ]
        assert paused_after_restart["pending_interrupt_count"] >= paused_before_restart[
            "pending_interrupt_count"
        ]
        assert paused_after_restart["task_count"] >= paused_before_restart["task_count"]
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)
