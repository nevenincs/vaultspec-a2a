"""Current-schema recovery proofs for direct control actions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select

from ...conftest import SqlitePosture
from ...database import (
    RecoveryAttemptModel,
    ThreadStatusElectionOutcome,
    create_control_action,
    create_thread,
    elect_thread_status,
    get_control_action_by_dispatch_id,
    get_thread,
    mark_control_action_applied,
    thread_write_expectation,
)
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...testing import DEFAULT_TEAM_PRESET, adopted_spawner, current_execution_metadata
from ...thread import RunWriteAuthority
from ...thread.enums import (
    ControlActionResultStatus,
    ControlActionType,
    RecoveryCondition,
    RepairStatus,
    ThreadStatus,
)
from ...thread.executable_graph import FrozenGraphDefinition, freeze_graph_definition
from ...worker.app import create_worker_app
from ...worker.executor import Executor
from ...worker.ipc import WorkerBridge
from ..accepted_input import freeze_accepted_input
from ..circuit_breaker import WorkerCircuitBreaker
from ..config import settings
from ..direct_control_recovery import (
    DirectControlRecoverySummary,
    redrive_direct_control_actions,
)
from ..dispatch_receipts import prepare_graph_action_receipt
from ..execution_authority import resolve_execution_authority
from ..recovery import seed_recovery_attempts

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ...providers.team_selection import FrozenLaneAssignment

_TEST_INTERNAL_TOKEN = "direct-control-recovery-test-token"


pytestmark = pytest.mark.sqlite_engine(SqlitePosture.TRANSACTIONS)


@dataclass(frozen=True, slots=True)
class _AcceptedCase:
    thread_id: str
    action_type: ControlActionType
    status: ThreadStatus
    dispatch: DispatchRequest
    intent: dict[str, object]


def _graph_authority(
    workspace: Path,
) -> tuple[FrozenGraphDefinition, dict[str, FrozenLaneAssignment]]:
    definition = freeze_graph_definition(
        load_team_config(DEFAULT_TEAM_PRESET, workspace_root=workspace),
        workspace_root=workspace,
    )
    assignment = resolve_execution_authority(
        current_execution_metadata(workspace)
    ).model_assignment
    return definition, assignment


def _accepted_cases(workspace: Path) -> tuple[_AcceptedCase, ...]:
    definition, assignment = _graph_authority(workspace)
    return (
        _AcceptedCase(
            "message-run",
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
            ThreadStatus.RUNNING,
            DispatchRequest(
                dispatch_id="message-stable",
                action="ingest",
                thread_id="message-run",
                agent_id="vaultspec-supervisor",
                content="continue",
                workspace_root=str(workspace),
                team_preset=DEFAULT_TEAM_PRESET,
                graph_definition=definition,
                recursion_limit=37,
                model_assignment=assignment,
            ),
            {"content": "continue", "agent_id": "vaultspec-supervisor"},
        ),
        _AcceptedCase(
            "permission-run",
            ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            ThreadStatus.INPUT_REQUIRED,
            DispatchRequest(
                dispatch_id="permission-stable",
                action="resume",
                thread_id="permission-run",
                option_id={"option_id": "allow_once", "notes": None},
                workspace_root=str(workspace),
                team_preset=DEFAULT_TEAM_PRESET,
                graph_definition=definition,
                recursion_limit=37,
                model_assignment=assignment,
            ),
            {"option_id": "allow_once", "notes": None},
        ),
        _AcceptedCase(
            "cancel-run",
            ControlActionType.CANCEL,
            ThreadStatus.CANCELLING,
            DispatchRequest(
                dispatch_id="cancel-stable",
                action="cancel",
                thread_id="cancel-run",
                workspace_root=str(workspace),
                recursion_limit=37,
                model_assignment=assignment,
            ),
            {"reason": "user_requested"},
        ),
    )


async def _persist_case(
    db: AsyncSession,
    case: _AcceptedCase,
    *,
    deadline_at: datetime | None = None,
) -> None:
    authority = RunWriteAuthority(0, 1, case.action_type, case.dispatch.dispatch_id)
    await create_thread(
        db,
        thread_id=case.thread_id,
        status=case.status,
        team_preset=case.dispatch.team_preset,
        metadata=current_execution_metadata(Path(case.dispatch.workspace_root or ".")),
        write_authority=authority,
    )
    await create_control_action(
        db,
        thread_id=case.thread_id,
        action_type=case.action_type,
        idempotency_key=f"accepted:{case.thread_id}",
        dispatch_id=case.dispatch.dispatch_id,
        payload=freeze_accepted_input(case.dispatch, intent=case.intent),
        recovery_deadline_at=deadline_at or datetime(2100, 1, 1, tzinfo=UTC),
    )
    if case.action_type is not ControlActionType.CANCEL:
        receipt = await prepare_graph_action_receipt(
            db,
            thread_id=case.thread_id,
            dispatch_id=case.dispatch.dispatch_id,
        )
        assert receipt is not None


async def _recovery_attempt(
    db: AsyncSession, thread_id: str
) -> RecoveryAttemptModel | None:
    """Read the run's one durable retry record as it is stored."""
    return await db.scalar(
        select(RecoveryAttemptModel).where(RecoveryAttemptModel.thread_id == thread_id)
    )


async def _run_recovery(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[DirectControlRecoverySummary, list[dict[str, object]]]:
    received: list[dict[str, object]] = []
    app = FastAPI()

    @app.post("/dispatch")
    async def receive(request: Request) -> JSONResponse:
        received.append(await request.json())
        return JSONResponse({"status": "dispatched"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://worker"
    ) as client:
        summary = await redrive_direct_control_actions(
            session_factory,
            worker_client=client,
            circuit_breaker=WorkerCircuitBreaker(
                failure_threshold=3, recovery_timeout=30
            ),
            worker_spawner=adopted_spawner(),
            trace_headers=None,
        )
    return summary, received


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ThreadStatus.CANCELLING, ThreadStatus.RECONCILING])
async def test_cancel_recovery_preserves_receipt_in_startup_state(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    status: ThreadStatus,
) -> None:
    case = _accepted_cases(tmp_path)[2]
    case = _AcceptedCase(
        case.thread_id, case.action_type, status, case.dispatch, case.intent
    )
    async with session_factory() as db:
        await _persist_case(db, case)
        await db.commit()

    summary, received = await _run_recovery(session_factory)
    assert summary.dispatched == 1
    assert summary.conflicted == summary.refused == 0
    assert [item["dispatch_id"] for item in received] == ["cancel-stable"]
    async with session_factory() as db:
        thread = await get_thread(db, case.thread_id)
        action = await get_control_action_by_dispatch_id(
            db, thread_id=case.thread_id, dispatch_id="cancel-stable"
        )
        assert thread is not None and thread.status == status.value
        assert thread.writer_action_receipt_id == "cancel-stable"
        assert action is not None and action.applied_at is None


@pytest.mark.asyncio
async def test_current_message_permission_and_cancel_redrive_stable_ids(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cases = _accepted_cases(tmp_path)
    async with session_factory() as db:
        for case in cases:
            await _persist_case(db, case)
        await db.commit()

    summary, received = await _run_recovery(session_factory)

    assert summary.examined == 3
    assert summary.dispatched == 3
    assert summary.refused == 0
    assert summary.conflicted == 0
    assert {item["dispatch_id"] for item in received} == {
        "message-stable",
        "permission-stable",
        "cancel-stable",
    }
    delivered = {str(item["dispatch_id"]): item for item in received}
    assert delivered["message-stable"]["action"] == "ingest"
    assert delivered["message-stable"]["content"] == "continue"
    assert delivered["message-stable"]["agent_id"] == "vaultspec-supervisor"
    assert delivered["message-stable"]["recursion_limit"] == 37
    assert delivered["message-stable"]["team_preset"] == DEFAULT_TEAM_PRESET
    assert delivered["message-stable"]["graph_action_receipt"] is not None
    assert delivered["permission-stable"]["action"] == "resume"
    assert delivered["permission-stable"]["option_id"] == {
        "option_id": "allow_once",
        "notes": None,
    }
    assert delivered["permission-stable"]["graph_action_receipt"] is not None
    assert delivered["cancel-stable"]["action"] == "cancel"
    assert delivered["cancel-stable"]["graph_action_receipt"] is None


@pytest.mark.asyncio
async def test_unavailable_project_refuses_graph_action_but_allows_cancel(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    missing = tmp_path / "deleted-project"
    cases = list(_accepted_cases(tmp_path))
    graph_case = cases[1]
    graph_case = _AcceptedCase(
        graph_case.thread_id,
        graph_case.action_type,
        graph_case.status,
        graph_case.dispatch.model_copy(update={"workspace_root": str(missing)}),
        graph_case.intent,
    )
    cancel_case = cases[2]
    cancel_case = _AcceptedCase(
        cancel_case.thread_id,
        cancel_case.action_type,
        cancel_case.status,
        cancel_case.dispatch.model_copy(update={"workspace_root": str(missing)}),
        cancel_case.intent,
    )
    async with session_factory() as db:
        await _persist_case(db, graph_case)
        await _persist_case(db, cancel_case)
        await db.commit()

    summary, received = await _run_recovery(session_factory)

    assert summary.examined == 2
    assert summary.dispatched == 1
    assert summary.refused == 1
    assert [item["dispatch_id"] for item in received] == ["cancel-stable"]
    async with session_factory() as db:
        refused_action = await get_control_action_by_dispatch_id(
            db,
            thread_id=graph_case.thread_id,
            dispatch_id=graph_case.dispatch.dispatch_id,
        )
        refused_thread = await get_thread(db, graph_case.thread_id)
    assert refused_action is not None
    assert refused_action.applied_at is not None
    assert (
        refused_action.result_status
        == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )
    assert refused_thread is not None
    assert refused_thread.status == ThreadStatus.RECONCILING.value
    assert (
        refused_thread.repair_status
        == RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value
    )
    assert refused_thread.repair_reason is not None
    assert refused_thread.repair_reason.startswith("no_active_project:")


@pytest.mark.asyncio
async def test_older_accepted_action_loses_to_newer_exact_authority(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old = _accepted_cases(tmp_path)[1]
    async with session_factory() as db:
        await _persist_case(db, old)
        thread = await get_thread(db, old.thread_id)
        assert thread is not None
        expectation = thread_write_expectation(thread)
        newer = _accepted_cases(tmp_path)[2]
        newer_dispatch = newer.dispatch.model_copy(
            update={"thread_id": old.thread_id, "dispatch_id": "newer-cancel"}
        )
        await create_control_action(
            db,
            thread_id=old.thread_id,
            action_type=ControlActionType.CANCEL,
            idempotency_key="accepted:newer-cancel",
            dispatch_id="newer-cancel",
            payload=freeze_accepted_input(
                newer_dispatch, intent={"reason": "user_requested"}
            ),
            recovery_deadline_at=datetime(2100, 1, 1, tzinfo=UTC),
        )
        elected = await elect_thread_status(
            db,
            old.thread_id,
            expectation=expectation,
            status=ThreadStatus.CANCELLING,
            action_type=ControlActionType.CANCEL,
            action_receipt_id="newer-cancel",
        )
        assert elected.outcome is ThreadStatusElectionOutcome.WON
        await db.commit()

    summary, received = await _run_recovery(session_factory)

    assert summary.examined == 1
    assert summary.dispatched == 1
    assert summary.conflicted == 0
    assert [item["dispatch_id"] for item in received] == ["newer-cancel"]


@pytest.mark.asyncio
async def test_expired_run_is_quarantined_without_dispatch(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    case = _accepted_cases(tmp_path)[0]
    async with session_factory() as db:
        await _persist_case(
            db,
            case,
            deadline_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        accepted = await get_control_action_by_dispatch_id(
            db, thread_id=case.thread_id, dispatch_id=case.dispatch.dispatch_id
        )
        assert accepted is not None
        accepted.requested_at = datetime(2019, 1, 1, tzinfo=UTC)
        await db.commit()

    summary, received = await _run_recovery(session_factory)

    assert not received
    assert summary.examined == 1
    assert summary.refused == 1
    async with session_factory() as db:
        action = await get_control_action_by_dispatch_id(
            db, thread_id=case.thread_id, dispatch_id=case.dispatch.dispatch_id
        )
        thread = await get_thread(db, case.thread_id)
        attempt = await _recovery_attempt(db, case.thread_id)
    assert action is not None and action.applied_at is not None
    assert thread is not None
    assert thread.status == ThreadStatus.RECONCILING.value
    assert thread.repair_reason is not None
    assert thread.repair_reason.startswith("deadline_exceeded:")
    assert attempt is not None
    assert attempt.condition == RecoveryCondition.DEADLINE_EXCEEDED.value
    assert attempt.settled_at is not None


@pytest.mark.asyncio
async def test_applied_action_wins_over_deadline_quarantine(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    case = _accepted_cases(tmp_path)[0]
    async with session_factory() as db:
        await _persist_case(
            db,
            case,
            deadline_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        action = await get_control_action_by_dispatch_id(
            db, thread_id=case.thread_id, dispatch_id=case.dispatch.dispatch_id
        )
        assert action is not None
        await mark_control_action_applied(
            db,
            action.id,
            applied_at=datetime(2019, 1, 1, tzinfo=UTC),
        )
        await db.commit()

    summary, received = await _run_recovery(session_factory)

    assert not received
    assert summary.examined == 0
    assert summary.refused == 0
    async with session_factory() as db:
        thread = await get_thread(db, case.thread_id)
        attempt = await _recovery_attempt(db, case.thread_id)
    assert thread is not None
    assert thread.status == ThreadStatus.RUNNING.value
    assert thread.repair_status == RepairStatus.HEALTHY.value
    assert attempt is None


@pytest.mark.asyncio
async def test_corrupt_accepted_input_is_atomically_quarantined(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    case = _accepted_cases(tmp_path)[0]
    async with session_factory() as db:
        await _persist_case(db, case)
        action = await get_control_action_by_dispatch_id(
            db, thread_id=case.thread_id, dispatch_id=case.dispatch.dispatch_id
        )
        assert action is not None
        action.payload_json = "{not-json"
        await db.commit()

    summary, received = await _run_recovery(session_factory)

    assert not received
    assert summary.examined == 1
    assert summary.refused == 1
    assert summary.conflicted == 0
    async with session_factory() as db:
        action = await get_control_action_by_dispatch_id(
            db, thread_id=case.thread_id, dispatch_id=case.dispatch.dispatch_id
        )
        thread = await get_thread(db, case.thread_id)
        attempt = await _recovery_attempt(db, case.thread_id)
    assert action is not None
    assert action.applied_at is not None
    assert (
        action.result_status == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )
    assert thread is not None
    assert thread.status == ThreadStatus.RECONCILING.value
    assert thread.repair_reason is not None
    assert thread.repair_reason.startswith("incompatible_state:")
    assert attempt is not None
    assert attempt.condition == RecoveryCondition.INCOMPATIBLE_STATE.value
    assert attempt.settled_at is not None


@pytest.mark.asyncio
async def test_missing_accepted_action_quarantines_its_exact_run(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    case = _accepted_cases(tmp_path)[0]
    async with session_factory() as db:
        await _persist_case(db, case)
        now = datetime.now(UTC)
        await db.commit()
    async with session_factory() as db:
        assert await seed_recovery_attempts(db, observed_at=now, limit=1) == 1
        action = await get_control_action_by_dispatch_id(
            db, thread_id=case.thread_id, dispatch_id=case.dispatch.dispatch_id
        )
        assert action is not None
        await db.delete(action)
        await db.commit()

    summary, received = await _run_recovery(session_factory)

    assert not received
    assert summary.examined == 1
    assert summary.refused == 1
    async with session_factory() as db:
        thread = await get_thread(db, case.thread_id)
        attempt = await _recovery_attempt(db, case.thread_id)
    assert thread is not None
    # With the receipt absent there is no lawful evidence for a lifecycle
    # election. The last proven status remains while readiness blocks execution.
    assert thread.status == ThreadStatus.RUNNING.value
    assert (
        thread.execution_readiness == RepairStatus.OPERATOR_INTERVENTION_REQUIRED.value
    )
    assert thread.repair_reason is not None
    assert thread.repair_reason.startswith("incompatible_state:")
    assert attempt is not None
    assert attempt.condition == RecoveryCondition.INCOMPATIBLE_STATE.value
    assert attempt.settled_at is not None


@pytest.mark.asyncio
async def test_capacity_failure_waits_for_durable_next_eligibility(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    case = _accepted_cases(tmp_path)[0]
    async with session_factory() as db:
        await _persist_case(db, case)
        await db.commit()

    received = 0
    app = FastAPI()

    @app.post("/dispatch")
    async def receive() -> JSONResponse:
        nonlocal received
        received += 1
        if received == 1:
            return JSONResponse({"detail": "at capacity"}, status_code=429)
        return JSONResponse({"status": "dispatched"})

    breaker = WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30)
    spawner = adopted_spawner()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://worker"
    ) as client:
        first = await redrive_direct_control_actions(
            session_factory,
            worker_client=client,
            circuit_breaker=breaker,
            worker_spawner=spawner,
            trace_headers=None,
        )
        second = await redrive_direct_control_actions(
            session_factory,
            worker_client=client,
            circuit_breaker=breaker,
            worker_spawner=spawner,
            trace_headers=None,
        )
        async with session_factory() as db:
            attempt = await _recovery_attempt(db, case.thread_id)
            assert attempt is not None
            assert attempt.condition == RecoveryCondition.AT_CAPACITY.value
            assert attempt.attempt_count == 2
            assert attempt.settled_at is None
            attempt.next_eligible_at = attempt.created_at
            await db.commit()
        third = await redrive_direct_control_actions(
            session_factory,
            worker_client=client,
            circuit_breaker=breaker,
            worker_spawner=spawner,
            trace_headers=None,
        )
        async with session_factory() as db:
            action = await get_control_action_by_dispatch_id(
                db,
                thread_id=case.thread_id,
                dispatch_id=case.dispatch.dispatch_id,
            )
            attempt = await _recovery_attempt(db, case.thread_id)
            assert action is not None and attempt is not None
            await mark_control_action_applied(db, action.id)
            attempt.next_eligible_at = attempt.created_at
            await db.commit()
        fourth = await redrive_direct_control_actions(
            session_factory,
            worker_client=client,
            circuit_breaker=breaker,
            worker_spawner=spawner,
            trace_headers=None,
        )

    assert first.deferred == 1
    assert second.examined == 0
    assert third.dispatched == 1
    assert fourth.examined == 1
    assert fourth.dispatched == 0
    assert received == 2
    async with session_factory() as db:
        attempt = await _recovery_attempt(db, case.thread_id)
    assert attempt is not None and attempt.settled_at is not None


@pytest.fixture
def _dispatch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give both sides of real worker dispatch the current IPC credential."""
    monkeypatch.setattr(settings, "internal_token", _TEST_INTERNAL_TOKEN)


@asynccontextmanager
async def _worker_already_running(
    checkpoint_path: Path, thread_id: str
) -> AsyncGenerator[httpx.AsyncClient]:
    """Serve the production worker app with one run's slot genuinely taken.

    The slot is taken through the executor's own reservation verb, so the 409
    the recovery pass meets is the refusal the worker composes for a run it is
    already executing rather than a status written here.
    """
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        await saver.setup()
        bridge = WorkerBridge("http://control", "direct-control-recovery-test")
        executor = Executor(saver, bridge)
        reservation, _reason = await executor.reserve_dispatch_capacity(thread_id)
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


@pytest.mark.asyncio
@pytest.mark.usefixtures("_dispatch_auth")
async def test_a_busy_worker_keeps_the_action_claim_for_the_run_it_is_running(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A worker executing this run is reporting work in flight, not refusing it.

    Ownership is given back only for a delivery proven not to have happened.
    The worker here holds this exact run's slot, which is evidence that the
    accepted action reached it: releasing the claim would let the next
    dispatcher redeliver the very work being executed, so the claim is held
    until the application receipt settles it or the lease expires. The retry is
    still scheduled, under the condition the worker actually served.
    """
    case = _accepted_cases(tmp_path)[0]
    async with session_factory() as db:
        await _persist_case(db, case)
        await db.commit()

    async with _worker_already_running(
        tmp_path / "busy-worker.db", case.thread_id
    ) as client:
        summary = await redrive_direct_control_actions(
            session_factory,
            worker_client=client,
            circuit_breaker=WorkerCircuitBreaker(
                failure_threshold=3, recovery_timeout=30
            ),
            worker_spawner=adopted_spawner(),
            trace_headers=None,
        )

    assert summary.deferred == 1
    async with session_factory() as db:
        action = await get_control_action_by_dispatch_id(
            db,
            thread_id=case.thread_id,
            dispatch_id=case.dispatch.dispatch_id,
        )
        attempt = await _recovery_attempt(db, case.thread_id)
    assert action is not None
    assert action.applied_at is None
    assert action.claim_token is not None
    assert action.claim_expires_at is not None
    assert attempt is not None
    assert attempt.condition == RecoveryCondition.RUN_BUSY.value
    assert attempt.settled_at is None
