"""Operational tests for gateway process-supervision helpers."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import httpx
import pytest
from httpx import ASGITransport
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.diagnostics import classify_missing_ws_thread
from ...control.health import build_sqlite_fallback_diagnostics
from ...control.worker_management import (
    LazyWorkerSpawner,
    WorkerState,
    WorkerWatchdog,
    _build_worker_restart_detail,
    _worker_stderr_log_path,
)
from ...database.models import ThreadExecutionStateModel
from ..websocket import WebSocketCommandRejectedError
from ..ws_dispatch import create_dispatch_message_handler
from .conftest import make_app

if TYPE_CHECKING:
    from pathlib import Path


def test_build_worker_restart_detail_includes_log_tail(tmp_path: Path) -> None:
    """Crash detail should include both stderr tail text and the log path."""
    case_dir = tmp_path / "api-test-app"
    case_dir.mkdir(parents=True, exist_ok=True)
    stderr_log = case_dir / "worker.stderr.log"
    stderr_log.write_text(
        "bootstrap ok\ntraceback line one\ntraceback line two\n",
        encoding="utf-8",
    )

    detail = _build_worker_restart_detail(
        returncode=17,
        stderr_log_path=stderr_log,
    )

    assert "returncode=17" in detail
    assert "stderr_tail=bootstrap ok traceback line one traceback line two" in detail
    assert f"stderr_log={stderr_log}" in detail


def test_worker_stderr_log_path_is_repo_local() -> None:
    """Gateway-managed worker stderr logs should live under .vault/runtime."""
    log_path = _worker_stderr_log_path(8123)

    assert log_path.name == "worker-autospawn-8123.stderr.log"
    assert log_path.parent.name == "runtime"
    assert ".vault" in str(log_path)
    assert ".vaultspec" not in str(log_path)


def test_lazy_worker_spawner_avoids_stderr_log_path_when_auto_spawn_disabled() -> None:
    """Disabled auto-spawn should not require a runtime log path at startup."""
    spawner = LazyWorkerSpawner(
        worker_url="http://worker:8001",
        worker_port=8001,
        auto_spawn=False,
    )

    assert spawner.stderr_log_path is None


def test_worker_watchdog_keeps_stderr_log_path_null_when_auto_spawn_disabled() -> None:
    """Watchdog startup should preserve the no-autospawn diagnostic contract."""
    spawner = LazyWorkerSpawner(
        worker_url="http://worker:8001",
        worker_port=8001,
        auto_spawn=False,
    )
    app_state = SimpleNamespace()
    worker_state = WorkerState()

    WorkerWatchdog(
        spawner=spawner,
        circuit_breaker=WorkerCircuitBreaker(
            failure_threshold=1,
            recovery_timeout=1.0,
        ),
        worker_state=worker_state,
        app_state=app_state,
    )

    assert worker_state.worker_stderr_log_path is None


@pytest.mark.asyncio
async def test_api_health_reports_worker_stderr_log_path(
    session_factory,
    checkpointer,
) -> None:
    """GET /api/health should expose the diagnostic stderr log location."""
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    ws = WorkerState(
        worker_status="up",
        worker_last_restart_detail="returncode=9; stderr_log=example.log",
        worker_restart_count=1,
        worker_last_restart_reason="process_exited",
        worker_stderr_log_path=str(_worker_stderr_log_path(8001)),
    )
    app.state.worker_state = ws

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["worker_stderr_log_path"].endswith("worker-autospawn-8001.stderr.log")
    assert body["worker_last_restart_detail"] == "returncode=9; stderr_log=example.log"


def test_build_sqlite_fallback_diagnostics_reports_wal_state(tmp_path: Path) -> None:
    """SQLite fallback diagnostics should inspect real file-backed journal mode."""
    case_dir = tmp_path / "api-test-sqlite-health"
    case_dir.mkdir(parents=True, exist_ok=True)
    db_path = case_dir / "health.db"
    checkpoint_path = case_dir / "checkpoints.db"
    for path in (db_path, checkpoint_path):
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        finally:
            conn.close()

    diagnostics = build_sqlite_fallback_diagnostics(
        database_backend="sqlite",
        checkpoint_backend="sqlite",
        database_path=db_path,
        checkpoint_path=checkpoint_path,
        busy_timeout_ms=5000,
    )

    assert diagnostics is not None
    assert diagnostics["active"] is True
    assert diagnostics["production_certifying"] is False
    assert diagnostics["busy_timeout_ms"] == 5000
    db_diag = cast("dict[str, object]", diagnostics["database"])
    assert db_diag["wal_enabled"] is True
    cp_diag = cast("dict[str, object]", diagnostics["checkpoint"])
    assert cp_diag["wal_enabled"] is True


@pytest.mark.asyncio
async def test_api_health_reports_sqlite_fallback_diagnostics(
    session_factory,
    checkpointer,
) -> None:
    """GET /api/health should expose explicit SQLite fallback diagnostics."""
    app, _aggregator, _worker, _checkpointer = make_app(session_factory, checkpointer)
    app.state.worker_status = "up"
    app.state.sqlite_fallback_diagnostics = {
        "active": True,
        "busy_timeout_ms": 5000,
        "production_certifying": False,
        "limitations": ["sqlite_fallback_not_production_certifying"],
        "database": {"path": "test.db", "wal_enabled": True, "journal_mode": "wal"},
    }

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sqlite_fallback"]["active"] is True
    assert body["sqlite_fallback"]["production_certifying"] is False
    assert body["sqlite_fallback"]["database"]["journal_mode"] == "wal"


@pytest.mark.asyncio
async def test_api_health_degrades_when_checkpointer_backend_is_unusable(
    session_factory,
    tmp_path: Path,
) -> None:
    """GET /api/health must fail closed when the checkpointer cannot be probed."""
    checkpoints_file = tmp_path / "closed-health-checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as saver:
        closed_checkpointer = saver

    app, _aggregator, _worker, _checkpointer = make_app(
        session_factory,
        closed_checkpointer,
    )

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["checkpoint"]["status"] == "error"
    assert body["checks"]["checkpoint"]["detail"] == "checkpoint probe failed"


@pytest.mark.asyncio
async def test_classify_missing_ws_thread_reports_not_found(
    session_factory,
    checkpointer,
) -> None:
    """Missing thread with no backend residue should return THREAD_NOT_FOUND."""
    result = await classify_missing_ws_thread(
        thread_id="missing-thread",
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    assert result.code == "THREAD_NOT_FOUND"
    assert result.metadata == {
        "execution_state_present": False,
        "checkpoint_present": False,
        "checkpoint_unverified": False,
    }


@pytest.mark.asyncio
async def test_classify_missing_ws_thread_reports_state_drift(
    session_factory,
    checkpointer,
) -> None:
    """Missing thread with durable checkpoint residue should report drift."""
    await checkpointer.setup()
    checkpoint = empty_checkpoint()
    checkpoint["id"] = "cp-123"
    await checkpointer.aput(
        {"configurable": {"thread_id": "drift-thread", "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )

    result = await classify_missing_ws_thread(
        thread_id="drift-thread",
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    assert result.code == "THREAD_STATE_DRIFT"
    assert result.metadata is not None
    assert result.metadata["execution_state_present"] is False
    assert result.metadata["checkpoint_present"] is True


@pytest.mark.asyncio
async def test_classify_missing_ws_thread_prefers_unverified_over_execution_state(
    session_factory,
    tmp_path: Path,
) -> None:
    """Checkpoint uncertainty must outrank orphaned execution-state residue."""
    case_dir = tmp_path / "api-test-app"
    case_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_file = case_dir / "closed-checkpoints.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        pass

    async with session_factory() as session:
        session.add(
            ThreadExecutionStateModel(
                thread_id="unverified-thread",
                checkpoint_id="cp-orphaned",
                parent_checkpoint_id=None,
                recovery_epoch=0,
                task_count=0,
                interrupt_count=0,
                next_nodes_json="[]",
                interrupt_types_json="[]",
                tasks_json="[]",
                degraded_reasons_json="[]",
            )
        )
        await session.commit()

    result = await classify_missing_ws_thread(
        thread_id="unverified-thread",
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    assert result.code == "THREAD_STATE_UNVERIFIED"
    assert result.metadata == {
        "execution_state_present": True,
        "checkpoint_present": False,
        "checkpoint_unverified": True,
    }


@pytest.mark.asyncio
async def test_dispatch_message_handler_rejects_missing_thread(
    session_factory,
    checkpointer,
) -> None:
    """WS dispatch handler should reject missing threads before worker dispatch."""
    app, _aggregator, worker, _checkpointer = make_app(session_factory, checkpointer)
    handler = create_dispatch_message_handler(
        worker.client,
        session_factory,
        checkpointer,
        app.state.circuit_breaker,
        app.state.worker_spawner,
        None,
        app.state,
    )

    with pytest.raises(WebSocketCommandRejectedError) as excinfo:
        await handler("missing-thread", "hello", None)

    rejection = excinfo.value
    assert rejection.code == "THREAD_NOT_FOUND"
    assert worker.dispatches == []


@pytest.mark.asyncio
async def test_dispatch_message_handler_prefers_unverified_over_not_found(
    session_factory,
    tmp_path: Path,
) -> None:
    """Send-message WS rejection must preserve checkpoint-unverified classification."""
    case_dir = tmp_path / "api-test-app"
    case_dir.mkdir(parents=True, exist_ok=True)
    checkpoints_file = case_dir / "closed-checkpoints.db"

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        pass

    async with session_factory() as session:
        session.add(
            ThreadExecutionStateModel(
                thread_id="unverified-thread",
                checkpoint_id="cp-orphaned",
                parent_checkpoint_id=None,
                recovery_epoch=0,
                task_count=0,
                interrupt_count=0,
                next_nodes_json="[]",
                interrupt_types_json="[]",
                tasks_json="[]",
                degraded_reasons_json="[]",
            )
        )
        await session.commit()

    app, _aggregator, worker, _checkpointer = make_app(session_factory, checkpointer)
    handler = create_dispatch_message_handler(
        worker.client,
        session_factory,
        checkpointer,
        app.state.circuit_breaker,
        app.state.worker_spawner,
        None,
        app.state,
    )

    with pytest.raises(WebSocketCommandRejectedError) as excinfo:
        await handler("unverified-thread", "hello", None)

    rejection = excinfo.value
    assert rejection.code == "THREAD_STATE_UNVERIFIED"
    assert rejection.metadata == {
        "execution_state_present": True,
        "checkpoint_present": False,
        "checkpoint_unverified": True,
    }
