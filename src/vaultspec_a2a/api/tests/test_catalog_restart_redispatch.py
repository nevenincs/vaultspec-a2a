"""Durable restart proof for the current provider-catalog authority."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.dispatch import redispatch_reconciling_threads
from ...control.worker_management import LazyWorkerSpawner
from ...database import close_db, get_session_factory, get_thread, init_db
from ...database.thread_repository import create_thread
from ...desktop.profile import derive_state_paths
from ...providers.in_process_catalog import discover_in_process_catalog
from ...providers.provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogStatus,
    HealthState,
    ProviderCatalogKey,
    ProviderRecord,
    SelectionReference,
    StructuredProviderHealth,
)
from ...providers.team_selection import freeze_team_selection
from ...testing.catalog_selection import in_process_selection
from ...tests.gateway_boot import (
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)
from ...thread.enums import ThreadStatus
from .conftest import _InProcessWorker

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path


def _current_metadata(
    workspace: Path, *, catalog_revision: str | None = None
) -> tuple[dict[str, object], dict[str, dict[str, Any]]]:
    key = ProviderCatalogKey("deterministic", "in-process-deterministic")
    discovered = discover_in_process_catalog(key)
    now = datetime.now(UTC)
    catalog = discovered.catalog
    if catalog_revision is not None:
        catalog = replace(
            catalog,
            state=replace(
                catalog.state,
                revision=catalog_revision,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            ),
        )
    record = ProviderRecord(
        provider_id=key.provider_id,
        display_name="Deterministic (in-process)",
        execution_mode=key.execution_mode,
        health=StructuredProviderHealth.derive(
            configured=HealthState.AVAILABLE,
            transport=HealthState.AVAILABLE,
            authentication=AuthenticationState.NOT_APPLICABLE,
            catalog=CatalogStatus.AVAILABLE,
            admission=AdmissionState.ADMITTED,
            checked_at=now,
        ),
        catalog=catalog,
    )
    model = record.catalog.models[0]
    frozen = freeze_team_selection(
        selection=SelectionReference(
            provider_id=key.provider_id,
            execution_mode=key.execution_mode,
            catalog_revision=record.catalog.state.revision or "",
            entry_id=model.entry_id,
        ),
        overrides={},
        fallbacks=(),
        required_roles=("mock-coder-success",),
        records=(record,),
    )
    return (
        {
            "workspace_root": str(workspace),
            "provider_catalog_selection": frozen.to_record(),
        },
        frozen.compiler_map(),
    )


def test_current_schema_restart_reaches_a_fresh_production_worker(
    tmp_path: Path,
) -> None:
    """Production startup consumes an exact freeze whose catalog has drifted."""
    app_home = tmp_path / "app-home"
    workspace = tmp_path / "workspace"
    app_home.mkdir()
    workspace.mkdir()
    attach = "attach-restart-proof-0123456789abcdef"
    seed_credentials(
        app_home,
        attach=attach,
        ownership="ownership-restart-proof-fedcba9876543210",
    )
    seat_valid_database(app_home)
    database_path = derive_state_paths(app_home).database_path
    frozen_revision = "frozen-revision-no-longer-served"
    metadata, exact_assignment = _current_metadata(
        workspace, catalog_revision=frozen_revision
    )

    async def _seed() -> None:
        await close_db()
        await init_db(str(database_path))
        try:
            async with get_session_factory()() as session:
                await create_thread(
                    session,
                    thread_id="current-schema-restart",
                    status=ThreadStatus.RECONCILING,
                    team_preset="mock-success-single",
                    metadata=json.dumps(metadata),
                )
                await session.commit()
        finally:
            await close_db()

    asyncio.run(_seed())
    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")
    script = gateway_script(log_level="info")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        environment = armed_gateway_env(
            app_home, gateway_port=gateway_port, worker_port=worker_port
        )
        environment["VAULTSPEC_SERVE_IN_PROCESS_LANES"] = "true"
        environment["VAULTSPEC_REPAIR_ON_STARTUP"] = "false"
        return spawn_gateway(
            script=script,
            gateway_port=gateway_port,
            env=environment,
            log_handle=log_handle,
            new_session=True,
        )

    process = None
    try:
        process, _gateway_port, _worker_port, base_url = spawn_until_ready(
            _spawn, log_path=log_path
        )
        headers = {"Authorization": f"Bearer {attach}"}
        with httpx.Client(base_url=base_url, headers=headers, timeout=240.0) as client:
            catalog = client.get(
                "/v1/provider-catalog", params={"workspace_root": str(workspace)}
            )
            assert catalog.status_code == 200, catalog.text
            live_selection = in_process_selection(catalog.json())
            assert live_selection["catalog_revision"] != frozen_revision

            # A real start is the production dispatch-demand edge. It starts the
            # worker and releases the gateway's deferred startup recovery only
            # after the worker has answered its readiness probe.
            trigger = client.post(
                "/v1/runs",
                json={
                    "stage": "start",
                    "run_id": "restart-demand",
                    "team_preset": "mock-success-single",
                    "message": "release startup recovery",
                    "autonomous": True,
                    "selection": live_selection,
                    "metadata": {"workspace_root": str(workspace)},
                },
            )
            assert trigger.status_code == 201, trigger.text

            deadline = time.monotonic() + 30.0
            snapshot: dict[str, Any] = {}
            while time.monotonic() < deadline:
                response = client.get("/v1/runs/current-schema-restart")
                assert response.status_code == 200, response.text
                snapshot = cast("dict[str, Any]", response.json())
                if snapshot["status"] in {"completed", "failed", "error"}:
                    break
                time.sleep(0.1)
            assert snapshot["status"] == "completed", (
                snapshot,
                log_path.read_text(encoding="utf-8", errors="replace")[-8000:],
            )
            frozen = snapshot["frozen_assignment"]
            assert frozen["assignments"]
            for role in frozen["assignments"]:
                expected = exact_assignment[role["role_id"]]
                assert role["provider_id"] == expected["provider"]
                assert role["execution_mode"] == expected["execution_mode"]
                assert role["model_name"] == expected["model_name"]
                assert role["controls"] == expected["controls"]
                assert role["catalog_revision"] == frozen_revision

            history = client.get("/v1/runs/current-schema-restart/history")
            assert history.status_code == 200, history.text
            agents = history.json()["state"]["agents"]
            assert agents
            assert all(agent["provider"] == "deterministic" for agent in agents)
            assert all(agent["model_name"] == "deterministic" for agent in agents)
    finally:
        if process is not None:
            reap_gateway(process)
        with suppress(Exception):
            log_handle.close()


@pytest.mark.asyncio
async def test_retired_durable_state_is_terminal_before_worker_contact(
    tmp_path: Path,
) -> None:
    """All retired durable authority shapes fail closed during startup recovery."""
    await close_db()
    await init_db(str(tmp_path / "retired-restart.db"))
    worker = _InProcessWorker()
    retired_cases: tuple[tuple[str, tuple[object, ...], str, object], ...] = (
        ("root-profile-id", (), "profile_id", "retired"),
        ("root-default-profile", (), "default_profile_id", "retired"),
        ("root-profile", (), "profile", {"id": "retired"}),
        ("selection-model-profile", ("selection",), "model_profile", "retired"),
        ("selection-model", ("selection",), "model", "retired-model"),
        ("selection-profile", ("selection",), "profile_id", "retired"),
        ("retired-provider", ("selection",), "provider_id", "gemini"),
        ("retired-mode", ("selection",), "execution_mode", "gemini-cli-acp"),
    )
    try:
        metadata, _assignment = _current_metadata(tmp_path)
        current = metadata["provider_catalog_selection"]
        assert isinstance(current, dict)
        original_digest = current["digest"]
        session_factory = get_session_factory()
        async with session_factory() as session:
            for label, path, field, value in retired_cases:
                record = deepcopy(current)
                target: object = record
                for key in path:
                    target = target[key]  # type: ignore[index]
                assert isinstance(target, dict)
                target[field] = value
                assert record["digest"] == original_digest
                await create_thread(
                    session,
                    thread_id=f"retired-durable-{label}",
                    status=ThreadStatus.RECONCILING,
                    team_preset="mock-success-single",
                    metadata=json.dumps(
                        {
                            "workspace_root": str(tmp_path),
                            "provider_catalog_selection": record,
                        }
                    ),
                )
            await create_thread(
                session,
                thread_id="retired-durable-model-profile-sentinel",
                status=ThreadStatus.RECONCILING,
                team_preset="mock-success-single",
                metadata=json.dumps(
                    {
                        "workspace_root": str(tmp_path),
                        "model_profile": {"provider": "gemini", "model": "secret"},
                    }
                ),
            )
            await session.commit()

        contacts: list[float] = []
        spawner = LazyWorkerSpawner(
            worker_url="http://test-worker:8001", worker_port=8001, auto_spawn=False
        )
        spawner.replace_process(None)
        await redispatch_reconciling_threads(
            worker.client,
            WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=30.0),
            spawner,
            record_worker_contact=contacts.append,
        )

        assert worker.dispatches == []
        assert contacts == []
        async with session_factory() as session:
            for label, *_rest in retired_cases:
                thread = await get_thread(session, f"retired-durable-{label}")
                assert thread is not None
                assert thread.status == ThreadStatus.FAILED.value
                assert thread.failure_reason == (
                    "persisted provider catalog selection is invalid"
                )
            sentinel = await get_thread(
                session, "retired-durable-model-profile-sentinel"
            )
            assert sentinel is not None
            assert sentinel.status == ThreadStatus.FAILED.value
            assert sentinel.failure_reason == (
                "retired model-profile state is unsupported; start a new run"
            )
    finally:
        await worker.client.aclose()
        await close_db()
