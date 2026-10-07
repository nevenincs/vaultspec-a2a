"""Concurrent lease proofs for direct message and cancellation controls.

The tests use independent file-backed SQLite sessions and the production worker
HTTP application backed by a real ``Executor``. No service or repository seam is
replaced: concurrency crosses the durable journal election and accepted work crosses
the worker's synchronous dispatch-ID admission boundary.
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import anyio
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from ...conftest import SqlitePosture
from ...control import cancel_service
from ...control._permission_response_contract import PermissionInput
from ...control.accepted_input import freeze_accepted_input
from ...control.action_lease import prepare_control_action_claim
from ...control.cancel_service import CancelResult, cancel_thread
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.config import settings
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...control.execution_authority import resolve_execution_authority
from ...control.leased_dispatch import DispatchTransport
from ...control.message_service import send_followup_message
from ...control.permission_service import respond_to_permission
from ...database import (
    RecoveryAttemptModel,
    ThreadModel,
    begin_write_transaction,
    create_control_action,
    create_thread,
    get_control_action_by_idempotency_key,
    get_permission_request,
    get_thread,
    record_permission_request,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...testing import (
    add_test_node,
    adopted_spawner,
    compile_test_graph,
    new_state_graph,
    session_scratch_dir,
)
from ...testing.catalog_authority import current_execution_metadata
from ...tests._write_authority import make_test_write_authority
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...thread.idempotency import (
    default_cancel_key,
    permission_response_action_key,
    thread_create_action_key,
)
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...worker.graph_lifecycle import RegisteredCompiledGraph


_TEST_INTERNAL_TOKEN = "direct-control-lease-test-token"


@pytest.fixture(autouse=True)
def _configure_test_dispatch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give both sides of real worker dispatch the current IPC credential."""
    monkeypatch.setattr(settings, "internal_token", _TEST_INTERNAL_TOKEN)


@asynccontextmanager
async def _worker_runtime(
    checkpointer: AsyncSqliteSaver,
    *,
    receipt_threads: tuple[str, ...] = (),
) -> AsyncGenerator[tuple[httpx.AsyncClient, FastAPI, WorkerBridge]]:
    relayed_events: list[dict[str, object]] = []
    event_sink = FastAPI()

    @event_sink.post("/internal/events/batch")
    async def accept_event_batch(request: Request) -> JSONResponse:
        body = await request.json()
        relayed_events.extend(cast("list[dict[str, object]]", body["events"]))
        return JSONResponse({"status": "ok"})

    bridge = WorkerBridge("http://control", "direct-control-lease-test")
    await bridge._client.aclose()
    bridge._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=event_sink),
        base_url="http://control",
    )
    executor = Executor(checkpointer, bridge)
    for thread_id in receipt_threads:
        _install_receipt_graph(executor, checkpointer, thread_id)
    app = create_worker_app()
    app.state.executor = executor
    app.state.relayed_events = relayed_events
    async with anyio.create_task_group() as tasks:
        app.state.task_group = tasks
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://worker",
            headers={"Authorization": f"Bearer {_TEST_INTERNAL_TOKEN}"},
        ) as client:
            yield client, app, bridge
        tasks.cancel_scope.cancel()
    await executor.shutdown()
    await bridge.close()


def _circuit_breaker() -> WorkerCircuitBreaker:
    return WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30.0)


def _install_receipt_graph(
    executor: Executor,
    checkpointer: AsyncSqliteSaver,
    thread_id: str,
) -> None:
    """Register a real one-node graph so Executor emits application truth."""

    async def complete(_state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage(content="applied")], "next": "FINISH"}

    builder = new_state_graph()
    add_test_node(builder, "worker", complete)
    builder.add_edge("__start__", "worker")
    builder.add_edge("worker", "__end__")
    graph: RegisteredCompiledGraph = compile_test_graph(
        builder, checkpointer=checkpointer
    )
    workspace = Path(_ACTIVE_PROJECT)
    definition = freeze_graph_definition(
        load_team_config("mock-success-single", workspace_root=workspace),
        workspace_root=workspace,
    )
    executor.register_compiled_graph(
        thread_id,
        (
            "mock-success-single",
            str(workspace),
            False,
            resolve_execution_authority(
                current_execution_metadata(workspace)
            ).model_assignment_digest,
            definition.digest(),
        ),
        graph,
    )


# A follow-up inherits the active project its run was created with, so a thread
# seeded for a dispatch-behaviour test needs a real one: without it the message
# service refuses before reaching the behaviour under test. The directory is
# real because the refusal is about presence, not shape.
_ACTIVE_PROJECT = str(session_scratch_dir("vaultspec-active-project-"))


def _active_project_metadata() -> str:
    """Return current execution authority naming a real active project."""
    return current_execution_metadata(Path(_ACTIVE_PROJECT))


async def _running_thread(
    sessions: async_sessionmaker[AsyncSession],
    thread_id: str,
    *,
    team_preset: str = "mock-success-single",
) -> None:
    async with sessions() as db:
        await _create_current_thread(
            db,
            thread_id=thread_id,
            status=ThreadStatus.RUNNING,
            team_preset=team_preset,
        )
        await db.commit()


async def _create_current_thread(
    db: AsyncSession,
    *,
    thread_id: str,
    status: ThreadStatus,
    team_preset: str = "mock-success-single",
) -> None:
    """Persist a thread with the complete current initial graph authority."""
    authority = make_test_write_authority()
    workspace = Path(_ACTIVE_PROJECT)
    metadata = _active_project_metadata()
    execution_authority = resolve_execution_authority(metadata)
    definition = freeze_graph_definition(
        load_team_config(team_preset, workspace_root=workspace),
        workspace_root=workspace,
    )
    await create_thread(
        db,
        write_authority=authority,
        thread_id=thread_id,
        status=status,
        team_preset=team_preset,
        metadata=metadata,
    )
    dispatch = DispatchRequest(
        dispatch_id=authority.action_receipt_id,
        action="ingest",
        thread_id=thread_id,
        content="seed accepted graph authority",
        team_preset=team_preset,
        graph_definition=definition,
        workspace_root=str(workspace),
        recursion_limit=25,
        model_assignment=execution_authority.model_assignment,
    )
    await create_control_action(
        db,
        thread_id=thread_id,
        action_type=authority.action_type,
        idempotency_key=thread_create_action_key(thread_id),
        dispatch_id=authority.action_receipt_id,
        payload=freeze_accepted_input(
            dispatch, intent={"content": "seed accepted graph authority"}
        ),
        recovery_deadline_at=datetime(2100, 1, 1, tzinfo=UTC),
    )
    receipt = await prepare_graph_action_receipt(
        db,
        thread_id=thread_id,
        dispatch_id=authority.action_receipt_id,
    )
    assert receipt is not None


@pytest.mark.asyncio
async def test_permission_ack_without_graph_event_remains_pending_application(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Worker scheduling ACK is not permission application truth."""
    thread_id = "permission-ack-only-thread"
    request_id = f"{thread_id}:permission"
    async with session_factory() as db:
        await _create_current_thread(
            db,
            thread_id=thread_id,
            status=ThreadStatus.INPUT_REQUIRED,
        )
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
    async with _worker_runtime(checkpointer) as (
        worker_client,
        _worker_app,
        _bridge,
    ):
        async with session_factory() as db:
            pending = await get_permission_request(db, request_id)
            assert pending is not None
            result = await respond_to_permission(
                db,
                permission=pending,
                response=PermissionInput(
                    request_id, "allow_once", "permission-client-retry"
                ),
                transport=DispatchTransport(
                    worker_client=worker_client,
                    circuit_breaker=_circuit_breaker(),
                    worker_spawner=adopted_spawner(),
                ),
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


async def _parked_permission(
    sessions: async_sessionmaker[AsyncSession], thread_id: str
) -> str:
    """Seed a run parked on a permission question and return its request id."""
    request_id = f"{thread_id}:permission"
    async with sessions() as db:
        await _create_current_thread(
            db,
            thread_id=thread_id,
            status=ThreadStatus.INPUT_REQUIRED,
        )
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
    return request_id


@pytest.mark.asyncio
async def test_definite_resume_failure_releases_and_ambiguous_failure_retains(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ownership is given back only for a delivery proven not to have happened.

    Neither arm needs a worker to pretend anything. The first meets a circuit
    the breaker really has shut, so the resume never left the gateway and the
    claim is certainly free to take again. The second meets a port with nothing
    behind it, which proves only that the acknowledgement was lost - the worker
    may have scheduled the resume - so the claim is held until reconciliation
    or expiry. Both record the condition they met, which is what the retry is
    scheduled against.
    """
    definite_thread = "definite-resume-thread"
    ambiguous_thread = "ambiguous-resume-thread"
    definite_request = await _parked_permission(session_factory, definite_thread)
    ambiguous_request = await _parked_permission(session_factory, ambiguous_thread)

    shut = _circuit_breaker()
    shut.force_open()
    async with (
        httpx.AsyncClient(base_url="http://127.0.0.1:1", timeout=0.2) as no_worker,
        session_factory() as db,
    ):
        definite_permission = await get_permission_request(db, definite_request)
        assert definite_permission is not None
        definite = await respond_to_permission(
            db,
            permission=definite_permission,
            response=PermissionInput(definite_request, "allow_once", "definite-retry"),
            transport=DispatchTransport(
                worker_client=no_worker,
                circuit_breaker=shut,
                worker_spawner=adopted_spawner("http://127.0.0.1:1"),
            ),
        )
    assert definite.failure_type is FailureType.CIRCUIT_OPEN

    async with (
        httpx.AsyncClient(base_url="http://127.0.0.1:1", timeout=0.2) as unreachable,
        session_factory() as db,
    ):
        ambiguous_permission = await get_permission_request(db, ambiguous_request)
        assert ambiguous_permission is not None
        ambiguous = await respond_to_permission(
            db,
            permission=ambiguous_permission,
            response=PermissionInput(
                ambiguous_request, "allow_once", "ambiguous-retry"
            ),
            transport=DispatchTransport(
                worker_client=unreachable,
                circuit_breaker=_circuit_breaker(),
                worker_spawner=adopted_spawner("http://127.0.0.1:1"),
            ),
        )
    assert ambiguous.failure_type is FailureType.UNREACHABLE

    async with session_factory() as db:
        definite_action = await get_control_action_by_idempotency_key(
            db,
            thread_id=definite_thread,
            idempotency_key=permission_response_action_key(definite_request),
        )
        ambiguous_action = await get_control_action_by_idempotency_key(
            db,
            thread_id=ambiguous_thread,
            idempotency_key=permission_response_action_key(ambiguous_request),
        )
        attempts = (
            (
                await db.execute(
                    select(RecoveryAttemptModel).where(
                        RecoveryAttemptModel.thread_id.in_(
                            {definite_thread, ambiguous_thread}
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
    assert definite_action is not None
    assert definite_action.claim_token is None
    assert definite_action.claim_expires_at is None
    assert ambiguous_action is not None
    assert ambiguous_action.claim_token is not None
    assert ambiguous_action.claim_expires_at is not None
    # Identity survives both dispositions: only ownership differs.
    assert definite_action.applied_at is None
    assert ambiguous_action.applied_at is None
    assert {attempt.thread_id: attempt.condition for attempt in attempts} == {
        definite_thread: "circuit_open",
        ambiguous_thread: "unreachable",
    }


@pytest.mark.asyncio
async def test_a_followup_reserves_nothing_while_the_run_is_cancelling(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A run that is leaving refuses before the lease, so nothing is written.

    The two states that still own an unfinished turn now admit a continuation
    behind it; a cancelling run does not, because it will never promote one.
    Its refusal has to precede the reservation, so this reads the durable side
    afterwards: no journal action under the key, no writer transition, and no
    dispatch id admitted by a REAL worker that is running and would have taken
    one.
    """
    status = ThreadStatus.CANCELLING
    thread_id = f"busy-{status.value}-thread"
    async with session_factory() as db:
        await _create_current_thread(db, thread_id=thread_id, status=status)
        await db.commit()

    async with session_factory() as db:
        before = await get_thread(db, thread_id)
        assert before is not None
        requested_before = before.last_requested_action

    async with _worker_runtime(checkpointer) as (
        _worker_client,
        worker_app,
        _bridge,
    ):
        async with session_factory() as db:
            result = await send_followup_message(
                db,
                thread_id=thread_id,
                content="second turn",
                agent_id="vaultspec-supervisor",
                idempotency_key="busy-refusal-key",
            )
        assert result.queued is False
        assert result.failure_type is FailureType.RUN_BUSY
        assert result.action_id == ""
        assert len(worker_app.state.dispatch_ids) == 0

    async with session_factory() as db:
        action = await get_control_action_by_idempotency_key(
            db, thread_id=thread_id, idempotency_key="busy-refusal-key"
        )
        after = await get_thread(db, thread_id)
    assert action is None
    assert after is not None
    assert after.status == status.value
    assert after.last_requested_action == requested_before


@pytest.mark.asyncio
async def test_cancel_retries_sqlite_lock_before_claim(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread_id = "locked-cancel-thread"
    await _running_thread(session_factory, thread_id)
    original_claim = prepare_control_action_claim
    attempts = 0

    async def locked_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OperationalError(
                "INSERT INTO control_actions",
                {},
                sqlite3.OperationalError("database is locked"),
            )
        return await original_claim(*args, **kwargs)

    monkeypatch.setattr(cancel_service, "prepare_control_action_claim", locked_once)
    async with _worker_runtime(checkpointer) as (
        worker_client,
        worker_app,
        _bridge,
    ):
        async with session_factory() as db:
            result = await cancel_thread(
                db,
                thread_id=thread_id,
                idempotency_key=None,
                transport=DispatchTransport(
                    worker_client=worker_client,
                    circuit_breaker=_circuit_breaker(),
                    worker_spawner=adopted_spawner(),
                ),
            )
        assert result.accepted
        assert attempts == 2
        assert len(worker_app.state.dispatch_ids) == 1


@pytest.mark.asyncio
async def test_concurrent_cancel_retry_labels_elect_one_resource_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    thread_id = "resource-cancel-thread"
    await _running_thread(session_factory, thread_id)

    async with _worker_runtime(checkpointer) as (
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
                    transport=DispatchTransport(
                        worker_client=worker_client,
                        circuit_breaker=_circuit_breaker(),
                        worker_spawner=adopted_spawner(),
                    ),
                )

        first, second = await asyncio.gather(
            cancel("desktop-retry"), cancel("dashboard-retry")
        )
        assert first.action_id == second.action_id
        assert first.idempotency_key == "desktop-retry"
        assert second.idempotency_key == "dashboard-retry"
        accepted = [result for result in (first, second) if result.accepted]
        assert len(accepted) >= 1
        for result in (first, second):
            if not result.accepted:
                assert result.failure_type is FailureType.CONFLICT
                assert result.thread_status == ThreadStatus.RUNNING.value
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
            transport=DispatchTransport(
                worker_client=unreachable_client,
                circuit_breaker=_circuit_breaker(),
                worker_spawner=adopted_spawner("http://127.0.0.1:1"),
            ),
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
async def test_definite_cancel_non_delivery_never_rolls_back_lifecycle_authority(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "definite-cancel-thread"
    await _running_thread(session_factory, thread_id)
    app = FastAPI()

    @app.post("/dispatch")
    async def reject_dispatch() -> JSONResponse:
        return JSONResponse({"detail": "at capacity"}, status_code=429)

    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://worker"
        ) as worker_client,
        session_factory() as db,
    ):
        result = await cancel_thread(
            db,
            thread_id=thread_id,
            idempotency_key="definite-cancel-attempt",
            transport=DispatchTransport(
                worker_client=worker_client,
                circuit_breaker=_circuit_breaker(),
                worker_spawner=adopted_spawner(),
            ),
        )
    assert result.cancelled is False
    assert result.accepted is False
    assert result.failure_type is FailureType.AT_CAPACITY
    assert result.thread_status == ThreadStatus.CANCELLING.value
    async with session_factory() as db:
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=default_cancel_key(thread_id),
        )
        thread = await get_thread(db, thread_id)
    assert action is not None
    assert action.claim_token is None
    assert action.claim_expires_at is None
    assert thread is not None
    assert thread.status == ThreadStatus.CANCELLING.value
    assert thread.run_revision == 1
    assert thread.writer_action_type == ControlActionType.CANCEL.value
    assert thread.writer_action_receipt_id == action.dispatch_id


@pytest.mark.asyncio
async def test_terminal_state_before_cancel_prevents_dispatch_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "terminal-before-cancel"
    async with session_factory() as db:
        await create_thread(
            db,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=ThreadStatus.COMPLETED,
        )
        await db.commit()
    async with (
        httpx.AsyncClient(base_url="http://127.0.0.1:1") as worker_client,
        session_factory() as db,
    ):
        result = await cancel_thread(
            db,
            thread_id=thread_id,
            idempotency_key="too-late",
            transport=DispatchTransport(
                worker_client=worker_client,
                circuit_breaker=_circuit_breaker(),
                worker_spawner=adopted_spawner("http://127.0.0.1:1"),
            ),
        )
    assert result.accepted is False
    assert result.failure_type is FailureType.TERMINAL
    async with session_factory() as db:
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=default_cancel_key(thread_id),
        )
    assert action is None


# The election proofs above keep journal mode and lock waiting at driver
# defaults. Contention between a service's read and its write is only faithful
# under the posture the product actually serves on: write-ahead logging, the
# configured busy timeout, and SQLAlchemy owning every ``BEGIN``.
@pytest.mark.asyncio
@pytest.mark.sqlite_engine(SqlitePosture.APPLICATION)
async def test_cancel_waits_for_a_concurrent_writer_rather_than_failing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A commit landing between the cancel preflight and its claim must not refuse.

    The preflight reads the run and its owning action before the claim writes.
    Begun deferred, that upgrade is refused outright the moment another
    connection commits in between - ``busy_timeout`` is never consulted - and the
    operator sees a 500 for an entirely ordinary race.
    """
    thread_id = "cancel-under-contention"
    await _running_thread(session_factory, thread_id)
    app = FastAPI()

    @app.post("/dispatch")
    async def accept_dispatch() -> JSONResponse:
        return JSONResponse({"status": "accepted"})

    async with session_factory() as sibling:
        sibling_thread = await sibling.get(ThreadModel, thread_id)
        assert sibling_thread is not None
        await sibling.rollback()

        # Hold the write lock on an unrelated projection, exactly as another
        # relay write would.
        await begin_write_transaction(sibling)
        held = await sibling.get(ThreadModel, thread_id)
        assert held is not None
        held.last_sequence = 7
        await sibling.flush()

        async def _cancel() -> CancelResult:
            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://worker"
                ) as worker_client,
                session_factory() as db,
            ):
                return await cancel_thread(
                    db,
                    thread_id=thread_id,
                    idempotency_key="contended-cancel",
                    transport=DispatchTransport(
                        worker_client=worker_client,
                        circuit_breaker=_circuit_breaker(),
                        worker_spawner=adopted_spawner(),
                    ),
                )

        cancelling = asyncio.create_task(_cancel())
        await asyncio.sleep(0.3)
        assert not cancelling.done(), "the cancel must queue behind the write lock"
        await sibling.commit()
        result = await asyncio.wait_for(cancelling, timeout=10.0)

    assert result.accepted is True
    assert result.cancelled is True
    assert result.failure_type is None
    assert result.thread_status == ThreadStatus.CANCELLING.value

    async with session_factory() as db:
        thread = await get_thread(db, thread_id)
        action = await get_control_action_by_idempotency_key(
            db,
            thread_id=thread_id,
            idempotency_key=default_cancel_key(thread_id),
        )
    assert thread is not None
    assert thread.status == ThreadStatus.CANCELLING.value
    # The sibling's commit survived the cancellation that waited for it.
    assert thread.last_sequence == 7
    assert action is not None
