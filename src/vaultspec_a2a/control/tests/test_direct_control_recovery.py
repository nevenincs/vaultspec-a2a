"""Crash-recovery proofs for the active-project gate on redriven dispatches.

Real file-backed SQLite and the real worker HTTP application: the recovery pass
reads the durable control-action rows it would read at gateway start, and the
worker's own dispatch-ID admission set is what proves whether a dispatch was
actually sent. No service, repository, or transport seam is replaced, so a
refusal here is a refusal on the path a restart takes.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...control.action_lease import claim_control_action
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.direct_control_recovery import redrive_direct_control_actions
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_thread,
    get_control_action_by_idempotency_key,
    record_permission_request,
    record_permission_response_submission,
)
from ...database.models import Base
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.idempotency import default_cancel_key
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from pathlib import Path

    from fastapi import FastAPI

_MESSAGE_KEY = "recovery-message-key"
_CANCEL_THREAD = "recovery-cancel"
_MESSAGE_THREAD = "recovery-message"
_PERMISSION_THREAD = "recovery-permission"
_PERMISSION_REQUEST = f"{_PERMISSION_THREAD}:permission-1"
_PERMISSION_KEY = f"permission-response:{_PERMISSION_REQUEST}"


@pytest_asyncio.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'direct-control-recovery.db'}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@asynccontextmanager
async def _worker_runtime(
    checkpoint_path: Path,
) -> AsyncGenerator[tuple[httpx.AsyncClient, FastAPI]]:
    """Run the real worker app so its admission set records what was sent."""
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        bridge = WorkerBridge("http://127.0.0.1:1", "direct-control-recovery-test")
        executor = Executor(saver, bridge)
        app = create_worker_app()
        app.state.executor = executor
        async with anyio.create_task_group() as tasks:
            app.state.task_group = tasks
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://worker",
            ) as client:
                yield client, app
            tasks.cancel_scope.cancel()
        await executor.shutdown()
        await bridge.close()


def _circuit_breaker() -> WorkerCircuitBreaker:
    return WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)


def _spawner() -> LazyWorkerSpawner:
    spawner = LazyWorkerSpawner(
        worker_url="http://worker",
        worker_port=8001,
        auto_spawn=False,
    )
    spawner.replace_process(None)
    return spawner


async def _seed_unapplied_actions(
    sessions: async_sessionmaker[AsyncSession],
    *,
    metadata: str | None,
) -> dict[str, str]:
    """Seed one thread per recoverable action with an expired, unapplied lease.

    *metadata* is the stored thread metadata every seeded thread carries, which
    is the single variable under test: the same three actions are seeded either
    way, so any difference in the recovery verdict is attributable to the active
    project alone.
    """
    expired = datetime.now(UTC) - timedelta(minutes=5)
    async with sessions() as db:
        for thread_id, status in (
            (_MESSAGE_THREAD, ThreadStatus.RUNNING),
            (_CANCEL_THREAD, ThreadStatus.CANCELLING),
            (_PERMISSION_THREAD, ThreadStatus.INPUT_REQUIRED),
        ):
            await create_thread(
                db,
                thread_id=thread_id,
                status=status,
                metadata=metadata,
            )
        await record_permission_request(
            db,
            request_id=_PERMISSION_REQUEST,
            thread_id=_PERMISSION_THREAD,
            pause_reason_type="bash",
            description="Allow?",
            allowed_options=[
                {"option_id": "allow_once", "name": "Allow once", "kind": "allow_once"}
            ],
            tool_call="bash",
        )
        await record_permission_response_submission(
            db,
            request_id=_PERMISSION_REQUEST,
            option_id="allow_once",
            idempotency_key="permission-client-key",
        )
        dispatch_ids = {
            _MESSAGE_THREAD: (
                await claim_control_action(
                    db,
                    thread_id=_MESSAGE_THREAD,
                    action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                    idempotency_key=_MESSAGE_KEY,
                    payload={"content": "continue", "agent_id": "supervisor"},
                    now=expired,
                    lease_ttl=timedelta(seconds=1),
                )
            ).dispatch_id,
            _CANCEL_THREAD: (
                await claim_control_action(
                    db,
                    thread_id=_CANCEL_THREAD,
                    action_type=ControlActionType.CANCEL,
                    idempotency_key=default_cancel_key(_CANCEL_THREAD),
                    payload={"cancel": True},
                    now=expired,
                    lease_ttl=timedelta(seconds=1),
                )
            ).dispatch_id,
            _PERMISSION_THREAD: (
                await claim_control_action(
                    db,
                    thread_id=_PERMISSION_THREAD,
                    action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
                    request_id=_PERMISSION_REQUEST,
                    idempotency_key=_PERMISSION_KEY,
                    payload={"option_id": "allow_once", "notes": None},
                    now=expired,
                    lease_ttl=timedelta(seconds=1),
                )
            ).dispatch_id,
        }
        await db.commit()
    return dispatch_ids


@pytest.mark.asyncio
async def test_recovery_refuses_a_thread_whose_metadata_names_no_project(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A stored run with no active project is refused before it is dispatched.

    Both actions that re-enter graph execution - the follow-up and the permission
    resume - need the run sited: the worker that held the project is gone by the
    time recovery runs, so nothing downstream still carries it. Degrading the
    absent project to nothing and dispatching anyway put the refusal at the
    provider seam, after the agent had already been sited in whatever directory
    the worker started in. The cancel is the control: it names no project by
    design and still goes out.
    """
    dispatch_ids = await _seed_unapplied_actions(session_factory, metadata=None)

    async with _worker_runtime(tmp_path / "refused-checkpoints.db") as (
        worker_client,
        worker_app,
    ):
        summary = await redrive_direct_control_actions(
            session_factory,
            worker_client=worker_client,
            circuit_breaker=_circuit_breaker(),
            worker_spawner=_spawner(),
            recursion_limit=25,
            trace_headers=None,
        )

        assert summary.examined == 3
        assert summary.refused == 2
        assert summary.dispatched == 1
        assert summary.conflicted == 0
        # The worker is the authority on what was actually sent.
        admitted = worker_app.state.dispatch_ids
        assert len(admitted) == 1
        assert dispatch_ids[_CANCEL_THREAD] in admitted
        assert dispatch_ids[_MESSAGE_THREAD] not in admitted
        assert dispatch_ids[_PERMISSION_THREAD] not in admitted

    # Refused is not discarded: neither action is marked applied, so the operator
    # intention survives for a run that does name its project.
    async with session_factory() as db:
        message_action = await get_control_action_by_idempotency_key(
            db, thread_id=_MESSAGE_THREAD, idempotency_key=_MESSAGE_KEY
        )
        permission_action = await get_control_action_by_idempotency_key(
            db, thread_id=_PERMISSION_THREAD, idempotency_key=_PERMISSION_KEY
        )
    assert message_action is not None
    assert message_action.applied_at is None
    assert permission_action is not None
    assert permission_action.applied_at is None


@pytest.mark.asyncio
async def test_recovery_dispatches_every_action_when_the_project_is_named(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The gate is the project, not the recovery pass: named, all three go out."""
    workspace = tmp_path / "active-project"
    workspace.mkdir()
    dispatch_ids = await _seed_unapplied_actions(
        session_factory,
        metadata=json.dumps({"workspace_root": str(workspace)}),
    )

    async with _worker_runtime(tmp_path / "dispatched-checkpoints.db") as (
        worker_client,
        worker_app,
    ):
        summary = await redrive_direct_control_actions(
            session_factory,
            worker_client=worker_client,
            circuit_breaker=_circuit_breaker(),
            worker_spawner=_spawner(),
            recursion_limit=25,
            trace_headers=None,
        )

        assert summary.examined == 3
        assert summary.dispatched == 3
        assert summary.refused == 0
        assert summary.conflicted == 0
        admitted = worker_app.state.dispatch_ids
        assert len(admitted) == 3
        assert all(value in admitted for value in dispatch_ids.values())


@pytest.mark.asyncio
async def test_recovery_refuses_a_relative_stored_project_rather_than_crashing(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An unusable stored spelling is an absent project, not an exception.

    A workspace root that cannot be minted into the run's canonical form - a
    relative path here - reaches the dispatch model's validator, which raises.
    Recovery runs at gateway start over every unapplied action, so one such row
    aborting the pass would strand every other action behind it. It is classified
    where it is read instead.
    """
    await _seed_unapplied_actions(
        session_factory,
        metadata=json.dumps({"workspace_root": "relative/project"}),
    )

    async with _worker_runtime(tmp_path / "relative-checkpoints.db") as (
        worker_client,
        worker_app,
    ):
        summary = await redrive_direct_control_actions(
            session_factory,
            worker_client=worker_client,
            circuit_breaker=_circuit_breaker(),
            worker_spawner=_spawner(),
            recursion_limit=25,
            trace_headers=None,
        )

        assert summary.examined == 3
        assert summary.refused == 2
        assert summary.dispatched == 1
        assert len(worker_app.state.dispatch_ids) == 1
