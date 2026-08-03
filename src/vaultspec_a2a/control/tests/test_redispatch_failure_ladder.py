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
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.dispatch import (
    _REDISPATCH_LOG_EVERY_N,
    redispatch_reconciling_threads,
)
from ...control.worker_management import LazyWorkerSpawner
from ...database import create_thread, get_thread
from ...database.session import close_db, get_session_factory, init_db
from ...thread.enums import ThreadStatus

_LOGGER_NAME = "vaultspec_a2a.control.dispatch"


@pytest.mark.asyncio
async def test_invalid_frozen_selection_fails_only_its_thread_and_sweep_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A corrupt modern authority cannot prevent later restart work from running."""
    db_file = tmp_path / "redispatch-invalid-frozen.db"
    await close_db()
    await init_db(str(db_file))
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            # list_threads orders newest first, so create the valid thread before
            # the corrupt one to prove a malformed first item does not abort.
            await create_thread(
                session,
                thread_id="valid-after-corrupt",
                status=ThreadStatus.RECONCILING,
                team_preset="mock-success-single",
                metadata=json.dumps({"workspace_root": str(tmp_path)}),
            )
            await create_thread(
                session,
                thread_id="corrupt-modern-freeze",
                status=ThreadStatus.RECONCILING,
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
                    record_worker_contact=lambda _when: None,
                )

        async with session_factory() as session:
            corrupt = await get_thread(session, "corrupt-modern-freeze")
            valid = await get_thread(session, "valid-after-corrupt")
        assert corrupt is not None
        assert corrupt.status == ThreadStatus.FAILED.value
        assert (
            corrupt.failure_reason == "persisted provider catalog selection is invalid"
        )
        assert valid is not None
        assert valid.status == ThreadStatus.RECONCILING.value
        assert any(
            "Refusing invalid frozen assignment" in record.getMessage()
            for record in caplog.records
        )
        assert any(
            "Circuit breaker open" in record.getMessage()
            and "valid-after-corrupt" in record.getMessage()
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
            await create_thread(
                session,
                thread_id="healthy-after-projectless",
                status=ThreadStatus.RECONCILING,
                team_preset="mock-success-single",
                metadata=json.dumps({"workspace_root": str(tmp_path)}),
            )
            await create_thread(
                session,
                thread_id="projectless",
                status=ThreadStatus.RECONCILING,
                team_preset="mock-success-single",
                metadata=json.dumps({"feature_tag": "no-project-here"}),
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
                await create_thread(
                    session,
                    thread_id=thread_id,
                    status=ThreadStatus.RECONCILING,
                    team_preset="mock-success-single",
                    metadata=json.dumps({"workspace_root": str(tmp_path)}),
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
            await create_thread(
                session,
                status=ThreadStatus.RECONCILING,
                team_preset="mock-success-single",
                metadata=json.dumps({"workspace_root": str(tmp_path)}),
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
