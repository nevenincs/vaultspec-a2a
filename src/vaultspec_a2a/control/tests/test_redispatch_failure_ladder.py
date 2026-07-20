"""Re-dispatch failure logging must not re-log identically per stuck thread.

Real DB, real threads in RECONCILING status, a real (forced-open) circuit
breaker - no mocks. Pins the loop-hygiene fix: a large reconciling batch that
all fail the same way (a persistent circuit-open, e.g. after a restart) must
log the failure ladder-style (1st occurrence, every Nth repeat, a batch-end
summary) instead of once per thread.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import httpx
import pytest

from vaultspec_a2a.control.circuit_breaker import WorkerCircuitBreaker
from vaultspec_a2a.control.dispatch import (
    _REDISPATCH_LOG_EVERY_N,
    redispatch_reconciling_threads,
)
from vaultspec_a2a.control.worker_management import LazyWorkerSpawner
from vaultspec_a2a.database import create_thread
from vaultspec_a2a.database.session import close_db, get_session_factory, init_db
from vaultspec_a2a.thread.enums import ThreadStatus

_LOGGER_NAME = "vaultspec_a2a.control.dispatch"


@pytest.mark.asyncio
async def test_redispatch_dedups_repeated_circuit_open_failures(
    tmp_path, caplog: pytest.LogCaptureFixture
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
                    client, circuit_breaker, spawner, SimpleNamespace()
                )

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
    tmp_path, caplog: pytest.LogCaptureFixture
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
                    client, circuit_breaker, spawner, SimpleNamespace()
                )

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
