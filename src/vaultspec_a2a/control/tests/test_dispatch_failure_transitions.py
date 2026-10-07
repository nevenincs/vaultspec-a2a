"""Dispatch-failure state transitions stay aligned with readiness semantics."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...api.tests.clarification_harness import park_clarification
from ...control._permission_response_contract import (
    PermissionInput,
    PermissionRuntime,
)
from ...control.accepted_input import freeze_accepted_input
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.clarification_service import (
    ClarificationRuntime,
    respond_to_clarification,
)
from ...control.config import settings
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...control.execution_authority import resolve_execution_authority
from ...control.permission_service import respond_to_permission
from ...control.repair_transitions import apply_dispatch_failure
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_control_action,
    create_thread,
    get_permission_request,
    get_thread,
    record_permission_request,
)
from ...domain_config import domain_config
from ...ipc.schemas import DispatchRequest
from ...providers.conditions import ProviderCondition
from ...team.team_config import load_team_config
from ...testing import session_scratch_dir
from ...tests._write_authority import make_test_write_authority
from ...thread.clarification import ClarificationAnswers
from ...thread.dispatch_policy import FailureType
from ...thread.enums import RepairStatus, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from ._catalog_authority import current_execution_metadata

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
    )

_TEST_INTERNAL_TOKEN = "dispatch-failure-transition-test-token"


@pytest.fixture
def _dispatch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give both sides of real worker dispatch the current IPC credential."""
    monkeypatch.setattr(settings, "internal_token", _TEST_INTERNAL_TOKEN)


@asynccontextmanager
async def _saturated_worker(
    checkpoint_path: Path,
) -> AsyncGenerator[httpx.AsyncClient]:
    """Serve the production worker app with every run slot already taken.

    The capacity is exhausted through the executor's own reservation verb, so
    the 429 the gateway meets is the one the worker composes for a full
    service rather than a status written here.
    """
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        bridge = WorkerBridge("http://control", "dispatch-failure-transition-test")
        executor = Executor(saver, bridge)
        for index in range(domain_config.max_concurrent_threads):
            reservation, _reason = await executor.reserve_dispatch_capacity(
                f"held-{index}"
            )
            assert reservation is not None
        app = create_worker_app()
        app.state.executor = executor
        async with anyio.create_task_group() as tasks:
            app.state.task_group = tasks
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://worker",
                headers={"Authorization": f"Bearer {_TEST_INTERNAL_TOKEN}"},
            ) as client:
                yield client
            tasks.cancel_scope.cancel()
        await executor.shutdown()
        await bridge.close()


# A follow-up inherits the active project its run was created with, so a thread
# seeded for a dispatch-behaviour test needs a real one: without it the message
# service refuses before reaching the behaviour under test. The directory is
# real because the refusal is about presence, not shape.
_ACTIVE_PROJECT = str(session_scratch_dir("vaultspec-active-project-"))


def _active_project_metadata() -> str:
    """Return current execution authority naming a real active project."""
    return current_execution_metadata(Path(_ACTIVE_PROJECT))


async def _seed_accepted_initial_action(
    session: AsyncSession, thread_id: str, *, workspace: Path | None = None
) -> None:
    thread = await get_thread(session, thread_id)
    assert thread is not None
    metadata = thread.thread_metadata or _active_project_metadata()
    workspace = workspace or Path(_ACTIVE_PROJECT)
    dispatch = DispatchRequest(
        dispatch_id=thread.writer_action_receipt_id,
        action="ingest",
        thread_id=thread_id,
        content="initial fixture",
        workspace_root=str(workspace),
        team_preset="mock-success-single",
        graph_definition=freeze_graph_definition(
            load_team_config("mock-success-single", workspace_root=workspace),
            workspace_root=workspace,
        ),
        model_assignment=resolve_execution_authority(metadata).model_assignment,
        recursion_limit=25,
    )
    await create_control_action(
        session,
        thread_id=thread_id,
        action_type=thread.writer_action_type,
        idempotency_key=f"thread-create:{thread_id}",
        dispatch_id=thread.writer_action_receipt_id,
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        payload=freeze_accepted_input(dispatch, intent={"content": "initial fixture"}),
    )
    assert (
        await prepare_graph_action_receipt(
            session, thread_id=thread_id, dispatch_id=thread.writer_action_receipt_id
        )
        is not None
    )


@pytest.mark.asyncio
async def test_a_failed_dispatch_records_its_reason_and_condition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A dispatch that fails the run persists why, on both durable channels."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Failed dispatch",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    async with session_factory() as session:
        await apply_dispatch_failure(
            session,
            thread.id,
            failed_status=ThreadStatus.FAILED,
            reason="the gateway worker is not reachable",
        )
        await session.commit()

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == ThreadStatus.FAILED.value
        assert updated.failure_reason == "the gateway worker is not reachable"
        # The floor, not a provider member: nothing here reached a provider.
        assert updated.provider_condition == ProviderCondition.UNKNOWN.value
        assert updated.repair_reason == "the gateway worker is not reachable"


@pytest.mark.asyncio
async def test_an_undelivered_resume_does_not_stamp_a_failure_on_a_live_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A run left parked keeps its question, and reports no failure.

    The permission-resume caller passes INPUT_REQUIRED: the resume did not
    arrive, but the run is still alive and still waiting on its answer. Writing
    a failure reason or condition here would make a reloading client report a
    failure that never happened, because both columns are defined as describing
    a run that FAILED. The account survives on the repair reason instead.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Undelivered resume",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    async with session_factory() as session:
        await apply_dispatch_failure(
            session,
            thread.id,
            failed_status=ThreadStatus.INPUT_REQUIRED,
            reason="the gateway worker is not reachable",
        )
        await session.commit()

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == ThreadStatus.INPUT_REQUIRED.value
        assert updated.failure_reason is None
        assert updated.provider_condition is None
        # Not lost, just carried where a still-live run can honestly carry it.
        assert updated.repair_reason == "the gateway worker is not reachable"


@pytest.mark.asyncio
async def test_a_definitely_undelivered_resume_records_why_the_answer_did_not_land(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """An answer that never reached the parked node says so durably.

    The clarification is parked in a real checkpoint by the real graph, and an
    open circuit is a definite non-delivery: the resume never left the gateway,
    so the claim is released and the answer certainly did not reach the node.
    The run is untouched - still parked, still answerable - so the account is
    recorded where a live run can carry it and nowhere that claims a failure.
    """
    thread_id = "undelivered-clarification-resume"
    async with AsyncSqliteSaver.from_conn_string(
        str(tmp_path / "clarification-checkpoints.db")
    ) as checkpointer:
        await checkpointer.setup()
        parked = await park_clarification(checkpointer, thread_id=thread_id)

        async with session_factory() as session:
            await create_thread(
                session,
                write_authority=make_test_write_authority(),
                thread_id=thread_id,
                status=ThreadStatus.INPUT_REQUIRED,
                title="Undelivered clarification resume",
                repair_status="paused_resumable",
                execution_readiness="paused_resumable",
                metadata=current_execution_metadata(tmp_path),
            )
            await _seed_accepted_initial_action(session, thread_id, workspace=tmp_path)
            await session.commit()

        spawner = LazyWorkerSpawner(
            worker_url="http://127.0.0.1:9",
            worker_port=9,
            auto_spawn=False,
        )
        spawner.replace_process(None)
        circuit_breaker = WorkerCircuitBreaker(
            failure_threshold=1,
            recovery_timeout=30.0,
        )
        circuit_breaker.force_open()

        async with (
            httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client,
            session_factory() as session,
        ):
            result = await respond_to_clarification(
                session,
                thread_id=thread_id,
                request_id=parked.request.request_id,
                resolution=ClarificationAnswers(
                    request_id=parked.request.request_id,
                    answers={"provider": "codex"},
                ),
                runtime=ClarificationRuntime(
                    checkpointer, client, circuit_breaker, spawner, 1, None
                ),
            )

    assert result.dispatched is False
    assert result.failure_type is FailureType.CIRCUIT_OPEN

    async with session_factory() as session:
        updated = await get_thread(session, thread_id)
        assert updated is not None
        # Still parked on the same question, so no failure may be stamped.
        assert updated.status == ThreadStatus.INPUT_REQUIRED.value
        assert updated.failure_reason is None
        assert updated.provider_condition is None
        assert updated.repair_reason is not None
        assert updated.repair_reason.startswith("Clarification resume not delivered:")
        assert result.error_detail is not None
        assert result.error_detail in updated.repair_reason
        # The resume stays resumable: a released claim is redrivable, and the
        # pause it is parked on is unchanged.
        assert updated.repair_status == "paused_resumable"
        assert updated.execution_readiness == "paused_resumable"


@pytest.mark.asyncio
async def test_a_reasonless_failure_still_carries_a_condition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A failed run is classified even when the caller supplied no message.

    The condition rides the FAILURE, not the reason. A caller that fails a run
    without a message must still leave a classified row - otherwise the blank
    terminal this campaign removes returns through the back door, and a client
    reloading sees a failed run it cannot branch on.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Reasonless failure",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

    async with session_factory() as session:
        await apply_dispatch_failure(
            session,
            thread.id,
            failed_status=ThreadStatus.FAILED,
        )
        await session.commit()

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
        assert updated is not None
        assert updated.status == ThreadStatus.FAILED.value
        assert updated.failure_reason is None
        assert updated.provider_condition == ProviderCondition.UNKNOWN.value


def _permission_spawner(worker_url: str = "http://worker") -> LazyWorkerSpawner:
    spawner = LazyWorkerSpawner(
        worker_url=worker_url, worker_port=8001, auto_spawn=False
    )
    spawner.replace_process(None)
    return spawner


async def _parked_permission_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    workspace: Path,
) -> str:
    """Seed a run parked on a real tool-permission question."""
    request_id = f"{thread_id}:permission"
    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=ThreadStatus.INPUT_REQUIRED,
            title="Parked on a tool permission",
            repair_status=RepairStatus.PAUSED_RESUMABLE.value,
            execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
            metadata=current_execution_metadata(workspace),
        )
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="tool_permission_request",
            description="Allow the command?",
            allowed_options=[{"optionId": "allow_once", "name": "Allow once"}],
        )
        await _seed_accepted_initial_action(session, thread_id, workspace=workspace)
        await session.commit()
    return request_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("_dispatch_auth")
async def test_a_saturated_worker_leaves_the_parked_run_answerable(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Backpressure retains the accepted answer instead of quarantining the run.

    The worker is the production application with every run slot genuinely
    taken, so the refusal is its own 429. Capacity says "not now", which is a
    condition that passes: the run is still parked on its question, still
    answerable, and the scheduled retry owns what happens next. Declaring
    operator intervention here would strand a run nothing is wrong with.
    """
    thread_id = "capacity-refused-resume"
    request_id = await _parked_permission_run(
        session_factory, thread_id=thread_id, workspace=tmp_path
    )

    async with (
        _saturated_worker(tmp_path / "capacity-checkpoints.db") as worker_client,
        session_factory() as session,
    ):
        result = await respond_to_permission(
            session,
            response=PermissionInput(request_id, "allow_once", "capacity-retry"),
            runtime=PermissionRuntime(
                WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30.0),
                _permission_spawner(),
                worker_client,
                25,
                None,
            ),
        )

    assert result.accepted is False
    assert result.failure_type is FailureType.AT_CAPACITY
    # The caller still learns the answer did not land, and learns it as the
    # typed outcome rather than as a status this service picked: a dispatch
    # outcome is served identically by every verb that can meet it, so the
    # status belongs to the one protocol mapping and not to here.
    assert result.error_detail
    assert result.error_status_code is None

    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
        permission = await get_permission_request(session, request_id)
    assert thread is not None
    assert thread.status == ThreadStatus.INPUT_REQUIRED.value
    assert thread.failure_reason is None
    assert thread.repair_status == RepairStatus.PAUSED_RESUMABLE.value
    assert thread.execution_readiness == RepairStatus.PAUSED_RESUMABLE.value
    # A capacity refusal is proven non-delivery, so the question is handed back
    # whole rather than left half-answered.
    assert permission is not None
    assert permission.request_status == "pending"


@pytest.mark.asyncio
async def test_an_unreachable_worker_leaves_the_parked_run_answerable(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A transport failure retains the accepted answer for its scheduled retry.

    Nothing is listening on the port, so the refused connection is a real one.
    It proves nothing about the run: the answer may even have been scheduled
    before the acknowledgement was lost, which is exactly why the run must be
    left resumable for recovery rather than quarantined for an operator.
    """
    thread_id = "unreachable-refused-resume"
    request_id = await _parked_permission_run(
        session_factory, thread_id=thread_id, workspace=tmp_path
    )

    async with (
        httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as worker_client,
        session_factory() as session,
    ):
        result = await respond_to_permission(
            session,
            response=PermissionInput(request_id, "allow_once", "unreachable-retry"),
            runtime=PermissionRuntime(
                WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30.0),
                _permission_spawner("http://127.0.0.1:9"),
                worker_client,
                25,
                None,
            ),
        )

    assert result.accepted is False
    assert result.failure_type is FailureType.UNREACHABLE
    assert result.error_detail
    assert result.error_status_code is None

    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
        permission = await get_permission_request(session, request_id)
    assert thread is not None
    assert thread.status == ThreadStatus.INPUT_REQUIRED.value
    assert thread.failure_reason is None
    assert thread.repair_status == RepairStatus.PAUSED_RESUMABLE.value
    assert thread.execution_readiness == RepairStatus.PAUSED_RESUMABLE.value
    # Ambiguous delivery keeps the submitted answer: undoing it here would let
    # a second, different answer race a resume that may already be running.
    assert permission is not None
    assert permission.request_status == "answered_pending_apply"
