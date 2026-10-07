"""Every read-side permission rejection lands the same durable journal entry.

The permission state machine rejects a response from four distinct guards. Each
one records a ``REJECTED_INVALID_STATE`` control action carrying the original
reason and commits it before reporting, so a replay under the same idempotency
key reads the stored reason back instead of re-deciding it. These drive the real
``respond_to_permission`` against a real SQLite-backed session and a run really
parked on its request in a real checkpointer, and assert both halves of that
contract - the returned result and the committed row - through a second session,
which only sees the row if the commit really happened.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from ...control._permission_response_contract import PermissionInput
from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.leased_dispatch import DispatchTransport
from ...control.permission_service import respond_to_permission
from ...database import (
    ControlActionModel,
    create_thread,
    get_control_action_by_idempotency_key,
    get_permission_request,
    mark_permission_request_applied,
    overdue_recovery_actions,
    record_permission_request,
    supersede_permission_requests,
)
from ...testing import (
    adopted_spawner,
    current_execution_metadata,
    park_document_approval,
    park_permission,
    seed_create_action,
)
from ...tests._write_authority import make_test_write_authority
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionResultStatus, ThreadStatus

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
    )

_CONFLICT = 409
_FORBIDDEN = 403
_NOT_FOUND = 404

_OPTIONS: list[dict[str, object]] = [
    {"optionId": "allow_once", "name": "Allow once"},
    {"optionId": "reject_once", "name": "Reject once"},
]


async def _respond(
    session: AsyncSession,
    checkpointer: AsyncSqliteSaver,
    *,
    thread_id: str,
    request_id: str,
    option_id: str,
):
    """Drive the real service with real (unreachable-worker) collaborators.

    Every rejection under test returns before any dispatch, so the worker never
    has to answer; the collaborators are real objects regardless.
    """
    spawner = adopted_spawner()
    circuit_breaker = WorkerCircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=0.2) as client:
        return await respond_to_permission(
            session,
            thread_id=thread_id,
            response=PermissionInput(request_id, option_id, None),
            checkpointer=checkpointer,
            transport=DispatchTransport(
                worker_client=client,
                circuit_breaker=circuit_breaker,
                worker_spawner=spawner,
            ),
        )


async def _seed_thread(session_factory: async_sessionmaker[AsyncSession]) -> str:
    """Create a committed, non-terminal thread the guards can reject against."""
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Permission rejection",
            status=ThreadStatus.INPUT_REQUIRED.value,
        )
        await session.commit()
    return thread.id


async def _journal_request(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    request_id: str,
    pause_reason_type: str = "tool_permission_request",
    allowed_options: list[dict[str, object]] | None = None,
) -> None:
    """Record the journal row the relay writes beside a request the run raised."""
    async with session_factory() as session:
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread_id,
            pause_reason_type=pause_reason_type,
            description="Run a tool",
            allowed_options=_OPTIONS if allowed_options is None else allowed_options,
        )
        await session.commit()


async def _assert_journalled(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    action_id: str,
    expected_option_id: str,
    expected_error_detail: str,
) -> None:
    """The rejection row must be readable from a session that never wrote it."""
    async with session_factory() as reader:
        stored = await reader.get(ControlActionModel, action_id)
        overdue = await overdue_recovery_actions(
            reader, observed_at=datetime.now(UTC) + timedelta(days=1), limit=10
        )
    assert stored is not None, "the rejection was reported but never committed"
    assert (
        stored.result_status == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )
    # A refusal is settled the moment it is written: nothing will ever dispatch
    # it, so it carries no recovery deadline and recovery never selects it. The
    # invented ``now + 5 min`` made every refusal look like accepted work whose
    # delivery was owed, and the deadline it claimed was fiction.
    assert stored.recovery_deadline_at is None
    assert action_id not in {action.id for action in overdue}
    assert isinstance(stored.payload_json, str), (
        "the rejection reason must be persisted on the action"
    )
    payload = json.loads(stored.payload_json)
    assert payload == {
        "option_id": expected_option_id,
        "error_detail": expected_error_detail,
    }


@pytest.mark.asyncio
async def test_unknown_option_is_journalled_and_committed(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The option-validation guard journals the rejection reason durably."""
    thread_id = await _seed_thread(session_factory)
    request_id = await park_permission(
        checkpointer, thread_id=thread_id, options=_OPTIONS
    )
    await _journal_request(session_factory, thread_id=thread_id, request_id=request_id)

    async with session_factory() as session:
        result = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=request_id,
            option_id="not-an-option",
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
async def test_a_request_the_run_is_not_parked_on_is_journalled_and_committed(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The pending guard reads the checkpoint, so a stale request is refused.

    The stale request is one the run has already moved past, which is what makes
    it stale: its journal row still says pending, and the checkpoint - the only
    thing that says whether a run is parked - does not hold it. Two requests both
    still held are two live questions, a fan-out stage parking each of its
    branches on its own, and each of those is answerable.
    """
    thread_id = await _seed_thread(session_factory)
    await park_permission(checkpointer, thread_id=thread_id, options=_OPTIONS)
    stale_request_id = f"{thread_id}:perm-stale"
    await _journal_request(
        session_factory, thread_id=thread_id, request_id=stale_request_id
    )

    async with session_factory() as session:
        result = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=stale_request_id,
            option_id="allow_once",
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
async def test_an_answer_to_an_applied_request_journals_an_undispatchable_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The duplicate a settled request's replay records is settled when written.

    The run has moved past the request and its answer is already applied, so the
    replay is reported as the duplicate it is. Nothing will dispatch that row, so
    it carries no recovery deadline and recovery never selects it.
    """
    thread_id = await _seed_thread(session_factory)
    request_id = f"{thread_id}:perm-applied"
    await _journal_request(session_factory, thread_id=thread_id, request_id=request_id)
    async with session_factory() as session:
        await mark_permission_request_applied(session, request_id=request_id)
        await session.commit()

    async with session_factory() as session:
        result = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=request_id,
            option_id="allow_once",
        )

    assert result.accepted is True
    assert result.applied is True
    assert result.action_status == ControlActionResultStatus.DUPLICATE.value
    assert result.action_id is not None

    async with session_factory() as reader:
        stored = await reader.get(ControlActionModel, result.action_id)
        overdue = await overdue_recovery_actions(
            reader, observed_at=datetime.now(UTC) + timedelta(days=1), limit=10
        )
    assert stored is not None, "the duplicate was reported but never committed"
    assert stored.result_status == ControlActionResultStatus.DUPLICATE.value
    assert stored.recovery_deadline_at is None
    assert result.action_id not in {action.id for action in overdue}


@pytest.mark.asyncio
async def test_a_held_request_is_answerable_whatever_its_journal_row_says(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
    tmp_path: Path,
) -> None:
    """A journal row marked superseded does not close a pause the run still holds.

    The row is journal, not authority: the checkpoint still holds the request, so
    its answer is admitted and carried as far as the dispatch - which meets an
    unreachable worker, the typed outcome that proves no refusal came first.
    """
    async with session_factory() as session:
        thread = await create_thread(
            session,
            write_authority=make_test_write_authority(),
            title="Permission held",
            status=ThreadStatus.INPUT_REQUIRED.value,
            metadata=current_execution_metadata(tmp_path),
        )
        await seed_create_action(session, thread.id, workspace=tmp_path)
        await session.commit()
    thread_id = thread.id
    held_request_id = await park_permission(
        checkpointer, thread_id=thread_id, options=_OPTIONS
    )
    await _journal_request(
        session_factory, thread_id=thread_id, request_id=held_request_id
    )
    async with session_factory() as session:
        await supersede_permission_requests(
            session, thread_id=thread_id, except_request_id=f"{thread_id}:other"
        )
        await session.commit()

    async with session_factory() as session:
        result = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=held_request_id,
            option_id="allow_once",
        )

    assert result.accepted is False
    assert result.failure_type is FailureType.UNREACHABLE
    assert result.error_status_code is None


@pytest.mark.asyncio
async def test_optionless_request_is_journalled_and_committed(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A request offering no usable options fails closed, and says so durably."""
    thread_id = await _seed_thread(session_factory)
    request_id = await park_permission(checkpointer, thread_id=thread_id, options=[])
    await _journal_request(
        session_factory,
        thread_id=thread_id,
        request_id=request_id,
        allowed_options=[],
    )

    async with session_factory() as session:
        result = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=request_id,
            option_id="allow_once",
        )

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
async def test_replay_reads_the_stored_rejection_reason(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The journal entry is what a replay answers from - not a re-decision.

    This is why the commit belongs inside the rejection path: the second call
    hits the idempotency dedup branch, which reads the stored ``error_detail``
    back out of the committed row.
    """
    thread_id = await _seed_thread(session_factory)
    request_id = await park_permission(
        checkpointer, thread_id=thread_id, options=_OPTIONS
    )
    await _journal_request(session_factory, thread_id=thread_id, request_id=request_id)

    async with session_factory() as session:
        first = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=request_id,
            option_id="nope",
        )
    async with session_factory() as session:
        replay = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=request_id,
            option_id="nope",
        )

    assert replay.action_id == first.action_id
    assert replay.idempotency_key == first.idempotency_key
    assert replay.error_detail == first.error_detail
    assert (
        replay.action_status == ControlActionResultStatus.REJECTED_INVALID_STATE.value
    )


@pytest.mark.asyncio
async def test_a_request_no_run_holds_or_journals_is_not_found(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A guessed request id reaches nothing: it is neither held nor journalled."""
    thread_id = await _seed_thread(session_factory)
    await park_permission(checkpointer, thread_id=thread_id, options=_OPTIONS)

    async with session_factory() as session:
        result = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id="perm-never-asked",
            option_id="allow_once",
        )

    assert result.accepted is False
    assert result.error_status_code == _NOT_FOUND
    assert result.action_id is None


@pytest.mark.asyncio
async def test_document_approval_pause_is_refused_not_journalled(
    session_factory: async_sessionmaker[AsyncSession],
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The engine alone decides a document-approval pause; this route refuses.

    Accepting the response would resolve this pause into a
    REJECTED_INVALID_STATE row carrying an ``{"approved": bool}`` resume the
    document phase gate cannot parse — a state fork against engine truth. The
    route refuses before the idempotency and transition logic even runs, so
    nothing is journalled under the response's natural idempotency key and the
    permission is left exactly as durably pending as it was before the call —
    proving the retired approved-boolean resume is never constructed.
    """
    thread_id = await _seed_thread(session_factory)
    request_id = await park_document_approval(
        checkpointer, thread_id=thread_id, proposal_id=f"{thread_id}:perm-document"
    )
    await _journal_request(
        session_factory,
        thread_id=thread_id,
        request_id=request_id,
        pause_reason_type="document_approval_request",
        allowed_options=[
            {"optionId": "approve", "name": "Approve"},
            {"optionId": "reject", "name": "Reject"},
        ],
    )

    async with session_factory() as session:
        result = await _respond(
            session,
            checkpointer,
            thread_id=thread_id,
            request_id=request_id,
            option_id="approve",
        )

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
