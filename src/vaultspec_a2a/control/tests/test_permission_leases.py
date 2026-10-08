"""Real concurrent permission requests against the leased service."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import pytest

from ...control._permission_response_contract import PermissionInput
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.leased_dispatch import DispatchTransport
from ...control.permission_service import respond_to_permission
from ...database import (
    create_thread,
    get_control_action_by_idempotency_key,
    record_permission_request,
)
from ...testing import (
    adopted_spawner,
    current_execution_metadata,
    park_permission,
    seed_create_action,
)
from ...tests._write_authority import make_test_write_authority
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus
from ...thread.idempotency import permission_response_action_key

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# The park below writes a checkpoint from INSIDE an open, uncommitted
# application transaction, which the one file production serves both stores
# from cannot admit: the saver's write upgrades a read transaction and SQLite
# refuses it outright. The shape is the test's, not production's - the worker
# writes checkpoints on its own connection - so the two stores are separated
# here until the seed commits before it parks.
pytestmark = pytest.mark.separate_checkpoint_store

_OPTIONS: list[dict[str, object]] = [
    {"optionId": "allow_once", "name": "Allow once"},
    {"optionId": "reject_once", "name": "Reject once"},
]


async def _run_case(
    sessions: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    runtime_dir: Path,
    bodies: list[tuple[str, str | None]],
):
    async with sessions() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            status=ThreadStatus.INPUT_REQUIRED.value,
            metadata=current_execution_metadata(runtime_dir),
        )
        request_id = await park_permission(
            checkpointer, thread_id=thread.id, options=_OPTIONS
        )
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread.id,
            pause_reason_type="tool_permission_request",
            description="Allow the operation?",
            allowed_options=_OPTIONS,
        )
        await seed_create_action(session, thread.id, workspace=runtime_dir)
        await session.commit()
        thread_id = thread.id

    start = asyncio.Event()

    async def respond(index: int, option_id: str, notes: str | None):
        spawner = adopted_spawner()
        breaker = WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=1)
        async with (
            sessions() as session,
            httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client,
        ):
            await start.wait()
            return await respond_to_permission(
                session,
                thread_id=thread_id,
                response=PermissionInput(
                    request_id, option_id, f"client-retry-{index}", notes
                ),
                checkpointer=checkpointer,
                transport=DispatchTransport(
                    worker_client=client,
                    circuit_breaker=breaker,
                    worker_spawner=spawner,
                ),
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
    return results, action


@pytest.mark.asyncio
async def test_identical_concurrent_retries_share_one_request_lease(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    tmp_path: Path,
) -> None:
    results, action = await _run_case(
        session_factory,
        checkpointer,
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
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    tmp_path: Path,
) -> None:
    results, action = await _run_case(
        session_factory,
        checkpointer,
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
