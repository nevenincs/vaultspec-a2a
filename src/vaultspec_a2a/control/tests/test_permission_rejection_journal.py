"""Every read-side permission rejection lands the same durable journal entry.

The permission state machine rejects a response from four distinct guards. Each
one records a ``REJECTED_INVALID_STATE`` control action carrying the original
reason and commits it before reporting, so a replay under the same idempotency
key reads the stored reason back instead of re-deciding it. These drive the real
``respond_to_permission`` against a real SQLite-backed session and assert both
halves of that contract - the returned result and the committed row - through a
second session, which only sees the row if the commit really happened.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.permission_service import respond_to_permission
from ...control.worker_management import LazyWorkerSpawner
from ...database import (
    create_thread,
    get_control_action_by_idempotency_key,
    get_permission_request,
    record_permission_request,
)
from ...database.models import ControlActionModel
from ...streaming.aggregator import EventAggregator
from ...thread.enums import ControlActionResultStatus, ThreadStatus

_CONFLICT = 409
_FORBIDDEN = 403

_OPTIONS: list[dict[str, object]] = [
    {"optionId": "allow_once", "name": "Allow once"},
    {"optionId": "reject_once", "name": "Reject once"},
]


@pytest_asyncio.fixture
async def engine(tmp_path_factory: pytest.TempPathFactory):
    """A file-backed engine so a second session reads only committed state."""
    case_dir = tmp_path_factory.mktemp("permission-rejection-db")
    db_file = case_dir / "test.db"
    materialize_schema(Path(db_file))
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _respond(
    session: AsyncSession,
    *,
    request_id: str,
    option_id: str,
):
    """Drive the real service with real (unreachable-worker) collaborators.

    Every rejection under test returns before any dispatch, so the worker never
    has to answer; the collaborators are real objects regardless.
    """
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9",
        worker_port=9,
        auto_spawn=False,
    )
    spawner.replace_process(None)
    circuit_breaker = WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client:
        return await respond_to_permission(
            session,
            request_id=request_id,
            option_id=option_id,
            idempotency_key=None,
            aggregator=EventAggregator(),
            circuit_breaker=circuit_breaker,
            worker_spawner=spawner,
            worker_client=client,
            recursion_limit=25,
            trace_headers=None,
        )


async def _seed_thread(session_factory) -> str:
    """Create a committed, non-terminal thread the guards can reject against."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="Permission rejection",
            status=ThreadStatus.INPUT_REQUIRED.value,
        )
        await session.commit()
    return thread.id


async def _assert_journalled(
    session_factory,
    *,
    action_id: str,
    expected_option_id: str,
    expected_error_detail: str,
) -> None:
    """The rejection row must be readable from a session that never wrote it."""
    async with session_factory() as reader:
        stored = await reader.get(ControlActionModel, action_id)
    assert stored is not None, "the rejection was reported but never committed"
    assert (
        stored.result_status == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )
    assert isinstance(stored.payload_json, str), (
        "the rejection reason must be persisted on the action"
    )
    payload = json.loads(stored.payload_json)
    assert payload == {
        "option_id": expected_option_id,
        "error_detail": expected_error_detail,
    }


@pytest.mark.asyncio
async def test_unknown_option_is_journalled_and_committed(session_factory) -> None:
    """The option-validation guard journals the rejection reason durably."""
    thread_id = await _seed_thread(session_factory)
    request_id = f"{thread_id}:perm-unknown"

    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="tool_permission_request",
            description="Run a tool",
            allowed_options=_OPTIONS,
        )
        await session.commit()

    async with session_factory() as session:
        result = await _respond(
            session, request_id=request_id, option_id="not-an-option"
        )

    assert result.accepted is False
    assert result.applied is False
    assert (
        result.action_status == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )
    assert result.error_detail == "Unknown permission option for this request"
    assert result.error_status_code == _CONFLICT
    assert result.action_id is not None
    assert result.idempotency_key is not None

    await _assert_journalled(
        session_factory,
        action_id=result.action_id,
        expected_option_id="not-an-option",
        expected_error_detail="Unknown permission option for this request",
    )


@pytest.mark.asyncio
async def test_superseded_request_is_journalled_and_committed(session_factory) -> None:
    """The active-interrupt guard journals through the same single path."""
    thread_id = await _seed_thread(session_factory)
    stale_request_id = f"{thread_id}:perm-stale"
    active_request_id = f"{thread_id}:perm-active"

    async with session_factory() as session:
        for request_id in (stale_request_id, active_request_id):
            await record_permission_request(
                session,
                request_id=request_id,
                thread_id=thread_id,
                pause_reason_type="tool_permission_request",
                description="Run a tool",
                allowed_options=_OPTIONS,
            )
        await session.commit()

    async with session_factory() as session:
        result = await _respond(
            session, request_id=stale_request_id, option_id="allow_once"
        )

    assert result.accepted is False
    assert (
        result.action_status == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )
    assert result.error_detail == "Permission request is no longer pending"
    assert result.error_status_code == _CONFLICT
    assert result.idempotency_key is not None
    assert result.action_id is not None

    await _assert_journalled(
        session_factory,
        action_id=result.action_id,
        expected_option_id="allow_once",
        expected_error_detail="Permission request is no longer pending",
    )


@pytest.mark.asyncio
async def test_optionless_request_is_journalled_and_committed(session_factory) -> None:
    """A request offering no usable options fails closed, and says so durably."""
    thread_id = await _seed_thread(session_factory)
    request_id = f"{thread_id}:perm-optionless"

    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="tool_permission_request",
            description="Run a tool",
            allowed_options=[],
        )
        await session.commit()

    async with session_factory() as session:
        result = await _respond(session, request_id=request_id, option_id="allow_once")

    assert result.accepted is False
    assert result.error_detail == "Permission request has no valid options"
    assert result.error_status_code == _CONFLICT
    assert result.idempotency_key is not None
    assert result.action_id is not None

    await _assert_journalled(
        session_factory,
        action_id=result.action_id,
        expected_option_id="allow_once",
        expected_error_detail="Permission request has no valid options",
    )


@pytest.mark.asyncio
async def test_replay_reads_the_stored_rejection_reason(session_factory) -> None:
    """The journal entry is what a replay answers from - not a re-decision.

    This is why the commit belongs inside the rejection path: the second call
    hits the idempotency dedup branch, which reads the stored ``error_detail``
    back out of the committed row.
    """
    thread_id = await _seed_thread(session_factory)
    request_id = f"{thread_id}:perm-replay"

    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="tool_permission_request",
            description="Run a tool",
            allowed_options=_OPTIONS,
        )
        await session.commit()

    async with session_factory() as session:
        first = await _respond(session, request_id=request_id, option_id="nope")
    async with session_factory() as session:
        replay = await _respond(session, request_id=request_id, option_id="nope")

    assert replay.action_id == first.action_id
    assert replay.idempotency_key == first.idempotency_key
    assert replay.error_detail == first.error_detail
    assert (
        replay.action_status == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )


@pytest.mark.asyncio
async def test_document_approval_pause_is_refused_not_journalled(
    session_factory,
) -> None:
    """The engine alone decides a document-approval pause; this route refuses.

    Before the amended edge contract was enforced here, this pause resolved
    into a REJECTED_INVALID_STATE row carrying an ``{"approved": bool}`` resume
    the document phase gate could not parse — a state fork against engine
    truth (D3/D6). The fix refuses before the idempotency and transition logic
    even runs, so nothing is journalled under the response's natural
    idempotency key and the permission is left exactly as durably pending as
    it was before the call — proving the retired approved-boolean resume is
    never constructed.
    """
    thread_id = await _seed_thread(session_factory)
    request_id = f"{thread_id}:perm-document"

    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type="document_approval_request",
            description="Approve document phase?",
            allowed_options=[
                {"optionId": "approve", "name": "Approve"},
                {"optionId": "reject", "name": "Reject"},
            ],
        )
        await session.commit()

    async with session_factory() as session:
        result = await _respond(session, request_id=request_id, option_id="approve")

    assert result.accepted is False
    assert result.applied is False
    assert result.error_status_code == _FORBIDDEN
    assert result.error_detail is not None
    assert "engine" in result.error_detail.lower()

    expected_idempotency_key = hashlib.sha256(
        f"{request_id}:approve".encode()
    ).hexdigest()
    async with session_factory() as reader:
        stored = await get_control_action_by_idempotency_key(
            reader, thread_id=thread_id, idempotency_key=expected_idempotency_key
        )
    assert stored is None, "a refused document-approval pause must journal nothing"

    async with session_factory() as reader:
        permission = await get_permission_request(reader, request_id)
    assert permission is not None
    assert permission.request_status == "pending"
