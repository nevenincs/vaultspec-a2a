"""Concurrent lease proofs for direct message and cancellation controls.

The tests use independent file-backed SQLite sessions and the production worker
HTTP application backed by a real ``Executor``. No service or repository seam is
replaced: concurrency crosses the durable journal election and accepted work crosses
the worker's synchronous dispatch-ID admission boundary.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import anyio
import httpx
import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...api.tests.clarification_harness import new_state_graph
from ...control.action_lease import claim_control_action
from ...control.cancel_service import CancelResult, cancel_thread
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.direct_control_recovery import redrive_direct_control_actions
from ...control.event_handlers import relay_event
from ...control.message_service import MessageResult, send_followup_message
from ...control.permission_service import (
    permission_response_action_key,
    respond_to_permission,
)
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_thread,
    get_control_action_by_idempotency_key,
    get_permission_request,
    get_thread,
    record_permission_request,
    record_permission_response_submission,
)
from ...database.models import Base
from ...streaming.aggregator import EventAggregator
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.idempotency import default_cancel_key
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from pathlib import Path

    from fastapi import FastAPI

    from ...worker.graph_lifecycle import RegisteredCompiledGraph


@pytest_asyncio.fixture
async def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'direct-control-leases.db'}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@asynccontextmanager
async def _worker_runtime(
    checkpoint_path: Path,
    *,
    receipt_threads: tuple[str, ...] = (),
) -> AsyncGenerator[tuple[httpx.AsyncClient, FastAPI, WorkerBridge]]:
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        bridge = WorkerBridge("http://127.0.0.1:1", "direct-control-lease-test")
        executor = Executor(saver, bridge)
        for thread_id in receipt_threads:
            _install_receipt_graph(executor, saver, thread_id)
        app = create_worker_app()
        app.state.executor = executor
        async with anyio.create_task_group() as tasks:
            app.state.task_group = tasks
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://worker",
            ) as client:
                yield client, app, bridge
            tasks.cancel_scope.cancel()
        await executor.shutdown()
        await bridge.close()


def _circuit_breaker() -> WorkerCircuitBreaker:
    return WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)


def _spawner(worker_url: str = "http://worker") -> LazyWorkerSpawner:
    spawner = LazyWorkerSpawner(
        worker_url=worker_url,
        worker_port=8001,
        auto_spawn=False,
    )
    spawner.replace_process(None)
    return spawner


def _install_receipt_graph(
    executor: Executor,
    checkpointer: AsyncSqliteSaver,
    thread_id: str,
) -> None:
    """Register a real one-node graph so Executor emits application truth."""

    async def complete(_state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage(content="applied")], "next": "FINISH"}

    builder = new_state_graph()
    builder.add_node("worker", complete)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    graph: RegisteredCompiledGraph = builder.compile(checkpointer=checkpointer)
    executor.register_compiled_graph(
        thread_id,
        ("settle-preset", None, False),
        graph,
    )


# A follow-up inherits the active project its run was created with, so a thread
# seeded for a dispatch-behaviour test needs a real one: without it the message
# service refuses before reaching the behaviour under test. The directory is
# real because the refusal is about presence, not shape.
_ACTIVE_PROJECT = tempfile.mkdtemp(prefix="vaultspec-active-project-")


def _active_project_metadata() -> str:
    """Return thread metadata naming a real active project."""
    return json.dumps({"workspace_root": _ACTIVE_PROJECT})


async def _running_thread(
    sessions: async_sessionmaker[AsyncSession],
    thread_id: str,
    *,
    team_preset: str | None = None,
) -> None:
    async with sessions() as db:
        await create_thread(
            db,
            thread_id=thread_id,
            status=ThreadStatus.RUNNING,
            team_preset=team_preset,
            metadata=_active_project_metadata(),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_permission_ack_without_graph_event_remains_pending_application(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Worker scheduling ACK is not permission application truth."""
    thread_id = "permission-ack-only-thread"
    request_id = f"{thread_id}:permission"
    async with session_factory() as db:
        await create_thread(db, thread_id=thread_id, status=ThreadStatus.INPUT_REQUIRED)
        await record_permission_request(
            db,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="bash",
            description="Allow the command?",
            allowed_options=[
                {
                    "option_id": "allow_once",
                    "name": "Allow once",
                    "kind": "allow_once",
                }
            ],
            tool_call="bash",
        )
        await db.commit()

    # The real worker accepts and schedules the dispatch, but no graph is
    # registered for this thread. Executor therefore produces no first graph
    # event and no dispatch_applied receipt.
    async with _worker_runtime(tmp_path / "permission-ack-only.db") as (
        worker_client,
        _worker_app,
        _bridge,
    ):
        async with session_factory() as db:
            result = await respond_to_permission(
                db,
                request_id=request_id,
                option_id="allow_once",
                notes=None,
                idempotency_key="permission-client-retry",
                aggregator=EventAggregator(),
                circuit_breaker=_circuit_breaker(),
                worker_spawner=_spawner(),
                worker_client=worker_client,
                recursion_limit=25,
                trace_headers=None,
            )
        assert result.accepted is True
        assert result.applied is False
        await anyio.sleep(0.2)

    async with session_factory() as db:
        thread = await get_thread(db, thread_id)
        permission = await get_permission_request(db, request_id)
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=permission_response_action_key(request_id),
        )
    assert thread is not None
    assert thread.status == ThreadStatus.INPUT_REQUIRED.value
    assert thread.last_applied_action is None
    assert permission is not None
    assert permission.request_status == "answered_pending_apply"
    assert action is not None
    assert action.applied_at is None


@pytest.mark.asyncio
async def test_concurrent_identical_custom_key_messages_dispatch_once(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "identical-message-thread"
    custom_key = "client-message-retry"
    await _running_thread(session_factory, thread_id, team_preset="settle-preset")

    async with _worker_runtime(
        tmp_path / "identical-message-checkpoints.db",
        receipt_threads=(thread_id,),
    ) as (worker_client, worker_app, bridge):

        async def send() -> MessageResult:
            async with session_factory() as db:
                return await send_followup_message(
                    db,
                    thread_id=thread_id,
                    content="continue with the audit",
                    agent_id="vaultspec-supervisor",
                    idempotency_key=custom_key,
                    circuit_breaker=_circuit_breaker(),
                    worker_spawner=_spawner(),
                    worker_client=worker_client,
                    recursion_limit=25,
                    trace_headers=None,
                )

        first, second = await asyncio.gather(send(), send())
        assert sum(result.dispatched for result in (first, second)) == 1
        assert first.action_id == second.action_id
        assert len(worker_app.state.dispatch_ids) == 1

        async with session_factory() as db:
            action = await get_control_action_by_idempotency_key(
                db, thread_id=thread_id, idempotency_key=custom_key
            )
        assert action is not None
        assert action.dispatch_id in worker_app.state.dispatch_ids
        assert action.applied_at is None

        receipt: dict[str, object] | None = None
        with anyio.fail_after(5.0):
            while receipt is None:
                buffered = cast(
                    "list[dict[str, object]]",
                    getattr(bridge, "_event_buffer", []),
                )
                for item in buffered:
                    candidate = item.get("payload")
                    candidate_mapping = (
                        cast("dict[str, object]", candidate)
                        if isinstance(candidate, dict)
                        else None
                    )
                    if (
                        candidate_mapping is not None
                        and candidate_mapping.get("type") == "dispatch_applied"
                        and candidate_mapping.get("dispatch_id") == action.dispatch_id
                    ):
                        receipt = candidate_mapping
                        break
                if receipt is None:
                    await anyio.sleep(0.01)

        await relay_event(
            thread_id,
            receipt,
            session_factory=session_factory,
        )
        async with session_factory() as db:
            settled = await get_control_action_by_idempotency_key(
                db, thread_id=thread_id, idempotency_key=custom_key
            )
        assert settled is not None
        assert settled.applied_at is not None
        assert settled.claim_token is None


@pytest.mark.asyncio
async def test_competing_same_key_messages_conflict_and_dispatch_once(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "competing-message-thread"
    custom_key = "client-competing-retry"
    await _running_thread(session_factory, thread_id)

    async with _worker_runtime(tmp_path / "competing-message-checkpoints.db") as (
        worker_client,
        worker_app,
        _bridge,
    ):

        async def send(content: str) -> MessageResult:
            async with session_factory() as db:
                return await send_followup_message(
                    db,
                    thread_id=thread_id,
                    content=content,
                    agent_id="vaultspec-supervisor",
                    idempotency_key=custom_key,
                    circuit_breaker=_circuit_breaker(),
                    worker_spawner=_spawner(),
                    worker_client=worker_client,
                    recursion_limit=25,
                    trace_headers=None,
                )

        first, second = await asyncio.gather(send("approve"), send("reject"))
        assert sum(result.dispatched for result in (first, second)) == 1
        assert {first.failure_type, second.failure_type} == {
            None,
            FailureType.CONFLICT,
        }
        assert first.action_id == second.action_id
        assert len(worker_app.state.dispatch_ids) == 1


@pytest.mark.asyncio
async def test_concurrent_cancel_retry_labels_elect_one_resource_dispatch(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "resource-cancel-thread"
    await _running_thread(session_factory, thread_id)

    async with _worker_runtime(tmp_path / "cancel-checkpoints.db") as (
        worker_client,
        worker_app,
        _bridge,
    ):

        async def cancel(label: str) -> CancelResult:
            async with session_factory() as db:
                return await cancel_thread(
                    db,
                    thread_id=thread_id,
                    idempotency_key=label,
                    circuit_breaker=_circuit_breaker(),
                    worker_spawner=_spawner(),
                    worker_client=worker_client,
                    recursion_limit=25,
                )

        first, second = await asyncio.gather(
            cancel("desktop-retry"), cancel("dashboard-retry")
        )
        assert first.action_id == second.action_id
        assert first.idempotency_key == "desktop-retry"
        assert second.idempotency_key == "dashboard-retry"
        assert (
            sum(result.accepted and not result.applied for result in (first, second))
            == 2
        )
        assert len(worker_app.state.dispatch_ids) == 1

        async with session_factory() as db:
            action = await get_control_action_by_idempotency_key(
                db,
                thread_id=thread_id,
                idempotency_key=default_cancel_key(thread_id),
            )
        assert action is not None
        assert action.dispatch_id in worker_app.state.dispatch_ids


@pytest.mark.asyncio
async def test_message_definite_failure_releases_and_ambiguous_failure_retains(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    definite_thread = "definite-message-thread"
    ambiguous_thread = "ambiguous-message-thread"
    await _running_thread(session_factory, definite_thread)
    await _running_thread(session_factory, ambiguous_thread)

    async with _worker_runtime(tmp_path / "failure-checkpoints.db") as (
        worker_client,
        worker_app,
        _bridge,
    ):
        breaker = _circuit_breaker()
        breaker.force_open()
        async with session_factory() as db:
            definite = await send_followup_message(
                db,
                thread_id=definite_thread,
                content="definite",
                agent_id="vaultspec-supervisor",
                idempotency_key="definite-key",
                circuit_breaker=breaker,
                worker_spawner=_spawner(),
                worker_client=worker_client,
                recursion_limit=25,
                trace_headers=None,
            )
        assert definite.failure_type is FailureType.CIRCUIT_OPEN
        assert len(worker_app.state.dispatch_ids) == 0

    async with (
        httpx.AsyncClient(
            base_url="http://127.0.0.1:1", timeout=0.2
        ) as unreachable_client,
        session_factory() as db,
    ):
        ambiguous = await send_followup_message(
            db,
            thread_id=ambiguous_thread,
            content="ambiguous",
            agent_id="vaultspec-supervisor",
            idempotency_key="ambiguous-key",
            circuit_breaker=_circuit_breaker(),
            worker_spawner=_spawner("http://127.0.0.1:1"),
            worker_client=unreachable_client,
            recursion_limit=25,
            trace_headers=None,
        )
    assert ambiguous.failure_type is FailureType.UNREACHABLE

    async with session_factory() as db:
        definite_action = await get_control_action_by_idempotency_key(
            db, thread_id=definite_thread, idempotency_key="definite-key"
        )
        ambiguous_action = await get_control_action_by_idempotency_key(
            db, thread_id=ambiguous_thread, idempotency_key="ambiguous-key"
        )
    assert definite_action is not None
    assert definite_action.claim_token is None
    assert definite_action.claim_expires_at is None
    assert ambiguous_action is not None
    assert ambiguous_action.claim_token is not None
    assert ambiguous_action.claim_expires_at is not None


@pytest.mark.asyncio
async def test_ambiguous_cancel_preserves_durable_cancelling_intent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A lost worker acknowledgement must not undo the accepted cancellation."""
    thread_id = "ambiguous-cancel-thread"
    await _running_thread(session_factory, thread_id)

    async with (
        httpx.AsyncClient(
            base_url="http://127.0.0.1:1", timeout=0.2
        ) as unreachable_client,
        session_factory() as db,
    ):
        result = await cancel_thread(
            db,
            thread_id=thread_id,
            idempotency_key="desktop-cancel-attempt",
            circuit_breaker=_circuit_breaker(),
            worker_spawner=_spawner("http://127.0.0.1:1"),
            worker_client=unreachable_client,
            recursion_limit=25,
            trace_headers=None,
        )

    assert result.accepted is True
    assert result.cancelled is True
    assert result.applied is False
    assert result.thread_status == ThreadStatus.CANCELLING.value
    assert result.failure_type is None

    async with session_factory() as db:
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=default_cancel_key(thread_id),
        )
        thread = await get_thread(db, thread_id)
    assert action is not None
    assert action.claim_token is not None
    assert action.claim_expires_at is not None
    assert thread is not None
    assert thread.status == ThreadStatus.CANCELLING.value


@pytest.mark.asyncio
async def test_restart_redrives_expired_permission_message_and_cancel_actions(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A new gateway reconstructs all three direct control dispatches."""
    expired_now = datetime.now(UTC) - timedelta(minutes=5)
    async with session_factory() as db:
        for thread_id, status in (
            ("recover-message", ThreadStatus.RUNNING),
            ("recover-cancel", ThreadStatus.CANCELLING),
            ("recover-permission", ThreadStatus.INPUT_REQUIRED),
        ):
            await create_thread(db, thread_id=thread_id, status=status)
        request_id = "recover-permission:permission-1"
        await record_permission_request(
            db,
            request_id=request_id,
            thread_id="recover-permission",
            pause_reason_type="bash",
            description="Allow?",
            allowed_options=[
                {
                    "option_id": "allow_once",
                    "name": "Allow once",
                    "kind": "allow_once",
                }
            ],
            tool_call="bash",
        )
        await record_permission_response_submission(
            db,
            request_id=request_id,
            option_id="allow_once",
            idempotency_key="permission-client-key",
        )
        claims = [
            await claim_control_action(
                db,
                thread_id="recover-message",
                action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                idempotency_key="recover-message-key",
                payload={"content": "continue", "agent_id": "supervisor"},
                now=expired_now,
                lease_ttl=timedelta(seconds=1),
            ),
            await claim_control_action(
                db,
                thread_id="recover-cancel",
                action_type=ControlActionType.CANCEL,
                idempotency_key=default_cancel_key("recover-cancel"),
                payload={"cancel": True},
                now=expired_now,
                lease_ttl=timedelta(seconds=1),
            ),
            await claim_control_action(
                db,
                thread_id="recover-permission",
                action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
                request_id=request_id,
                idempotency_key=f"permission-response:{request_id}",
                payload={"option_id": "allow_once", "notes": None},
                now=expired_now,
                lease_ttl=timedelta(seconds=1),
            ),
        ]
        await db.commit()

    async with _worker_runtime(tmp_path / "direct-recovery-checkpoints.db") as (
        worker_client,
        worker_app,
        _bridge,
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
        assert summary.deferred == 0
        assert summary.conflicted == 0
        admitted_ids = {
            dispatch_id
            for dispatch_id in (claim.dispatch_id for claim in claims)
            if dispatch_id in worker_app.state.dispatch_ids
        }
        assert admitted_ids == {claim.dispatch_id for claim in claims}
