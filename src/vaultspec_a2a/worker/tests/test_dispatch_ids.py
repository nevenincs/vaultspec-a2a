"""Real worker admission proofs for stable dispatch identities."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import anyio
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...control.execution_authority import resolve_execution_authority
from ...control.tests._catalog_authority import current_execution_metadata
from ...domain_config import domain_config
from ...ipc.schemas import DispatchRequest
from ..app import create_worker_app
from ..dispatch_ids import DispatchIdAdmission
from ..executor import Executor
from ..ipc import WorkerBridge

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import FastAPI


def test_dispatch_id_admission_is_fifo_bounded() -> None:
    admission = DispatchIdAdmission(capacity=2)

    assert admission.admit("one") is True
    assert admission.admit("one") is False
    assert admission.admit("two") is True
    assert admission.admit("three") is True
    assert len(admission) == 2
    assert admission.admit("one") is True


def test_duplicate_worker_dispatch_schedules_one_real_executor_task(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "duplicate-worker-checkpoints.db"

    @asynccontextmanager
    async def worker_lifespan(app: FastAPI):
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            # A closed loopback port gives the real bridge a definite delivery
            # failure. The resulting terminal event stays buffered and therefore
            # provides an observable count of real Executor applications.
            bridge = WorkerBridge("http://127.0.0.1:1", "dedupe-test")
            executor = Executor(saver, bridge)
            app.state.executor = executor
            app.state.bridge = bridge
            async with anyio.create_task_group() as tasks:
                app.state.task_group = tasks
                yield
                tasks.cancel_scope.cancel()
            await executor.shutdown()
            await bridge.close()

    app = create_worker_app(lifespan=worker_lifespan)
    dispatch = DispatchRequest(
        dispatch_id="stable-cancel-dispatch",
        action="cancel",
        thread_id="duplicate-worker-thread",
        recursion_limit=25,
    )
    with TestClient(app) as client:
        first = client.post("/dispatch", json=dispatch.model_dump(mode="json"))
        duplicate = client.post("/dispatch", json=dispatch.model_dump(mode="json"))
        deadline = time.monotonic() + 5
        bridge: WorkerBridge = app.state.bridge
        buffered = cast("list[dict[str, Any]]", getattr(bridge, "_event_buffer", []))
        while len(buffered) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert first.status_code == 200
        assert duplicate.status_code == 200
        assert first.json() == duplicate.json()
        terminal_events: list[dict[str, Any]] = [
            item
            for item in buffered
            if item["payload"].get("event_type") == "thread_terminal"
        ]
        assert len(terminal_events) == 1


def test_dispatch_reserves_capacity_before_scheduling_or_checkpoint_read(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "capacity-worker-checkpoints.db"

    @asynccontextmanager
    async def worker_lifespan(app: FastAPI):
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            bridge = WorkerBridge("http://127.0.0.1:1", "capacity-test")
            executor = Executor(saver, bridge)
            for index in range(domain_config.max_concurrent_threads):
                assert await executor.reserve_dispatch_capacity(f"held-{index}")
            app.state.executor = executor
            app.state.bridge = bridge
            async with anyio.create_task_group() as tasks:
                app.state.task_group = tasks
                yield
                tasks.cancel_scope.cancel()
            await executor.shutdown()
            await bridge.close()

    app = create_worker_app(lifespan=worker_lifespan)
    authority = resolve_execution_authority(current_execution_metadata(tmp_path))
    dispatch = DispatchRequest(
        dispatch_id="capacity-refused-before-schedule",
        action="ingest",
        thread_id="over-capacity",
        team_preset="mock-success-single",
        workspace_root=str(tmp_path),
        recursion_limit=25,
        model_assignment=authority.model_assignment,
    )
    with TestClient(app) as client:
        response = client.post("/dispatch", json=dispatch.model_dump(mode="json"))

        assert response.status_code == 429
        assert len(app.state.dispatch_ids) == 0
        assert app.state.executor.active_ingest_count == (
            domain_config.max_concurrent_threads
        )
