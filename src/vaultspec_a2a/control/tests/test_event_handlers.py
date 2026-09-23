"""Focused replay/idempotency tests for worker->gateway event handlers."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import Response
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...api.schemas.events import PermissionRequestEvent
from ...conftest import materialize_schema
from ...control._permission_response_contract import permission_response_action_key
from ...control.accepted_input import freeze_accepted_input
from ...control.dispatch_receipts import prepare_graph_action_receipt
from ...control.event_handlers import (
    _handle_permission_event,
    _handle_progress_event,
    _handle_terminal_event,
)
from ...database import (
    ThreadStatusElectionOutcome,
    acquire_control_action_lease,
    create_control_action,
    create_thread,
    elect_thread_status,
    get_permission_request,
    record_permission_request,
    record_permission_response_submission,
    set_thread_approval_state,
    successor_thread_write_authority,
    thread_write_expectation,
)
from ...database.models import ControlActionModel, RunWriteAuthority, ThreadModel
from ...database.session import configure_sqlite_transactions
from ...graph.enums import ServerEventType
from ...ipc.schemas import DispatchRequest
from ...team.team_config import load_team_config
from ...tests._write_authority import make_test_write_authority
from ...thread.action_receipts import GraphActionReceipt, GraphCompletionReceipt
from ...thread.constants import MAX_PERMISSION_DESCRIPTION_CHARS
from ...thread.enums import ControlActionResultStatus, ControlActionType, ThreadStatus
from ...thread.executable_graph import freeze_graph_definition
from ...thread.failure_evidence import GraphFailureEvidence, failure_detail_fingerprint
from ...worker.ipc import WorkerBridge


@dataclass(frozen=True, slots=True)
class _SeedActionSpec:
    action_type: ControlActionType
    idempotency_key: str
    request_id: str | None = None
    completed: bool = False


async def _seed_unapplied_leased_action(
    session: AsyncSession,
    checkpointer: InMemorySaver,
    *,
    thread_id: str,
    spec: _SeedActionSpec,
) -> tuple[ControlActionModel, GraphActionReceipt, str]:
    """Create current accepted graph authority and its unapplied lease."""
    dispatch_id = uuid4().hex
    graph_definition = freeze_graph_definition(
        load_team_config("mock-success-single", workspace_root=Path.cwd()),
        workspace_root=Path.cwd(),
    )
    intent: dict[str, object]
    if spec.action_type is ControlActionType.MESSAGE_FOLLOWUP_REQUESTED:
        dispatch = DispatchRequest(
            dispatch_id=dispatch_id,
            action="ingest",
            thread_id=thread_id,
            content="current follow-up",
            workspace_root=str(Path.cwd()),
            team_preset="mock-success-single",
            graph_definition=graph_definition,
            recursion_limit=25,
        )
        intent = {
            "content": "current follow-up",
            "agent_id": dispatch.agent_id,
        }
    elif spec.action_type is ControlActionType.PERMISSION_RESPONSE_SUBMITTED:
        dispatch = DispatchRequest(
            dispatch_id=dispatch_id,
            action="resume",
            thread_id=thread_id,
            option_id={"option_id": "allow_once", "notes": None},
            workspace_root=str(Path.cwd()),
            team_preset="mock-success-single",
            graph_definition=graph_definition,
            recursion_limit=25,
        )
        intent = {"option_id": "allow_once", "notes": None}
    else:
        raise ValueError(f"unsupported graph action fixture: {spec.action_type}")
    action = await create_control_action(
        session,
        thread_id=thread_id,
        action_type=spec.action_type,
        idempotency_key=spec.idempotency_key,
        request_id=spec.request_id,
        dispatch_id=dispatch_id,
        payload=freeze_accepted_input(dispatch, intent=intent),
        recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    thread = await session.get(ThreadModel, thread_id)
    assert thread is not None
    expectation = thread_write_expectation(thread)
    election = await elect_thread_status(
        session,
        thread_id,
        expectation=expectation,
        status=expectation.status,
        successor=successor_thread_write_authority(
            expectation,
            action_type=spec.action_type,
            action_receipt_id=dispatch_id,
        ),
    )
    assert election.outcome is ThreadStatusElectionOutcome.WON
    receipt = await prepare_graph_action_receipt(
        session, thread_id=thread_id, dispatch_id=dispatch_id
    )
    assert receipt is not None
    checkpoint = empty_checkpoint()
    checkpoint_id = uuid4().hex
    checkpoint["id"] = checkpoint_id
    checkpoint["channel_values"] = {
        "active_graph_action_receipt": receipt.model_dump(mode="json"),
        "graph_action_receipts": {receipt.dispatch_id: receipt.model_dump(mode="json")},
    }
    if spec.completed:
        completion = GraphCompletionReceipt(
            schema_version="graph-completion-v1",
            action=receipt,
            outcome="completed",
        )
        checkpoint["channel_values"]["graph_completion_receipts"] = {
            receipt.dispatch_id: completion.model_dump(mode="json")
        }
    checkpoint["channel_versions"] = {
        "active_graph_action_receipt": 1,
        "graph_action_receipts": 1,
    }
    if spec.completed:
        checkpoint["channel_versions"]["graph_completion_receipts"] = 1
    await checkpointer.aput(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        checkpoint["channel_versions"],
    )
    acquired = await acquire_control_action_lease(
        session,
        action.id,
        claim_token=f"test-claim:{action.id}",
        claim_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert acquired
    return action, receipt, checkpoint_id


@pytest.mark.asyncio
async def test_dispatch_application_receipt_settles_exact_message_action(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    """A worker receipt settles its named follow-up, never another action."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="message-receipt-thread",
            status="running",
        )
        other, _other_receipt, _other_checkpoint = await _seed_unapplied_leased_action(
            session,
            checkpointer,
            thread_id=thread.id,
            spec=_SeedActionSpec(
                action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                idempotency_key="message:other",
            ),
        )
        (
            expected,
            expected_receipt,
            expected_checkpoint,
        ) = await _seed_unapplied_leased_action(
            session,
            checkpointer,
            thread_id=thread.id,
            spec=_SeedActionSpec(
                action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                idempotency_key="message:expected",
            ),
        )
        await session.commit()

    await _handle_progress_event(
        thread.id,
        {
            "type": "dispatch_applied",
            "dispatch_id": expected.dispatch_id,
            "action": "ingest",
            "graph_action_receipt": expected_receipt.model_dump(mode="json"),
            "checkpoint_id": expected_checkpoint,
        },
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as session:
        expected_row = await session.get(ControlActionModel, expected.id)
        other_row = await session.get(ControlActionModel, other.id)
        stored_thread = await session.get(ThreadModel, thread.id)

    assert expected_row is not None
    assert expected_row.applied_at is not None
    assert expected_row.claim_token is None
    assert other_row is not None
    assert other_row.applied_at is None
    assert other_row.claim_token is not None
    assert stored_thread is not None
    assert stored_thread.last_applied_action == "message_followup_applied"


@pytest.mark.asyncio
async def test_dispatch_application_receipt_requires_named_durable_checkpoint(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="missing-application-checkpoint",
            status="running",
        )
        action, receipt, _checkpoint_id = await _seed_unapplied_leased_action(
            session,
            checkpointer,
            thread_id=thread.id,
            spec=_SeedActionSpec(
                action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                idempotency_key="message:missing-checkpoint",
            ),
        )
        await session.commit()

    await _handle_progress_event(
        thread.id,
        {
            "type": "dispatch_applied",
            "dispatch_id": action.dispatch_id,
            "action": "ingest",
            "graph_action_receipt": receipt.model_dump(mode="json"),
            "checkpoint_id": uuid4().hex,
        },
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as session:
        stored = await session.get(ControlActionModel, action.id)
    assert stored is not None
    assert stored.applied_at is None
    assert stored.claim_token is not None


@pytest_asyncio.fixture
async def engine(tmp_path_factory: pytest.TempPathFactory):
    """Create a file-backed engine for replay-focused control tests."""
    case_dir = tmp_path_factory.mktemp("control-event-handler-db")
    db_file = case_dir / "test.db"
    materialize_schema(Path(db_file))
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Provide an async session factory bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def checkpointer() -> InMemorySaver:
    """Keep exact incorporated checkpoints for application receipts."""
    return InMemorySaver()


async def _seed_current_cancel(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    dispatch_id: str,
    status: ThreadStatus = ThreadStatus.CANCELLING,
) -> str:
    async with session_factory() as session:
        await create_thread(
            session,
            thread_id=thread_id,
            status=status,
            write_authority=RunWriteAuthority(
                0, 1, ControlActionType.CANCEL, dispatch_id
            ),
        )
        action = await create_control_action(
            session,
            thread_id=thread_id,
            action_type=ControlActionType.CANCEL,
            idempotency_key=f"cancel:{thread_id}",
            dispatch_id=dispatch_id,
            payload=freeze_accepted_input(
                DispatchRequest(
                    dispatch_id=dispatch_id,
                    action="cancel",
                    thread_id=thread_id,
                    recursion_limit=25,
                ),
                intent={"cancel": True},
            ),
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        acquired = await acquire_control_action_lease(
            session,
            action.id,
            claim_token=f"claim:{thread_id}",
            claim_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        assert acquired
        await session.commit()
        return action.id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ThreadStatus.CANCELLING, ThreadStatus.RECONCILING])
@pytest.mark.parametrize(
    ("outcome", "result_status"),
    [
        ("ceased", ControlActionResultStatus.CANCELLED_CEASED),
        (
            "no_active_work",
            ControlActionResultStatus.CANCELLED_NO_ACTIVE_WORK,
        ),
    ],
)
async def test_exact_cancellation_evidence_settles_current_action(
    session_factory: async_sessionmaker[AsyncSession],
    outcome: str,
    result_status: ControlActionResultStatus,
    status: ThreadStatus,
) -> None:
    thread_id = f"cancel-evidence-{outcome}"
    dispatch_id = f"dispatch-{outcome}"
    action_id = await _seed_current_cancel(
        session_factory, thread_id=thread_id, dispatch_id=dispatch_id, status=status
    )

    payload: dict[str, object] = {
        "event_type": "thread_terminal",
        "status": "cancelled",
        "cancellation_evidence": {
            "schema_version": "cancellation-evidence-v1",
            "dispatch_id": dispatch_id,
            "outcome": outcome,
        },
    }
    for _delivery in range(2):
        await _handle_terminal_event(
            thread_id, payload, session_factory=session_factory
        )

    async with session_factory() as session:
        action = await session.get(ControlActionModel, action_id)
        thread = await session.get(ThreadModel, thread_id)
    assert action is not None
    assert action.applied_at is not None
    assert action.result_status == result_status.value
    assert action.claim_token is None
    assert thread is not None
    assert thread.status == ThreadStatus.CANCELLED.value
    assert thread.run_revision == 1
    assert thread.last_applied_action == ControlActionType.CANCEL.value


def _busy_once_control_app(
    sessions: async_sessionmaker[AsyncSession],
    blocker: sqlite3.Connection,
    attempts: list[dict[str, Any]],
    busy_errors: list[str],
) -> FastAPI:
    """Serve the event batch route, refusing once while *blocker* holds the lock."""
    app = FastAPI()

    @app.post("/internal/events/batch")
    async def receive_batch(request: Request) -> Response:
        body = cast("dict[str, Any]", await request.json())
        attempts.append(body)
        event = cast("dict[str, Any]", body["events"][0])
        try:
            await _handle_terminal_event(
                event["thread_id"],
                event["payload"],
                session_factory=sessions,
            )
        except OperationalError as exc:
            if not isinstance(exc.orig, sqlite3.OperationalError):
                raise
            busy_errors.append(str(exc.orig))
            blocker.rollback()
            return Response(status_code=503)
        return Response(
            content='{"status":"ok"}',
            media_type="application/json",
        )

    return app


async def _assert_cancel_applied(db_file: Path, action_id: str, thread_id: str) -> None:
    """Read the durable outcome back through a fresh engine and check it."""
    verification_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    verification_sessions = async_sessionmaker(
        verification_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    try:
        async with verification_sessions() as session:
            action = await session.get(ControlActionModel, action_id)
            thread = await session.get(ThreadModel, thread_id)
    finally:
        await verification_engine.dispose()

    assert action is not None
    assert action.applied_at is not None
    assert (
        action.result_status == ControlActionResultStatus.CANCELLED_NO_ACTIVE_WORK.value
    )
    assert action.claim_token is None
    assert thread is not None
    assert thread.status == ThreadStatus.CANCELLED.value
    assert thread.run_revision == 1
    assert thread.last_applied_action == ControlActionType.CANCEL.value


@pytest.mark.asyncio
async def test_terminal_election_busy_retries_same_receipt_once(tmp_path: Path) -> None:
    """A busy terminal election can recover through the bounded bridge retry."""
    db_file = materialize_schema(tmp_path / "terminal-election-contention.db")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"timeout": 0},
    )
    configure_sqlite_transactions(engine)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    blocker = sqlite3.connect(str(db_file), isolation_level=None, timeout=0)
    attempts: list[dict[str, Any]] = []
    busy_errors: list[str] = []
    app = _busy_once_control_app(sessions, blocker, attempts, busy_errors)

    action_id = await _seed_current_cancel(
        sessions,
        thread_id="terminal-election-contention",
        dispatch_id="terminal-election-receipt",
    )
    payload: dict[str, object] = {
        "event_type": "thread_terminal",
        "status": "cancelled",
        "cancellation_evidence": {
            "schema_version": "cancellation-evidence-v1",
            "dispatch_id": "terminal-election-receipt",
            "outcome": "no_active_work",
        },
    }

    blocker.execute("PRAGMA journal_mode=WAL")
    blocker.execute("PRAGMA busy_timeout=0")
    blocker.execute("BEGIN IMMEDIATE")

    bridge = WorkerBridge("http://control", "terminal-election-contention")
    await bridge._client.aclose()
    bridge._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://control",
    )
    try:
        await bridge.send_event("terminal-election-contention", payload)
        assert await bridge.flush_events()
    finally:
        await bridge.close()
        blocker.close()
        await engine.dispose()

    assert busy_errors == ["database is locked"]
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    first_event = cast("dict[str, Any]", attempts[0]["events"][0])
    assert first_event["payload"]["cancellation_evidence"]["dispatch_id"] == (
        "terminal-election-receipt"
    )

    await _assert_cancel_applied(db_file, action_id, "terminal-election-contention")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("evidence_dispatch_id", "expected_thread_status"),
    [
        (None, ThreadStatus.CANCELLING),
        ("different-dispatch", ThreadStatus.CANCELLING),
        (None, ThreadStatus.RECONCILING),
        ("different-dispatch", ThreadStatus.RECONCILING),
    ],
)
async def test_unproven_cancelled_terminal_does_not_settle_cancel_action(
    session_factory: async_sessionmaker[AsyncSession],
    evidence_dispatch_id: str | None,
    expected_thread_status: ThreadStatus,
) -> None:
    thread_id = f"unproven-cancel-{evidence_dispatch_id or 'absent'}"
    dispatch_id = f"dispatch-{thread_id}"
    action_id = await _seed_current_cancel(
        session_factory,
        thread_id=thread_id,
        dispatch_id=dispatch_id,
        status=expected_thread_status,
    )
    payload: dict[str, object] = {
        "event_type": "thread_terminal",
        "status": "cancelled",
    }
    if evidence_dispatch_id is not None:
        payload["cancellation_evidence"] = {
            "schema_version": "cancellation-evidence-v1",
            "dispatch_id": evidence_dispatch_id,
            "outcome": "ceased",
        }

    await _handle_terminal_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )

    async with session_factory() as session:
        action = await session.get(ControlActionModel, action_id)
        thread = await session.get(ThreadModel, thread_id)
    assert action is not None
    assert action.applied_at is None
    assert action.result_status == ControlActionResultStatus.ACCEPTED_NOT_APPLIED.value
    assert action.claim_token is not None
    assert thread is not None
    assert thread.status == expected_thread_status.value
    assert thread.last_applied_action is None


@pytest.mark.asyncio
async def test_replayed_permission_resolved_is_ignored_after_progress_apply(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    """A replayed permission_resolved event must not append a second applied action."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Replay Guard",
            status="input_required",
        )
        request_id = f"{thread.id}:perm-1"
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread.id,
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
        await record_permission_response_submission(
            session,
            request_id=request_id,
            option_id="allow_once",
            idempotency_key="response-1",
        )
        (
            submitted,
            submitted_receipt,
            submitted_checkpoint,
        ) = await _seed_unapplied_leased_action(
            session,
            checkpointer,
            thread_id=thread.id,
            spec=_SeedActionSpec(
                action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
                idempotency_key=permission_response_action_key(request_id),
                request_id=request_id,
            ),
        )
        await session.commit()

    await _handle_progress_event(
        thread.id,
        {
            "type": "dispatch_applied",
            "dispatch_id": submitted.dispatch_id,
            "action": "resume",
            "graph_action_receipt": submitted_receipt.model_dump(mode="json"),
            "checkpoint_id": submitted_checkpoint,
        },
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.request_status == "applied"
        actions = (
            (
                await session.execute(
                    select(ControlActionModel).where(
                        ControlActionModel.request_id == request_id,
                        ControlActionModel.action_type == "permission_response_applied",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(actions) == 1
        assert actions[0].idempotency_key == (
            f"permission-response-applied:{request_id}"
        )
        submitted_action = await session.get(ControlActionModel, submitted.id)
        assert submitted_action is not None
        assert submitted_action.applied_at is not None
        assert submitted_action.claim_token is None

    await _handle_permission_event(
        thread.id,
        {"type": "permission_resolved", "request_id": request_id},
        session_factory=session_factory,
    )

    async with session_factory() as session:
        actions = (
            (
                await session.execute(
                    select(ControlActionModel).where(
                        ControlActionModel.request_id == request_id,
                        ControlActionModel.action_type == "permission_response_applied",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(actions) == 1


@pytest.mark.asyncio
async def test_plan_approval_request_is_persisted_as_durable_pending_permission(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Supervisor plan approval interrupts must become durable pending rows."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Plan approval relay",
        )
        await session.commit()
        thread_id = thread.id

    request_id = f"{thread_id}:plan-approval-1"
    payload: dict[str, object] = {
        "type": "plan_approval_request",
        "request_id": request_id,
        "description": "Approve plan for feature 'audit-5'",
        "options": [
            {"option_id": "approve", "name": "Approve", "kind": "allow_once"},
            {"option_id": "reject", "name": "Reject", "kind": "reject_once"},
        ],
        "tool_call": "plan_approval",
    }

    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.pause_reason_type == "plan_approval_request"
        assert permission.request_status == "pending"
        assert permission.tool_call == "plan_approval"
        assert json.loads(permission.allowed_options_json) == payload["options"]

        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        assert thread.approval_status == "pending"
        assert thread.approval_request_id == request_id
        assert thread.run_revision == 1
        actions = (
            (
                await session.execute(
                    select(ControlActionModel).where(
                        ControlActionModel.thread_id == thread_id,
                        ControlActionModel.action_type
                        == ControlActionType.PERMISSION_REQUEST_CREATED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(actions) == 1
        assert thread.writer_action_receipt_id == actions[0].dispatch_id


@pytest.mark.asyncio
async def test_stale_permission_creation_replay_cannot_reclaim_newer_authority(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Stale permission replay",
        )
        await session.commit()
        thread_id = thread.id
    request_id = f"{thread_id}:stale-permission"
    payload: dict[str, object] = {
        "type": "permission_request",
        "request_id": request_id,
        "description": "Allow the first action?",
        "options": [{"option_id": "allow", "name": "Allow", "kind": "allow_once"}],
        "tool_call": "bash",
    }
    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )

    async with session_factory() as session:
        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        expectation = thread_write_expectation(thread)
        response = await create_control_action(
            session,
            thread_id=thread_id,
            action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
            request_id=request_id,
            idempotency_key=f"permission-response:{request_id}",
            payload={"option_id": "allow"},
            recovery_deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert response.dispatch_id is not None
        election = await elect_thread_status(
            session,
            thread_id,
            expectation=expectation,
            status=ThreadStatus.RUNNING,
            successor=successor_thread_write_authority(
                expectation,
                action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
                action_receipt_id=response.dispatch_id,
            ),
        )
        assert election.outcome is ThreadStatusElectionOutcome.WON
        await session.commit()
        expected_revision = thread.run_revision
        expected_generation = thread.writer_generation
        expected_receipt = thread.writer_action_receipt_id

    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )

    async with session_factory() as session:
        thread = await session.get(ThreadModel, thread_id)
    assert thread is not None
    assert thread.status == ThreadStatus.RUNNING.value
    assert thread.run_revision == expected_revision
    assert thread.writer_generation == expected_generation
    assert thread.writer_action_type == ControlActionType.PERMISSION_RESPONSE_SUBMITTED
    assert thread.writer_action_receipt_id == expected_receipt


@pytest.mark.asyncio
async def test_terminal_event_expires_pending_plan_approval_projection(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    """Checkpoint completion atomically expires pending approval residue."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Terminal plan approval",
            status=ThreadStatus.RUNNING,
        )
        thread_id = thread.id
        request_id = f"{thread_id}:plan-approval-terminal"
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="plan_approval_request",
            description="Approve the plan before completion",
            allowed_options=[
                {
                    "option_id": "approve",
                    "name": "Approve Plan",
                    "kind": "allow_once",
                }
            ],
            tool_call="plan_approval",
        )
        await set_thread_approval_state(
            session,
            thread_id,
            approval_status="pending",
            approval_request_id=request_id,
            approval_reason="Approve the plan before completion",
        )
        action, _receipt, _checkpoint = await _seed_unapplied_leased_action(
            session,
            checkpointer,
            thread_id=thread_id,
            spec=_SeedActionSpec(
                action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                idempotency_key="message:terminal-proof",
                completed=True,
            ),
        )
        await session.commit()

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.request_status == "expired_by_terminal_state"

        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        assert thread.status == "completed"
        assert thread.approval_status is None
        assert thread.approval_request_id is None
        assert thread.approval_reason is None
        assert thread.approval_response_action_id is None
        stored_action = await session.get(ControlActionModel, action.id)
        assert stored_action is not None
        assert stored_action.applied_at is not None


@pytest.mark.asyncio
async def test_failure_evidence_elects_only_its_current_graph_action(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    detail = "provider transport ended before a response"
    condition = "network_unreachable"
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            thread_id="exact-failure-thread",
            status=ThreadStatus.RUNNING,
        )
        action, receipt, _checkpoint = await _seed_unapplied_leased_action(
            session,
            checkpointer,
            thread_id=thread.id,
            spec=_SeedActionSpec(
                action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
                idempotency_key="message:exact-failure",
            ),
        )
        await session.commit()
    evidence = GraphFailureEvidence(
        schema_version="graph-failure-v1",
        action=receipt,
        outcome="failed",
        detail_fingerprint=failure_detail_fingerprint(detail),
        provider_condition=condition,
    )

    await _handle_terminal_event(
        thread.id,
        {
            "event_type": "thread_terminal",
            "status": "failed",
            "error_detail": "a different failure",
            "provider_condition": condition,
            "failure_evidence": evidence.model_dump(mode="json"),
        },
        session_factory=session_factory,
    )
    async with session_factory() as session:
        refused_thread = await session.get(ThreadModel, thread.id)
        refused_action = await session.get(ControlActionModel, action.id)
    assert refused_thread is not None
    assert refused_thread.status == ThreadStatus.RUNNING.value
    assert refused_action is not None
    assert refused_action.applied_at is None

    await _handle_terminal_event(
        thread.id,
        {
            "event_type": "thread_terminal",
            "status": "failed",
            "error_detail": detail,
            "provider_condition": condition,
            "failure_evidence": evidence.model_dump(mode="json"),
        },
        session_factory=session_factory,
    )

    async with session_factory() as session:
        stored_thread = await session.get(ThreadModel, thread.id)
        stored_action = await session.get(ControlActionModel, action.id)
    assert stored_thread is not None
    assert stored_thread.status == ThreadStatus.FAILED.value
    assert stored_thread.failure_reason == detail
    assert stored_thread.provider_condition == condition
    assert stored_action is not None
    assert stored_action.applied_at is not None


@pytest.mark.asyncio
async def test_document_approval_request_is_persisted_as_durable_pending_permission(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Document phase-gate interrupts must become durable pending rows.

    The research_adr phase gate parks with a ``document_approval_request``
    interrupt; the relay must record it as a verdict-style approval so the thread
    is INPUT_REQUIRED and the out-of-run verdict subscriber can correlate an
    engine verdict to the parked run.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Document approval relay",
        )
        await session.commit()
        thread_id = thread.id

    request_id = f"{thread_id}:document-approval-1"
    payload: dict[str, object] = {
        "type": "document_approval_request",
        "request_id": request_id,
        "phase": "research",
        "feature": "sse-reconnection",
        "description": "Approve the research document for feature 'sse-reconnection'",
        "options": [
            {"option_id": "approve", "name": "Approve Document", "kind": "allow_once"},
            {"option_id": "reject", "name": "Reject", "kind": "reject_once"},
        ],
    }

    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.pause_reason_type == "document_approval_request"
        assert permission.request_status == "pending"

        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        assert thread.status == "input_required"
        assert thread.approval_status == "pending"
        assert thread.approval_request_id == request_id


@dataclass(frozen=True, slots=True)
class _RejectionSpec:
    title: str
    pause_reason_type: str
    options: list[dict[str, object]]
    stamp_thread_rejected: bool


async def _answered_rejection(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
    *,
    spec: _RejectionSpec,
) -> tuple[str, str, str, GraphActionReceipt, str]:
    """Park a thread on a permission the human denied, awaiting settlement.

    Reproduces the real pre-settlement state: the response has been submitted
    (leaving the row ``answered_pending_apply``) and, for a plan approval, the
    control service has already stamped the thread REJECTED. Returns
    ``(thread_id, request_id)``.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title=spec.title,
            status="input_required",
        )
        request_id = f"{thread.id}:perm-reject"
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread.id,
            pause_reason_type=spec.pause_reason_type,
            description="Approve?",
            allowed_options=spec.options,
            tool_call=spec.pause_reason_type,
        )
        await record_permission_response_submission(
            session,
            request_id=request_id,
            option_id="reject",
            idempotency_key="response-reject-1",
        )
        (
            submitted,
            submitted_receipt,
            submitted_checkpoint,
        ) = await _seed_unapplied_leased_action(
            session,
            checkpointer,
            thread_id=thread.id,
            spec=_SeedActionSpec(
                action_type=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
                idempotency_key=permission_response_action_key(request_id),
                request_id=request_id,
            ),
        )
        if spec.stamp_thread_rejected:
            await set_thread_approval_state(
                session,
                thread.id,
                approval_status="rejected",
                approval_request_id=request_id,
                approval_reason="Approve?",
            )
        await session.commit()
        thread_id = thread.id
        dispatch_id = submitted.dispatch_id
        assert dispatch_id is not None

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.request_status == "answered_pending_apply"
        assert permission.response_option_id == "reject"

    return (
        thread_id,
        request_id,
        dispatch_id,
        submitted_receipt,
        submitted_checkpoint,
    )


_PLAN_OPTIONS: list[dict[str, object]] = [
    {"option_id": "approve", "name": "Approve Plan", "kind": "allow_once"},
    {"option_id": "reject", "name": "Reject — Revise Plan", "kind": "reject_once"},
]

# Kimi's real offer: the ACP wire spells the identity ``optionId``, and the option
# id ``"reject"`` is provider-defined -- it is not a PermissionOptionKind value.
_KIMI_OPTIONS: list[dict[str, object]] = [
    {"optionId": "approve", "kind": "allow_once"},
    {"optionId": "reject", "kind": "reject_once"},
]


@pytest.mark.asyncio
async def test_plan_rejection_survives_the_resolution_projection(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    """The resolution handler must not overwrite a denial with an approval.

    The control service stamps the thread REJECTED when the response is submitted.
    The ``permission_resolved`` projection then recomputes the verdict, and used to
    recompute it from a rejecting-*kind* set matched against the response option
    *id* -- so the bare ``"reject"`` the plan gate mints read as an approval and was
    written straight over the correct state.
    """
    (
        thread_id,
        request_id,
        _dispatch_id,
        _receipt,
        _checkpoint,
    ) = await _answered_rejection(
        session_factory,
        checkpointer,
        spec=_RejectionSpec(
            title="Plan rejection",
            pause_reason_type="plan_approval_request",
            options=_PLAN_OPTIONS,
            stamp_thread_rejected=True,
        ),
    )

    await _handle_permission_event(
        thread_id,
        {"type": "permission_resolved", "request_id": request_id},
        session_factory=session_factory,
    )

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.request_status == "rejected"

        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        assert thread.approval_status == "rejected"


@pytest.mark.asyncio
async def test_generic_progress_does_not_settle_an_answered_permission(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    """Uncorrelated progress must not settle any answered permission."""
    (
        thread_id,
        request_id,
        _dispatch_id,
        _receipt,
        _checkpoint,
    ) = await _answered_rejection(
        session_factory,
        checkpointer,
        spec=_RejectionSpec(
            title="Plan rejection via progress",
            pause_reason_type="plan_approval_request",
            options=_PLAN_OPTIONS,
            stamp_thread_rejected=True,
        ),
    )

    await _handle_progress_event(
        thread_id,
        {"type": "message_chunk", "content": "worker resumed"},
        session_factory=session_factory,
    )

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.request_status == "answered_pending_apply"

        thread = await session.get(ThreadModel, thread_id)
        assert thread is not None
        assert thread.approval_status == "rejected"


@pytest.mark.asyncio
async def test_a_kimi_tool_denial_settles_as_rejected_on_both_paths(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: InMemorySaver,
) -> None:
    """A provider-defined rejecting id must settle as a denial, not an approval.

    Kimi offers ``{"optionId": "reject", "kind": "reject_once"}`` -- the id is not
    its kind, which is what proves option ids are free-form. The denial is real:
    the ACP agent does receive ``"reject"`` and the tool is refused, so recording
    it as applied corrupts the journal rather than authorising anything.
    """
    (
        resolved_thread,
        resolved_request,
        _resolved_dispatch,
        _resolved_receipt,
        _resolved_checkpoint,
    ) = await _answered_rejection(
        session_factory,
        checkpointer,
        spec=_RejectionSpec(
            title="Kimi denial via resolution",
            pause_reason_type="bash",
            options=_KIMI_OPTIONS,
            stamp_thread_rejected=False,
        ),
    )
    await _handle_permission_event(
        resolved_thread,
        {"type": "permission_resolved", "request_id": resolved_request},
        session_factory=session_factory,
    )

    (
        progress_thread,
        progress_request,
        progress_dispatch,
        progress_receipt,
        progress_checkpoint,
    ) = await _answered_rejection(
        session_factory,
        checkpointer,
        spec=_RejectionSpec(
            title="Kimi denial via progress",
            pause_reason_type="bash",
            options=_KIMI_OPTIONS,
            stamp_thread_rejected=False,
        ),
    )
    await _handle_progress_event(
        progress_thread,
        {
            "type": "dispatch_applied",
            "dispatch_id": progress_dispatch,
            "action": "resume",
            "graph_action_receipt": progress_receipt.model_dump(mode="json"),
            "checkpoint_id": progress_checkpoint,
        },
        session_factory=session_factory,
        checkpointer=checkpointer,
    )

    async with session_factory() as session:
        for request_id in (resolved_request, progress_request):
            permission = await get_permission_request(session, request_id)
            assert permission is not None
            assert permission.request_status == "rejected"

        # A tool permission carries no plan approval state, so neither path may
        # invent one on the thread.
        for thread_id in (resolved_thread, progress_thread):
            thread = await session.get(ThreadModel, thread_id)
            assert thread is not None
            assert thread.approval_status is None


@pytest.mark.asyncio
async def test_permission_resolution_for_unknown_request_is_a_clean_noop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The resolution stage no-ops when no matching request row exists.

    After the split into a validation-then-dispatch handler, the resolution
    stage's missing-permission guard is exercised directly through the handler:
    a permission_resolved event for a request that was never recorded must
    settle nothing and append no control action.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Unknown Resolution",
        )
        await session.commit()
        thread_id = thread.id

    await _handle_permission_event(
        thread_id,
        {"type": "permission_resolved", "request_id": f"{thread_id}:never-recorded"},
        session_factory=session_factory,
    )

    async with session_factory() as session:
        actions = (await session.execute(select(ControlActionModel))).scalars().all()
        assert actions == []


@pytest.mark.asyncio
async def test_persisted_description_matches_what_the_stream_showed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The durable row holds exactly what the operator was streamed.

    Two readers truncate the same worker-supplied text at different times: this
    handler before writing the row, and the wire model when the frame is built.
    A reload re-reads the row, so a stream permitted to carry more than the row
    stores would show text live that vanishes on refresh - which is the bug the
    shared bound exists to prevent, and the one a second declaration reopens.

    Driven end to end against a real migrated SQLite database and the real wire
    model, from a single pathological description, so the two truncations are
    compared rather than each compared to a number written down twice.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Bounded Description",
            status="running",
        )
        await session.commit()

    oversize = "d" * (MAX_PERMISSION_DESCRIPTION_CHARS * 3)
    # The trap has to be live: a description already within the bound would let
    # this pass with both truncations removed.
    assert len(oversize) > MAX_PERMISSION_DESCRIPTION_CHARS

    await _handle_permission_event(
        thread.id,
        {
            "type": "permission_request",
            "request_id": "bounded-description",
            "description": oversize,
            "options": [],
        },
        session_factory=session_factory,
    )

    async with session_factory() as session:
        stored = await get_permission_request(session, "bounded-description")

    streamed = PermissionRequestEvent(
        type=ServerEventType.PERMISSION_REQUEST,
        thread_id=thread.id,
        agent_id="agent-1",
        timestamp=datetime.now(UTC),
        sequence=1,
        request_id="bounded-description",
        description=oversize,
        options=[],
    )

    assert stored is not None
    assert len(stored.description) < len(oversize)
    assert stored.description == streamed.description
