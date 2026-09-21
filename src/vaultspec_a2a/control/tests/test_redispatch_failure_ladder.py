# pyright: reportPrivateUsage=false

"""Re-dispatch failure logging must not re-log identically per stuck thread.

Real DB, real threads in RECONCILING status, a real (forced-open) circuit
breaker - no mocks. Pins the loop-hygiene fix: a large reconciling batch that
all fail the same way (a persistent circuit-open, e.g. after a restart) must
log the failure ladder-style (1st occurrence, every Nth repeat, a batch-end
summary) instead of once per thread.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from ...tests._write_authority import make_test_write_authority

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ...database.models import ThreadModel

from ...control.accepted_input import freeze_accepted_input
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.dispatch import (
    _REDISPATCH_LOG_EVERY_N,
    redispatch_reconciling_threads,
)
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...control.execution_authority import (
    ExecutionAuthorityError,
    resolve_execution_authority,
)
from ...control.worker_management import LazyWorkerSpawner
from ...database import create_control_action, create_thread, get_thread
from ...database.session import close_db, get_session_factory, init_db
from ...ipc.schemas import DispatchRequest
from ...providers.provider_catalog import (
    AdmissionState,
    AuthenticationState,
    CatalogState,
    CatalogStatus,
    HealthState,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogKey,
    ProviderHealthAxes,
    ProviderRecord,
    SelectionReference,
    StructuredProviderHealth,
)
from ...providers.team_selection import freeze_team_selection
from ...team.team_config import load_team_config
from ...thread.enums import ThreadStatus
from ...thread.executable_graph import freeze_graph_definition

_LOGGER_NAME = "vaultspec_a2a.control.dispatch"


async def _create_reconciling_thread_with_receipt(
    session: AsyncSession,
    *,
    thread_id: str,
    team_preset: str,
    metadata: str,
) -> ThreadModel:
    """Seed a current-schema reconciling row and its real action receipt."""
    authority = make_test_write_authority()
    thread = await create_thread(
        session,
        write_authority=authority,
        thread_id=thread_id,
        status=ThreadStatus.RECONCILING,
        team_preset=team_preset,
        metadata=metadata,
    )
    parsed = json.loads(metadata)
    workspace = Path(parsed.get("workspace_root") or Path.cwd())
    if not workspace.is_absolute():
        workspace = Path.cwd()
    try:
        assignment = resolve_execution_authority(metadata).model_assignment
    except ExecutionAuthorityError:
        assignment = {}
    dispatch = DispatchRequest(
        action="ingest",
        thread_id=thread.id,
        content="recover",
        workspace_root=str(workspace),
        recursion_limit=25,
        team_preset=team_preset,
        graph_definition=freeze_graph_definition(
            load_team_config(team_preset, workspace_root=workspace),
            workspace_root=workspace,
        ),
        model_assignment=assignment,
    )
    await create_control_action(
        session,
        thread_id=thread_id,
        action_type=authority.action_type,
        idempotency_key=f"{thread_id}-ingest",
        dispatch_id=authority.action_receipt_id,
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        payload=freeze_accepted_input(dispatch, intent={"content": "recover"}),
    )
    assert (
        await prepare_graph_action_receipt(
            session, thread_id=thread.id, dispatch_id=authority.action_receipt_id
        )
        is not None
    )
    return thread


def _current_metadata(workspace_root: str | None) -> dict[str, object]:
    """Build a valid current selection record for redispatch-path tests."""
    now = datetime.now(UTC)
    key = ProviderCatalogKey("deterministic", "in-process-deterministic")
    catalog = ProviderCatalog(
        key=key,
        state=CatalogState(
            status=CatalogStatus.AVAILABLE,
            checked_at=now,
            revision="test-revision",
            expires_at=now + timedelta(minutes=5),
        ),
        models=(
            ModelCatalogEntry(
                entry_id="deterministic",
                provider_value="deterministic",
                display_name="Deterministic",
            ),
        ),
    )
    health = StructuredProviderHealth.derive(
        axes=ProviderHealthAxes(
            configured=HealthState.AVAILABLE,
            transport=HealthState.AVAILABLE,
            authentication=AuthenticationState.NOT_APPLICABLE,
            catalog=CatalogStatus.AVAILABLE,
            admission=AdmissionState.ADMITTED,
        ),
        checked_at=now,
    )
    record = ProviderRecord(
        provider_id="deterministic",
        display_name="Deterministic",
        execution_mode="in-process-deterministic",
        health=health,
        catalog=catalog,
    )
    frozen = freeze_team_selection(
        selection=SelectionReference(
            provider_id="deterministic",
            execution_mode="in-process-deterministic",
            catalog_revision="test-revision",
            entry_id="deterministic",
        ),
        overrides={},
        fallbacks=(),
        required_roles=("mock-coder-success",),
        records=(record,),
    )
    metadata: dict[str, object] = {"provider_catalog_selection": frozen.to_record()}
    if workspace_root is not None:
        metadata["workspace_root"] = workspace_root
    return metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retired_key",
    [
        "MODEL_MAP",
        "default_profile",
        "default_profile_id",
        "model_profile",
        "profile",
        "profile_id",
    ],
)
async def test_retired_stored_authority_fails_closed_without_redispatch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, retired_key: str
) -> None:
    """Stored retired policy is detected by key and refused without interpretation."""
    db_file = tmp_path / "redispatch-retired-authority.db"
    await close_db()
    await init_db(str(db_file))
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="retired-authority",
                team_preset="mock-success-single",
                metadata=json.dumps(
                    {
                        "workspace_root": str(tmp_path),
                        "provider_catalog_selection": _current_metadata(str(tmp_path))[
                            "provider_catalog_selection"
                        ],
                        # The exact current freeze cannot make a retired root
                        # authority safe. Its value is deliberately malformed
                        # and must never be interpreted or reflected.
                        retired_key: ["must", "not", "be", "read"],
                    }
                ),
            )
            await session.commit()

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        spawner.replace_process(None)
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=1, recovery_timeout=999.0
        )

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9", timeout=0.2
        ) as client:
            with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
                await redispatch_reconciling_threads(
                    client,
                    circuit_breaker,
                    spawner,
                    record_worker_contact=lambda _when: pytest.fail(
                        "retired state reached worker dispatch"
                    ),
                )

        async with session_factory() as session:
            thread = await get_thread(session, "retired-authority")
        assert thread is not None
        assert thread.status == ThreadStatus.FAILED.value
        assert thread.failure_reason == (
            "stored execution authority is incompatible (retired)"
        )
        assert any(
            "Refusing incompatible execution authority (retired)" in record.getMessage()
            for record in caplog.records
        )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_invalid_or_absent_frozen_selection_fails_each_thread_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Neither corrupt nor absent current authority reaches a dispatch request."""
    db_file = tmp_path / "redispatch-invalid-frozen.db"
    await close_db()
    await init_db(str(db_file))
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            valid_with_extra = _current_metadata(str(tmp_path))
            frozen_record = valid_with_extra["provider_catalog_selection"]
            assert isinstance(frozen_record, dict)
            frozen_record["profile_id"] = "retired"
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="unchanged-digest-extra-field",
                team_preset="mock-success-single",
                metadata=json.dumps(valid_with_extra),
            )
            # list_threads orders newest first, so create the absent thread before
            # the corrupt one to prove a malformed first item does not abort.
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="absent-after-corrupt",
                team_preset="mock-success-single",
                metadata=json.dumps({"workspace_root": str(tmp_path)}),
            )
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="corrupt-modern-freeze",
                team_preset="mock-success-single",
                metadata=json.dumps(
                    {
                        "workspace_root": str(tmp_path),
                        "provider_catalog_selection": {
                            "schema_version": 1,
                            "digest": "not-a-valid-digest",
                        },
                    }
                ),
            )
            await session.commit()

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        spawner.replace_process(None)
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=1, recovery_timeout=999.0
        )
        circuit_breaker.force_open()

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9", timeout=0.2
        ) as client:
            with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
                await redispatch_reconciling_threads(
                    client,
                    circuit_breaker,
                    spawner,
                    record_worker_contact=lambda _when: pytest.fail(
                        "invalid frozen state reached worker dispatch"
                    ),
                )

        async with session_factory() as session:
            corrupt = await get_thread(session, "corrupt-modern-freeze")
            absent = await get_thread(session, "absent-after-corrupt")
            extra = await get_thread(session, "unchanged-digest-extra-field")
        assert corrupt is not None
        assert corrupt.status == ThreadStatus.FAILED.value
        assert corrupt.failure_reason == (
            "stored execution authority is incompatible (corrupt)"
        )
        assert absent is not None
        assert absent.status == ThreadStatus.FAILED.value
        assert absent.failure_reason == (
            "stored execution authority is incompatible (absent)"
        )
        assert extra is not None
        assert extra.status == ThreadStatus.FAILED.value
        assert extra.failure_reason == (
            "stored execution authority is incompatible (corrupt)"
        )
        assert any(
            "Refusing incompatible execution authority" in record.getMessage()
            for record in caplog.records
        )
        assert any(
            "absent-after-corrupt" in record.getMessage()
            and "incompatible_execution_authority" in record.getMessage()
            for record in caplog.records
        )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_a_thread_with_no_active_project_fails_alone_and_the_sweep_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An unrecoverable thread must not strand every healthy one behind it.

    A reconciling thread inherits the active project it was created with. One
    whose stored metadata names none cannot be re-sited, and the ingest contract
    refuses to construct a dispatch without it - so the refusal has to happen in
    the sweep, per thread. Left to the constructor, the raised error would abort
    the whole pass and the healthy threads after it would never be re-dispatched.
    """
    db_file = tmp_path / "redispatch-no-project.db"
    await close_db()
    await init_db(str(db_file))
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            # Newest first, so the healthy thread is created first and the
            # projectless one is reached before it.
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="healthy-after-projectless",
                team_preset="mock-success-single",
                metadata=json.dumps(_current_metadata(str(tmp_path))),
            )
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="projectless",
                team_preset="mock-success-single",
                metadata=json.dumps(
                    {**_current_metadata(None), "feature_tag": "no-project-here"}
                ),
            )
            await session.commit()

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        spawner.replace_process(None)
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=1, recovery_timeout=999.0
        )
        circuit_breaker.force_open()

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9", timeout=0.2
        ) as client:
            with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
                await redispatch_reconciling_threads(
                    client,
                    circuit_breaker,
                    spawner,
                    record_worker_contact=lambda _when: None,
                )

        async with session_factory() as session:
            projectless = await get_thread(session, "projectless")
            healthy = await get_thread(session, "healthy-after-projectless")
        assert projectless is not None
        assert projectless.status == ThreadStatus.FAILED.value
        assert "no active project" in (projectless.failure_reason or "")
        # The sweep reached the thread AFTER the refusal, which is the property
        # under test: a raised validator would have aborted before this one.
        assert healthy is not None
        assert healthy.status == ThreadStatus.RECONCILING.value
        assert any(
            "no active project" in record.getMessage()
            and "projectless" in record.getMessage()
            for record in caplog.records
        )
        assert any(
            "Circuit breaker open" in record.getMessage()
            and "healthy-after-projectless" in record.getMessage()
            for record in caplog.records
        )
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_a_relative_stored_project_fails_its_thread_rather_than_the_sweep(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A root that is PRESENT but unusable must refuse here too, not at the request.

    The sibling test above stores no ``workspace_root`` at all, which a bare type
    check already refuses. This one stores a relative path: a string, present,
    and still not a project a dispatch can be sited on, because resolving it
    would anchor the run to whatever directory this process was started in. It
    is the case that reaches the minting rather than the type check, and the one
    that used to raise inside the request constructor and abort the whole pass.
    """
    db_file = tmp_path / "redispatch-relative-project.db"
    await close_db()
    await init_db(str(db_file))
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="healthy-after-relative",
                team_preset="mock-success-single",
                metadata=json.dumps(_current_metadata(str(tmp_path))),
            )
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="relative-project",
                team_preset="mock-success-single",
                metadata=json.dumps(_current_metadata("workspaces/project")),
            )
            await session.commit()

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        spawner.replace_process(None)
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=1, recovery_timeout=999.0
        )
        circuit_breaker.force_open()

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9", timeout=0.2
        ) as client:
            with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
                await redispatch_reconciling_threads(
                    client,
                    circuit_breaker,
                    spawner,
                    record_worker_contact=lambda _when: None,
                )

        async with session_factory() as session:
            relative = await get_thread(session, "relative-project")
            healthy = await get_thread(session, "healthy-after-relative")
        assert relative is not None
        assert relative.status == ThreadStatus.FAILED.value
        assert "no active project" in (relative.failure_reason or "")
        assert healthy is not None
        assert healthy.status == ThreadStatus.RECONCILING.value
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_redispatch_dedups_repeated_circuit_open_failures(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db_file = tmp_path / "redispatch-dedup.db"
    await close_db()
    await init_db(str(db_file))
    try:
        thread_count = 2 * _REDISPATCH_LOG_EVERY_N + 2  # 12 for N=5
        thread_ids = [f"redispatch-dedup-{i}" for i in range(thread_count)]
        session_factory = get_session_factory()
        async with session_factory() as session:
            for thread_id in thread_ids:
                await _create_reconciling_thread_with_receipt(
                    session,
                    thread_id=thread_id,
                    team_preset="mock-success-single",
                    metadata=json.dumps(_current_metadata(str(tmp_path))),
                )
            await session.commit()

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        spawner.replace_process(None)
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=1, recovery_timeout=999.0
        )
        circuit_breaker.force_open()
        worker_contacts: list[float] = []

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9", timeout=0.2
        ) as client:
            with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
                await redispatch_reconciling_threads(
                    client,
                    circuit_breaker,
                    spawner,
                    record_worker_contact=worker_contacts.append,
                )

        assert worker_contacts == []

        circuit_open_warnings = [
            r
            for r in caplog.records
            if r.name == _LOGGER_NAME
            and r.levelno == logging.WARNING
            and "Circuit breaker open" in r.getMessage()
        ]
        # occurrence 1 and every Nth (5, 10) out of 12 -> exactly 3 full lines,
        # never one per thread.
        assert len(circuit_open_warnings) == 3

        summaries = [
            r
            for r in caplog.records
            if r.name == _LOGGER_NAME
            and r.levelno == logging.INFO
            and "Re-dispatch failure ladder" in r.getMessage()
        ]
        assert len(summaries) == 1
        summary_message = summaries[0].getMessage()
        assert f"{thread_count} occurrences" in summary_message
        # Every stuck thread is named in the summary, including the ones whose
        # own per-occurrence WARNING was gapped/suppressed by the ladder.
        for thread_id in thread_ids:
            assert thread_id in summary_message
    finally:
        await close_db()


@pytest.mark.asyncio
async def test_redispatch_logs_once_for_a_single_failure_with_no_summary(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A lone failure logs in full with no batch-end summary noise."""
    db_file = tmp_path / "redispatch-single.db"
    await close_db()
    await init_db(str(db_file))
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await _create_reconciling_thread_with_receipt(
                session,
                thread_id="single-failure",
                team_preset="mock-success-single",
                metadata=json.dumps(_current_metadata(str(tmp_path))),
            )
            await session.commit()

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        spawner.replace_process(None)
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=1, recovery_timeout=999.0
        )
        circuit_breaker.force_open()
        worker_contacts: list[float] = []

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:9", timeout=0.2
        ) as client:
            with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
                await redispatch_reconciling_threads(
                    client,
                    circuit_breaker,
                    spawner,
                    record_worker_contact=worker_contacts.append,
                )

        assert worker_contacts == []

        circuit_open_warnings = [
            r
            for r in caplog.records
            if r.name == _LOGGER_NAME
            and r.levelno == logging.WARNING
            and "Circuit breaker open" in r.getMessage()
        ]
        assert len(circuit_open_warnings) == 1

        summaries = [
            r
            for r in caplog.records
            if r.name == _LOGGER_NAME
            and r.levelno == logging.INFO
            and "Re-dispatch failure ladder" in r.getMessage()
        ]
        assert summaries == []
    finally:
        await close_db()
