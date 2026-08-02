"""Real concurrent permission requests against the leased service."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.permission_service import (
    permission_response_action_key,
    respond_to_permission,
)
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_thread,
    get_control_action_by_idempotency_key,
    record_permission_request,
)
from ...database.models import Base
from ...streaming.aggregator import EventAggregator
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus

if TYPE_CHECKING:
    from pathlib import Path

_OPTIONS: list[dict[str, object]] = [
    {"optionId": "allow_once", "name": "Allow once"},
    {"optionId": "reject_once", "name": "Reject once"},
]


async def _run_case(runtime_dir: Path, bodies: list[tuple[str, str | None]]):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{runtime_dir / 'permission-leases.db'}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as session:
        thread = await create_thread(session, status=ThreadStatus.INPUT_REQUIRED.value)
        request_id = f"{thread.id}:permission"
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread.id,
            pause_reason_type="tool_permission_request",
            description="Allow the operation?",
            allowed_options=_OPTIONS,
        )
        await session.commit()
        thread_id = thread.id

    start = asyncio.Event()

    async def respond(index: int, option_id: str, notes: str | None):
        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
        )
        breaker = WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=1)
        async with (
            sessions() as session,
            httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client,
        ):
            await start.wait()
            return await respond_to_permission(
                session,
                request_id=request_id,
                option_id=option_id,
                notes=notes,
                idempotency_key=f"client-retry-{index}",
                aggregator=EventAggregator(),
                circuit_breaker=breaker,
                worker_spawner=spawner,
                worker_client=client,
                recursion_limit=25,
                trace_headers=None,
            )

    tasks = [
        asyncio.create_task(respond(index, option, notes))
        for index, (option, notes) in enumerate(bodies)
    ]
    start.set()
    results = await asyncio.gather(*tasks)
    async with sessions() as session:
        action = await get_control_action_by_idempotency_key(
            session,
            thread_id=thread_id,
            idempotency_key=permission_response_action_key(request_id),
        )
    await engine.dispose()
    return results, action


@pytest.mark.asyncio
async def test_identical_concurrent_retries_share_one_request_lease(
    tmp_path: Path,
) -> None:
    results, action = await _run_case(
        tmp_path,
        [("allow_once", "same"), ("allow_once", "same")],
    )
    assert action is not None
    assert {result.action_id for result in results} == {action.id}
    assert (
        sum(result.failure_type is FailureType.UNREACHABLE for result in results) == 1
    )
    assert sum(result.accepted for result in results) == 1


@pytest.mark.asyncio
async def test_competing_concurrent_bodies_conflict_without_second_dispatch(
    tmp_path: Path,
) -> None:
    results, action = await _run_case(
        tmp_path,
        [("allow_once", "first"), ("reject_once", "second")],
    )
    assert action is not None
    assert (
        sum(result.failure_type is FailureType.UNREACHABLE for result in results) == 1
    )
    conflicts = [
        result for result in results if result.failure_type is FailureType.CONFLICT
    ]
    assert len(conflicts) == 1
    assert conflicts[0].error_status_code == 409
