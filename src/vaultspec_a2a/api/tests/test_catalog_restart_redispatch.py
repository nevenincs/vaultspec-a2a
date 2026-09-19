"""Durable restart proof for the current provider-catalog authority."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from contextlib import suppress
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from vaultspec_a2a.tests._write_authority import make_test_write_authority

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
    CatalogState,
    CatalogStatus,
    ControlKind,
    HealthState,
    ModelCatalogEntry,
    NativeControl,
    NativeControlOption,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderRecord,
    SelectionReference,
    StructuredProviderHealth,
)
from ...providers.team_selection import (
    FrozenTeamSelection,
    freeze_team_selection,
    model_assignment_digest,
)
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
from ..schemas.gateway import FrozenTeamAssignmentSummary
from .conftest import _InProcessWorker

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path


def _current_metadata(
    workspace: Path,
    *,
    catalog_revision: str | None = None,
    model_value: str = "deterministic",
) -> tuple[dict[str, object], FrozenTeamSelection]:
    key = ProviderCatalogKey("deterministic", "in-process-deterministic")
    discovered = discover_in_process_catalog(key)
    now = datetime.now(UTC)
    catalog = discovered.catalog
    if model_value != catalog.models[0].provider_value:
        catalog = replace(
            catalog,
            models=(
                replace(
                    catalog.models[0],
                    provider_value=model_value,
                    display_name=f"Historical {model_value}",
                ),
            ),
        )
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
    codex_key = ProviderCatalogKey("codex", "codex-app-server")
    codex_revision = "frozen-unused-codex-fallback"
    codex_record = ProviderRecord(
        provider_id=codex_key.provider_id,
        display_name="Codex",
        execution_mode=codex_key.execution_mode,
        health=StructuredProviderHealth.derive(
            configured=HealthState.AVAILABLE,
            transport=HealthState.AVAILABLE,
            authentication=AuthenticationState.AUTHENTICATED,
            catalog=CatalogStatus.AVAILABLE,
            admission=AdmissionState.ADMITTED,
            checked_at=now,
        ),
        catalog=ProviderCatalog(
            key=codex_key,
            state=CatalogState(
                status=CatalogStatus.AVAILABLE,
                checked_at=now,
                revision=codex_revision,
                expires_at=now + timedelta(minutes=5),
            ),
            models=(
                ModelCatalogEntry(
                    entry_id="unused-codex-entry",
                    provider_value="unused-codex-model",
                    display_name="Unused Codex fallback",
                    native_control_ids=("reasoning_effort",),
                ),
            ),
            native_controls=(
                NativeControl(
                    control_id="reasoning_effort",
                    kind=ControlKind.THOUGHT_LEVEL,
                    display_name="Reasoning effort",
                    options=(
                        NativeControlOption(
                            option_id="medium",
                            provider_value="medium",
                            display_name="Medium",
                        ),
                    ),
                    default_option_id="medium",
                ),
            ),
        ),
    )
    primary = SelectionReference(
        provider_id=key.provider_id,
        execution_mode=key.execution_mode,
        catalog_revision=record.catalog.state.revision or "",
        entry_id=model.entry_id,
    )
    frozen = freeze_team_selection(
        selection=primary,
        overrides={"mock-coder-success": primary},
        fallbacks=(
            SelectionReference(
                provider_id=codex_key.provider_id,
                execution_mode=codex_key.execution_mode,
                catalog_revision=codex_revision,
                entry_id="unused-codex-entry",
            ),
        ),
        required_roles=("mock-coder-success",),
        records=(record, codex_record),
    )
    return (
        {
            "workspace_root": str(workspace),
            "provider_catalog_selection": frozen.to_record(),
        },
        frozen,
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
    metadata, frozen_selection = _current_metadata(
        workspace, catalog_revision=frozen_revision
    )
    exact_record = frozen_selection.to_record()
    exact_disclosure = frozen_selection.disclosure()
    exact_wire_disclosure = FrozenTeamAssignmentSummary.model_validate(
        exact_disclosure
    ).model_dump(mode="json")
    exact_assignment = frozen_selection.compiler_map()
    exact_assignment_digest = model_assignment_digest(exact_assignment)
    other_metadata, other_frozen_selection = _current_metadata(
        workspace,
        catalog_revision="other-frozen-revision",
        model_value="deterministic-other",
    )
    other_assignment_digest = model_assignment_digest(
        other_frozen_selection.compiler_map()
    )
    assert other_assignment_digest != exact_assignment_digest
    fallback = exact_record["fallbacks"][0]
    assert fallback["defaulted_control_ids"] == ["reasoning_effort"]
    assert fallback["controls"] == [
        {
            "control_id": "reasoning_effort",
            "option_id": "medium",
            "provider_value": "medium",
            "display_name": "Reasoning effort",
            "option_display_name": "Medium",
        }
    ]

    async def _seed() -> None:
        await close_db()
        await init_db(str(database_path))
        try:
            async with get_session_factory()() as session:
                await create_thread(
                    session,
                    write_authority=make_test_write_authority(),
                    thread_id="current-schema-restart",
                    status=ThreadStatus.RECONCILING,
                    team_preset="mock-success-single",
                    metadata=json.dumps(metadata),
                )
                await create_thread(
                    session,
                    write_authority=make_test_write_authority(),
                    thread_id="same-assignment-restart",
                    status=ThreadStatus.RECONCILING,
                    team_preset="mock-success-single",
                    metadata=json.dumps(metadata),
                )
                await create_thread(
                    session,
                    write_authority=make_test_write_authority(),
                    thread_id="other-assignment-restart",
                    status=ThreadStatus.RECONCILING,
                    team_preset="mock-success-single",
                    metadata=json.dumps(other_metadata),
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

            def _await_terminal(run_id: str) -> dict[str, Any]:
                deadline = time.monotonic() + 30.0
                observed: dict[str, Any] = {}
                while time.monotonic() < deadline:
                    response = client.get(f"/v1/runs/{run_id}")
                    assert response.status_code == 200, response.text
                    observed = cast("dict[str, Any]", response.json())
                    if observed["status"] in {"completed", "failed", "error"}:
                        return observed
                    time.sleep(0.1)
                return observed

            snapshot = _await_terminal("current-schema-restart")
            assert snapshot["status"] == "completed", (
                snapshot,
                log_path.read_text(encoding="utf-8", errors="replace")[-8000:],
            )
            # Semantic object equality covers every nested identity and value;
            # JSON object key order is deliberately not part of the contract.
            assert snapshot["frozen_assignment"] == exact_wire_disclosure
            assert snapshot["frozen_assignment"]["digest"] == exact_record["digest"]

            history = client.get("/v1/runs/current-schema-restart/history")
            assert history.status_code == 200, history.text
            agents = history.json()["state"]["agents"]
            assert agents
            assert all(agent["provider"] == "deterministic" for agent in agents)
            assert all(agent["model_name"] == "deterministic" for agent in agents)
            assert all(
                agent["thread_id"] == "current-schema-restart" for agent in agents
            )
            assert history.json()["state"]["model_assignment_digest"] == (
                exact_assignment_digest
            )
            same_snapshot = _await_terminal("same-assignment-restart")
            other_snapshot = _await_terminal("other-assignment-restart")
            assert same_snapshot["status"] == "completed"
            assert other_snapshot["status"] == "completed"

            same_history = client.get("/v1/runs/same-assignment-restart/history")
            other_history = client.get("/v1/runs/other-assignment-restart/history")
            assert same_history.status_code == 200, same_history.text
            assert other_history.status_code == 200, other_history.text
            assert same_history.json()["state"]["model_assignment_digest"] == (
                exact_assignment_digest
            )
            assert other_history.json()["state"]["model_assignment_digest"] == (
                other_assignment_digest
            )
            assert {
                agent["thread_id"] for agent in same_history.json()["state"]["agents"]
            } == {"same-assignment-restart"}
            assert {
                agent["thread_id"] for agent in other_history.json()["state"]["agents"]
            } == {"other-assignment-restart"}
            assert {
                agent["provider"] for agent in other_history.json()["state"]["agents"]
            } == {"deterministic"}
            assert {
                agent["model_name"] for agent in other_history.json()["state"]["agents"]
            } == {"deterministic-other"}

            # Read the production database through an independent read-only
            # connection while the gateway still owns it. Recovery must not
            # rewrite any byte-relevant value in the accepted frozen record.
            with sqlite3.connect(
                f"file:{database_path.as_posix()}?mode=ro", uri=True
            ) as connection:
                stored_json = connection.execute(
                    "SELECT thread_metadata FROM threads WHERE id = ?",
                    ("current-schema-restart",),
                ).fetchone()
            assert stored_json is not None
            assert json.loads(stored_json[0])["provider_catalog_selection"] == (
                exact_record
            )
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
    retired_cases: tuple[tuple[str, tuple[str, ...], str, object], ...] = (
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
        current_raw = metadata["provider_catalog_selection"]
        assert isinstance(current_raw, dict)
        current = cast("dict[str, object]", current_raw)
        original_digest = current["digest"]
        session_factory = get_session_factory()
        async with session_factory() as session:
            for label, path, field, value in retired_cases:
                record = deepcopy(current)
                target: dict[str, object] = record
                for key in path:
                    nested = target[key]
                    assert isinstance(nested, dict)
                    target = cast("dict[str, object]", nested)
                target[field] = value
                assert record["digest"] == original_digest
                await create_thread(
                    session,
                    write_authority=make_test_write_authority(),
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
                write_authority=make_test_write_authority(),
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
                    "stored execution authority is incompatible (corrupt)"
                )
            sentinel = await get_thread(
                session, "retired-durable-model-profile-sentinel"
            )
            assert sentinel is not None
            assert sentinel.status == ThreadStatus.FAILED.value
            assert sentinel.failure_reason == (
                "stored execution authority is incompatible (retired)"
            )
    finally:
        await worker.client.aclose()
        await close_db()
