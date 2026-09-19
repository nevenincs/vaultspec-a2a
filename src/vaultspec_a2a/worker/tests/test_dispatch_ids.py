"""Real worker admission proofs for stable dispatch identities."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest
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


@pytest.mark.parametrize("action", ["ingest", "resume"])
def test_concurrent_identical_capacity_dispatches_replay_one_acceptance(
    tmp_path: Path,
    action: str,
) -> None:
    checkpoint_path = tmp_path / f"concurrent-{action}-checkpoints.db"

    @asynccontextmanager
    async def worker_lifespan(app: FastAPI):
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            bridge = WorkerBridge("http://127.0.0.1:1", f"concurrent-{action}")
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
    authority = resolve_execution_authority(current_execution_metadata(tmp_path))
    dispatch = DispatchRequest(
        dispatch_id=f"concurrent-identical-{action}",
        action=cast("Any", action),
        thread_id=f"concurrent-{action}-thread",
        workspace_root=str(tmp_path),
        content="run once" if action == "ingest" else None,
        option_id="allow_once" if action == "resume" else None,
        recursion_limit=25,
        model_assignment=authority.model_assignment,
    )
    payload = dispatch.model_dump(mode="json")

    with TestClient(app) as client:
        portal = client.portal
        assert portal is not None
        admission_lock = app.state.executor._ingest_lock
        portal.call(admission_lock.acquire)
        try:
            with ThreadPoolExecutor(max_workers=2) as requests:
                responses = [
                    requests.submit(client.post, "/dispatch", json=payload)
                    for _ in range(2)
                ]
                deadline = time.monotonic() + 5
                waiters = 0
                while time.monotonic() < deadline:
                    waiters = portal.call(
                        lambda: len(getattr(admission_lock, "_waiters", ()) or ())
                    )
                    if waiters == 2:
                        break
                    time.sleep(0.01)
                assert waiters == 2
                portal.call(admission_lock.release)
                resolved = [future.result(timeout=5) for future in responses]
        finally:
            if admission_lock.locked():
                portal.call(admission_lock.release)

        assert [response.status_code for response in resolved] == [200, 200]
        assert (
            resolved[0].json()
            == resolved[1].json()
            == {
                "status": "dispatched",
                "thread_id": dispatch.thread_id,
            }
        )
        assert len(app.state.dispatch_ids) == 1
        deadline = time.monotonic() + 5
        while (
            app.state.executor.active_ingest_count != 0 and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        # Only the request that synchronously admitted this ID generated a
        # capacity owner and crossed into task scheduling.
        assert app.state.executor._next_capacity_generation == 1
        assert app.state.executor.active_ingest_count == 0


def test_concurrent_distinct_same_thread_dispatch_retains_capacity_refusal(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "concurrent-distinct-checkpoints.db"

    @asynccontextmanager
    async def worker_lifespan(app: FastAPI):
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            await saver.setup()
            bridge = WorkerBridge("http://127.0.0.1:1", "concurrent-distinct")
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
    authority = resolve_execution_authority(current_execution_metadata(tmp_path))

    def request(dispatch_id: str) -> DispatchRequest:
        return DispatchRequest(
            dispatch_id=dispatch_id,
            action="ingest",
            thread_id="concurrent-distinct-thread",
            team_preset="mock-success-single",
            workspace_root=str(tmp_path),
            content="only one ID may enter",
            recursion_limit=25,
            model_assignment=authority.model_assignment,
        )

    with TestClient(app) as client:
        portal = client.portal
        assert portal is not None
        admission_lock = app.state.executor._ingest_lock
        portal.call(admission_lock.acquire)
        try:
            with ThreadPoolExecutor(max_workers=2) as requests:
                responses = [
                    requests.submit(
                        client.post,
                        "/dispatch",
                        json=request(dispatch_id).model_dump(mode="json"),
                    )
                    for dispatch_id in ("distinct-a", "distinct-b")
                ]
                deadline = time.monotonic() + 5
                waiters = 0
                while time.monotonic() < deadline:
                    waiters = portal.call(
                        lambda: len(getattr(admission_lock, "_waiters", ()) or ())
                    )
                    if waiters == 2:
                        break
                    time.sleep(0.01)
                assert waiters == 2
                portal.call(admission_lock.release)
                resolved = [future.result(timeout=5) for future in responses]
        finally:
            if admission_lock.locked():
                portal.call(admission_lock.release)

        assert sorted(response.status_code for response in resolved) == [200, 429]
        refusal = next(response for response in resolved if response.status_code == 429)
        assert refusal.json() == {
            "detail": "Worker at capacity — too many concurrent threads"
        }
        assert len(app.state.dispatch_ids) == 1


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
