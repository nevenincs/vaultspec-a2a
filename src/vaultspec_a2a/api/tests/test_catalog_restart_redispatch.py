"""Durable restart proof for the current provider-catalog authority."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.dispatch import redispatch_reconciling_threads
from ...control.worker_management import LazyWorkerSpawner
from ...database import close_db, get_session_factory, get_thread, init_db
from ...database.thread_repository import create_thread
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
from ...thread.enums import ThreadStatus
from .conftest import _InProcessWorker

if TYPE_CHECKING:
    from pathlib import Path


def _current_metadata(
    workspace: Path,
) -> tuple[dict[str, object], dict[str, dict[str, Any]]]:
    key = ProviderCatalogKey("deterministic", "in-process-deterministic")
    discovered = discover_in_process_catalog(key)
    now = datetime.now(UTC)
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
        catalog=discovered.catalog,
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


@pytest.mark.asyncio
async def test_current_schema_restart_redispatches_the_exact_frozen_assignment(
    tmp_path: Path,
) -> None:
    """A fresh worker receives durable schema-v1 values without catalog lookup."""
    await close_db()
    await init_db(str(tmp_path / "current-restart.db"))
    worker = _InProcessWorker()
    try:
        metadata, exact_assignment = _current_metadata(tmp_path)
        session_factory = get_session_factory()
        async with session_factory() as session:
            await create_thread(
                session,
                thread_id="current-schema-restart",
                status=ThreadStatus.RECONCILING,
                team_preset="mock-success-single",
                metadata=json.dumps(metadata),
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

        assert len(worker.dispatches) == 1
        dispatch = worker.dispatches[0]
        assert dispatch["thread_id"] == "current-schema-restart"
        assert dispatch["model_assignment"] == exact_assignment
        assert len(contacts) == 1
    finally:
        await worker.client.aclose()
        await close_db()


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
