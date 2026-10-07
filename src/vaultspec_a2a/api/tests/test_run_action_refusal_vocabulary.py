"""One dispatch outcome, one served status, whichever run verb met it.

A follow-up turn and a permission answer both reach the worker through the same
dispatch, so a worker that is holding the run's slot, or that has no room at
all, must read the same way on both. It did not: the permission verb had no
status for a busy worker and answered 500, and it called a saturated worker a
bad gateway while the follow-up verb called the same refusal a retry.

The refusals here are the ones the production worker really composes. The
gateway's worker client is pointed at ``create_worker_app()`` driven by a real
``Executor`` whose capacity is reserved up front, so the 409 and the 429 the
gateway classifies are the worker's own answers rather than statuses written
into a test.
"""

from __future__ import annotations

import itertools
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
from httpx import ASGITransport

from ...control.config import settings
from ...domain_config import domain_config
from ...testing import DEFAULT_TEAM_PRESET, async_catalog_run_fields
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from .conftest import make_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type SessionFactory = async_sessionmaker[AsyncSession]

_RUN_SEQ = itertools.count(1)


@asynccontextmanager
async def _worker_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """No-op: ASGITransport never runs the real lifespan protocol."""
    yield


@asynccontextmanager
async def _saturated_worker(
    app: FastAPI, checkpointer: AsyncSqliteSaver, *, held_threads: list[str]
) -> AsyncGenerator[Executor]:
    """Serve the production worker app with *held_threads* already reserved.

    The reservations are taken through the executor's own public capacity seam,
    which is the same one the dispatch endpoint takes, so the worker refuses for
    exactly the reason it would refuse a real concurrent turn.
    """
    bridge = WorkerBridge("http://control", "run-action-refusal-test")
    executor = Executor(checkpointer, bridge)
    worker_app = create_worker_app(lifespan=_worker_lifespan)
    worker_app.state.executor = executor
    try:
        for thread_id in held_threads:
            reservation, _reason = await executor.reserve_dispatch_capacity(thread_id)
            assert reservation is not None
        async with (
            httpx.AsyncClient(
                transport=ASGITransport(app=worker_app),
                base_url="http://worker",
                headers=(
                    {"Authorization": f"Bearer {settings.internal_token}"}
                    if settings.internal_token is not None
                    else None
                ),
            ) as worker_client,
            anyio.create_task_group() as tasks,
        ):
            worker_app.state.task_group = tasks
            app.state.worker_client = worker_client
            yield executor
            tasks.cancel_scope.cancel()
    finally:
        await executor.shutdown()
        await bridge.close()


async def _start_run(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/v1/runs",
        json={
            "run_id": f"refusal-vocab-{next(_RUN_SEQ):02d}",
            "team_preset": DEFAULT_TEAM_PRESET,
            "message": "start the turn",
            **await async_catalog_run_fields(client),
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def _seed_permission(
    session_factory: SessionFactory, *, thread_id: str, request_id: str
) -> None:
    """Record a real pending permission request against a real run."""
    from ...database.permission_repository import record_permission_request

    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="bash",
            description="Allow action?",
            allowed_options=[
                {
                    "option_id": "allow_once",
                    "name": "Allow once",
                    "kind": "allow_once",
                }
            ],
            tool_call="bash",
        )
        await session.commit()


@pytest.mark.asyncio
async def test_a_permission_answer_to_a_busy_run_is_a_conflict_not_a_server_fault(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """A worker holding the run's slot is a conflict about that one run.

    Nothing is broken: the turn the answer was meant for is being executed, and
    the accepted answer is retained for the retry the recovery coordinator
    schedules. Reporting that as an internal gateway failure told a caller to
    treat a healthy, busy gateway as a fault.
    """
    app, _agg, _stub, _cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        run_id = await _start_run(client)
        request_id = f"{run_id}:busy"
        await _seed_permission(session_factory, thread_id=run_id, request_id=request_id)

        async with _saturated_worker(app, checkpointer, held_threads=[run_id]):
            refused = await client.post(
                f"/v1/runs/{run_id}/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "run_busy"
    assert detail["message"]


@pytest.mark.asyncio
async def test_a_permission_answer_to_a_full_worker_asks_the_caller_to_retry(
    session_factory: SessionFactory, checkpointer: AsyncSqliteSaver
) -> None:
    """Capacity is about the service, and both verbs call it the same thing.

    The follow-up verb already served 503 for a saturated worker. The permission
    verb served 502, which says the far side is broken rather than busy, and a
    caller cannot tell from it that retrying is the right move.
    """
    app, _agg, _stub, _cp = make_app(session_factory, checkpointer)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://gateway", timeout=30.0
    ) as client:
        run_id = await _start_run(client)
        request_id = f"{run_id}:full"
        await _seed_permission(session_factory, thread_id=run_id, request_id=request_id)

        held = [
            f"holder-{index}" for index in range(domain_config.max_concurrent_threads)
        ]
        async with _saturated_worker(app, checkpointer, held_threads=held):
            refused = await client.post(
                f"/v1/runs/{run_id}/permissions/{request_id}/respond",
                json={"option_id": "allow_once"},
            )

    assert refused.status_code == 503, refused.text
    # A capacity refusal keeps a plain sentence: it is about the service, so
    # there is no run-scoped condition for a typed code to name.
    assert isinstance(refused.json()["detail"], str)
