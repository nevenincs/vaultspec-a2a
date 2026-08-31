"""Durable audit proofs for permission decisions.

Every test here drives the production decision path — ``respond_to_permission``
against a real file-backed SQLite database and the production worker HTTP
application backed by a real ``Executor`` — and then reads the result back
through the production reader ``get_permission_logs_by_thread``. No service,
repository, or transport seam is replaced.

Calling ``append_permission_log`` directly would prove only that the writer
works, which was never in doubt: the writer, the reader, the model, and the
migration all existed while nothing on the decision path ever called them. The
wiring is the thing under test, so the wiring is what these tests exercise.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.permission_service import respond_to_permission
from ...control.worker_management import LazyWorkerSpawner
from ...graph.enums import PermissionType
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ApprovalStatus, ThreadStatus
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from .. import (
    create_thread,
    get_permission_logs_by_thread,
    record_permission_request,
)
from ..models import Base

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from pathlib import Path

    from ..models import PermissionLogModel

_TOOL_OPTIONS: list[dict[str, object]] = [
    {"option_id": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"option_id": "reject_once", "name": "Reject once", "kind": "reject_once"},
]

_APPROVAL_OPTIONS: list[dict[str, object]] = [
    {"option_id": "approve", "name": "Approve Plan", "kind": "allow_once"},
    {"option_id": "reject", "name": "Reject - Revise Plan", "kind": "reject_once"},
]


@pytest_asyncio.fixture
async def sessions(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'permission-audit.db'}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@asynccontextmanager
async def _worker(checkpoint_path: Path) -> AsyncGenerator[httpx.AsyncClient]:
    """Serve the production worker application over a real HTTP transport."""
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        bridge = WorkerBridge("http://127.0.0.1:1", "permission-audit-test")
        executor = Executor(saver, bridge)
        app = create_worker_app()
        app.state.executor = executor
        async with anyio.create_task_group() as tasks:
            app.state.task_group = tasks
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://worker",
            ) as client:
                yield client
            tasks.cancel_scope.cancel()
        await executor.shutdown()
        await bridge.close()


def _spawner() -> LazyWorkerSpawner:
    spawner = LazyWorkerSpawner(
        worker_url="http://worker", worker_port=8001, auto_spawn=False
    )
    spawner.replace_process(None)
    return spawner


async def _pause_run(
    sessions: async_sessionmaker[AsyncSession],
    thread_id: str,
    *,
    pause_reason_type: str,
    tool_call: str | None,
    options: list[dict[str, object]],
) -> str:
    """Park a real run on a real durable permission request."""
    request_id = f"{thread_id}:permission"
    async with sessions() as db:
        await create_thread(db, thread_id=thread_id, status=ThreadStatus.INPUT_REQUIRED)
        await record_permission_request(
            db,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type=pause_reason_type,
            description="Allow the command?",
            allowed_options=options,
            tool_call=tool_call,
        )
        await db.commit()
    return request_id


async def _decide(
    sessions: async_sessionmaker[AsyncSession],
    worker_client: httpx.AsyncClient,
    *,
    request_id: str,
    option_id: str,
    idempotency_key: str,
):
    async with sessions() as db:
        return await respond_to_permission(
            db,
            request_id=request_id,
            option_id=option_id,
            notes=None,
            idempotency_key=idempotency_key,
            aggregator=EventAggregator(),
            circuit_breaker=WorkerCircuitBreaker(
                failure_threshold=3, recovery_timeout=30.0
            ),
            worker_spawner=_spawner(),
            worker_client=worker_client,
            recursion_limit=25,
            trace_headers=None,
        )


async def _audit_rows(
    sessions: async_sessionmaker[AsyncSession], thread_id: str
) -> list[PermissionLogModel]:
    async with sessions() as db:
        return list(await get_permission_logs_by_thread(db, thread_id))


@pytest.mark.asyncio
async def test_approving_a_tool_call_records_a_durable_audit_row(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A real approval leaves a real row naming the tool and the option."""
    thread_id = "audit-approve-thread"
    request_id = await _pause_run(
        sessions,
        thread_id,
        pause_reason_type="bash",
        tool_call="bash",
        options=_TOOL_OPTIONS,
    )
    assert await _audit_rows(sessions, thread_id) == []

    async with _worker(tmp_path / "audit-approve-checkpoints.db") as worker_client:
        result = await _decide(
            sessions,
            worker_client,
            request_id=request_id,
            option_id="allow_once",
            idempotency_key="operator-approval",
        )
    assert result.accepted is True

    rows = await _audit_rows(sessions, thread_id)
    assert len(rows) == 1
    entry = rows[0]
    assert entry.thread_id == thread_id
    assert entry.tool_name == "bash"
    assert entry.action == ApprovalStatus.APPROVED.value
    assert entry.option_id == "allow_once"
    # Unattributed by design: no stage of the permission pipeline captures an
    # agent identity, so the column records the absence rather than a guess.
    assert entry.agent_id is None
    assert entry.responded_at is not None


@pytest.mark.asyncio
async def test_rejecting_a_tool_call_records_the_denial_not_an_approval(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The audited verdict follows the option's kind, so a denial reads as one."""
    thread_id = "audit-reject-thread"
    request_id = await _pause_run(
        sessions,
        thread_id,
        pause_reason_type="bash",
        tool_call="bash",
        options=_TOOL_OPTIONS,
    )

    async with _worker(tmp_path / "audit-reject-checkpoints.db") as worker_client:
        result = await _decide(
            sessions,
            worker_client,
            request_id=request_id,
            option_id="reject_once",
            idempotency_key="operator-denial",
        )
    assert result.accepted is True

    rows = await _audit_rows(sessions, thread_id)
    assert len(rows) == 1
    assert rows[0].action == ApprovalStatus.REJECTED.value
    assert rows[0].option_id == "reject_once"


@pytest.mark.asyncio
async def test_an_approval_pause_is_audited_under_the_plan_approval_sentinel(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A pause that gated no tool still names what was decided."""
    thread_id = "audit-plan-thread"
    request_id = await _pause_run(
        sessions,
        thread_id,
        pause_reason_type="plan_approval_request",
        tool_call=None,
        options=_APPROVAL_OPTIONS,
    )

    async with _worker(tmp_path / "audit-plan-checkpoints.db") as worker_client:
        result = await _decide(
            sessions,
            worker_client,
            request_id=request_id,
            option_id="approve",
            idempotency_key="operator-plan-approval",
        )
    assert result.accepted is True

    rows = await _audit_rows(sessions, thread_id)
    assert len(rows) == 1
    assert rows[0].tool_name == PermissionType.PLAN_APPROVAL.value
    assert rows[0].action == ApprovalStatus.APPROVED.value
    # The audited verdict and the thread's approval state come from one
    # derivation, so the log cannot disagree with the state the reviewer sees.
    assert result.approval_status == rows[0].action


@pytest.mark.asyncio
async def test_a_guard_rejected_response_is_not_recorded_as_a_decision(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The log holds decisions, not attempts the state machine refused."""
    thread_id = "audit-refused-thread"
    request_id = await _pause_run(
        sessions,
        thread_id,
        pause_reason_type="bash",
        tool_call="bash",
        options=_TOOL_OPTIONS,
    )

    async with _worker(tmp_path / "audit-refused-checkpoints.db") as worker_client:
        result = await _decide(
            sessions,
            worker_client,
            request_id=request_id,
            option_id="option_the_request_never_offered",
            idempotency_key="operator-bad-option",
        )
    assert result.accepted is False
    assert result.error_status_code == 409

    assert await _audit_rows(sessions, thread_id) == []


@pytest.mark.asyncio
async def test_a_client_retry_records_one_decision_not_two(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One decision yields one row however many times the client retries.

    The audit write sits behind the control-action claim election, so a retry
    that replays the same response returns before reaching it.
    """
    thread_id = "audit-retry-thread"
    request_id = await _pause_run(
        sessions,
        thread_id,
        pause_reason_type="bash",
        tool_call="bash",
        options=_TOOL_OPTIONS,
    )

    async with _worker(tmp_path / "audit-retry-checkpoints.db") as worker_client:
        first = await _decide(
            sessions,
            worker_client,
            request_id=request_id,
            option_id="allow_once",
            idempotency_key="operator-retry-1",
        )
        second = await _decide(
            sessions,
            worker_client,
            request_id=request_id,
            option_id="allow_once",
            idempotency_key="operator-retry-2",
        )
    assert first.accepted is True
    assert second.accepted is True

    rows = await _audit_rows(sessions, thread_id)
    assert len(rows) == 1
    assert rows[0].option_id == "allow_once"
