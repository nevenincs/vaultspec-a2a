"""Repair transitions, dispatch failure among them, stay aligned with readiness."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest

from ...api.tests.clarification_harness import park_clarification
from ...control._permission_response_contract import PermissionInput
from ...control.accepted_input import freeze_accepted_input
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.clarification_service import (
    ClarificationRuntime,
    respond_to_clarification,
)
from ...control.config import settings
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...control.execution_authority import resolve_execution_authority
from ...control.leased_dispatch import DispatchTransport
from ...control.permission_service import respond_to_permission
from ...control.repair_transitions import (
    apply_dispatch_failure,
    apply_repair_transition,
)
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
from ...testing import adopted_spawner, session_scratch_dir
from ...testing.catalog_authority import current_execution_metadata
from ...tests._write_authority import make_test_write_authority
from ...thread.clarification import ClarificationAnswers
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionType, RepairStatus, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...thread.idempotency import thread_create_action_key
from ...thread.repair_policy import (
    DISPATCH_FAILED_TRANSITION,
    RepairPhase,
    repair_state_for_action,
)
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
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
    checkpointer: AsyncSqliteSaver,
) -> AsyncGenerator[httpx.AsyncClient]:
    """Serve the production worker app with every run slot already taken.

    The capacity is exhausted through the executor's own reservation verb, so
    the 429 the gateway meets is the one the worker composes for a full
    service rather than a status written here.
    """
    bridge = WorkerBridge("http://control", "dispatch-failure-transition-test")
    executor = Executor(checkpointer, bridge)
    for index in range(domain_config.max_concurrent_threads):
        reservation, _reason = await executor.reserve_dispatch_capacity(f"held-{index}")
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
        idempotency_key=thread_create_action_key(thread_id),
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


#: Every step of a control action the repair policy maps.
_ACTION_STEPS: list[tuple[ControlActionType, RepairPhase]] = [
    (ControlActionType.INGEST, RepairPhase.REQUESTED),
    (ControlActionType.INGEST, RepairPhase.APPLIED),
    (ControlActionType.PERMISSION_REQUEST_CREATED, RepairPhase.APPLIED),
    (ControlActionType.PERMISSION_RESPONSE_SUBMITTED, RepairPhase.REQUESTED),
    (ControlActionType.PERMISSION_RESPONSE_APPLIED, RepairPhase.APPLIED),
    (ControlActionType.MESSAGE_FOLLOWUP_REQUESTED, RepairPhase.REQUESTED),
    (ControlActionType.MESSAGE_FOLLOWUP_APPLIED, RepairPhase.APPLIED),
    (ControlActionType.CANCEL, RepairPhase.REQUESTED),
    (ControlActionType.CANCEL, RepairPhase.APPLIED),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "phase"), _ACTION_STEPS)
async def test_every_action_step_persists_through_the_one_applier(
    session_factory: async_sessionmaker[AsyncSession],
    action: ControlActionType,
    phase: RepairPhase,
) -> None:
    """Each mapped step lands whole: posture, readiness, account and action.

    The run starts quarantined with a stale account, so a step that left any of
    them behind would show here. Readiness is never written on its own, so it
    must read back as the posture the step installed.
    """
    transition = repair_state_for_action(action, phase)
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Repair step",
            repair_status=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
            repair_reason="a stale account",
        )
        await session.commit()

    async with session_factory() as session:
        await apply_repair_transition(session, thread.id, transition)
        await session.commit()

    async with session_factory() as session:
        updated = await get_thread(session, thread.id)
    assert updated is not None
    assert updated.repair_status == transition.repair_status.value
    assert updated.execution_readiness == updated.repair_status
    assert updated.repair_reason == transition.reason
    recorded = (
        updated.last_requested_action
        if phase is RepairPhase.REQUESTED
        else updated.last_applied_action
    )
    untouched = (
        updated.last_applied_action
        if phase is RepairPhase.REQUESTED
        else updated.last_requested_action
    )
    assert recorded == action.value
    assert untouched is None


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
        # The status change and the repair transition land together.
        assert updated.repair_status == DISPATCH_FAILED_TRANSITION.repair_status
        assert updated.execution_readiness == updated.repair_status


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
    checkpointer: AsyncSqliteSaver,
) -> None:
    """An answer that never reached the parked node says so durably.

    The clarification is parked in a real checkpoint by the real graph, and an
    open circuit is a definite non-delivery: the resume never left the gateway,
    so the claim is released and the answer certainly did not reach the node.
    The run is untouched - still parked, still answerable - so the account is
    recorded where a live run can carry it and nowhere that claims a failure.
    """
    thread_id = "undelivered-clarification-resume"
    parked = await park_clarification(checkpointer, thread_id=thread_id)

    async with session_factory() as session:
        await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id=thread_id,
            status=ThreadStatus.INPUT_REQUIRED,
            title="Undelivered clarification resume",
            repair_status="paused_resumable",
            metadata=current_execution_metadata(tmp_path),
        )
        await _seed_accepted_initial_action(session, thread_id, workspace=tmp_path)
        await session.commit()

    spawner = adopted_spawner()
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
                checkpointer,
                DispatchTransport(
                    worker_client=client,
                    circuit_breaker=circuit_breaker,
                    worker_spawner=spawner,
                ),
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
        # With no account of its own, the repair reason is the transition's.
        assert updated.repair_reason == DISPATCH_FAILED_TRANSITION.reason


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
    checkpointer: AsyncSqliteSaver,
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
        _saturated_worker(checkpointer) as worker_client,
        session_factory() as session,
    ):
        pending = await get_permission_request(session, request_id)
        assert pending is not None
        result = await respond_to_permission(
            session,
            permission=pending,
            response=PermissionInput(request_id, "allow_once", "capacity-retry"),
            transport=DispatchTransport(
                worker_client=worker_client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30.0
                ),
                worker_spawner=adopted_spawner(),
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
        pending = await get_permission_request(session, request_id)
        assert pending is not None
        result = await respond_to_permission(
            session,
            permission=pending,
            response=PermissionInput(request_id, "allow_once", "unreachable-retry"),
            transport=DispatchTransport(
                worker_client=worker_client,
                circuit_breaker=WorkerCircuitBreaker(
                    failure_threshold=3, recovery_timeout=30.0
                ),
                worker_spawner=adopted_spawner("http://127.0.0.1:9"),
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
