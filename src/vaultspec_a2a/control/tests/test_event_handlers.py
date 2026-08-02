"""Focused replay/idempotency tests for worker->gateway event handlers."""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...control.event_handlers import (
    _handle_permission_event,
    _handle_progress_event,
    _handle_terminal_event,
)
from ...database import (
    create_thread,
    get_permission_request,
    record_permission_request,
    record_permission_response_submission,
    set_thread_approval_state,
)
from ...database.models import Base, ControlActionModel, ThreadModel


@pytest_asyncio.fixture
async def engine(tmp_path_factory: pytest.TempPathFactory):
    """Create a file-backed engine for replay-focused control tests."""
    case_dir = tmp_path_factory.mktemp("control-event-handler-db")
    db_file = case_dir / "test.db"
    eng = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """Provide an async session factory bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_replayed_permission_resolved_is_ignored_after_progress_apply(
    session_factory,
) -> None:
    """A replayed permission_resolved event must not append a second applied action."""
    async with session_factory() as session:
        thread = await create_thread(session, title="Replay Guard")
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
        await session.commit()

    await _handle_progress_event(
        thread.id,
        {"type": "message_chunk", "content": "worker resumed"},
        session_factory=session_factory,
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
            f"permission-response-progress-applied:{request_id}"
        )

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
    session_factory,
) -> None:
    """Supervisor plan approval interrupts must become durable pending rows."""
    async with session_factory() as session:
        thread = await create_thread(session, title="Plan approval relay")
        await session.commit()
        thread_id = thread.id

    request_id = f"{thread_id}:plan-approval-1"
    payload = {
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


@pytest.mark.asyncio
async def test_terminal_event_expires_pending_plan_approval_projection(
    session_factory,
) -> None:
    """Terminal relay settles a parked plan approval without residue."""
    async with session_factory() as session:
        thread = await create_thread(session, title="Terminal plan approval")
        await session.commit()
        thread_id = thread.id

    request_id = f"{thread_id}:plan-approval-terminal"
    await _handle_permission_event(
        thread_id,
        {
            "type": "plan_approval_request",
            "request_id": request_id,
            "description": "Approve the plan before completion",
            "options": [
                {
                    "option_id": "approve",
                    "name": "Approve Plan",
                    "kind": "allow_once",
                }
            ],
            "tool_call": "plan_approval",
        },
        session_factory=session_factory,
    )

    await _handle_terminal_event(
        thread_id,
        {"event_type": "thread_terminal", "status": "completed"},
        session_factory=session_factory,
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


@pytest.mark.asyncio
async def test_document_approval_request_is_persisted_as_durable_pending_permission(
    session_factory,
) -> None:
    """Document phase-gate interrupts must become durable pending rows.

    The research_adr phase gate parks with a ``document_approval_request``
    interrupt; the relay must record it as a verdict-style approval so the thread
    is INPUT_REQUIRED and the out-of-run verdict subscriber can correlate an
    engine verdict to the parked run.
    """
    async with session_factory() as session:
        thread = await create_thread(session, title="Document approval relay")
        await session.commit()
        thread_id = thread.id

    request_id = f"{thread_id}:document-approval-1"
    payload = {
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


async def _answered_rejection(
    session_factory,
    *,
    title: str,
    pause_reason_type: str,
    options: list[dict[str, object]],
    stamp_thread_rejected: bool,
) -> tuple[str, str]:
    """Park a thread on a permission the human denied, awaiting settlement.

    Reproduces the real pre-settlement state: the response has been submitted
    (leaving the row ``answered_pending_apply``) and, for a plan approval, the
    control service has already stamped the thread REJECTED. Returns
    ``(thread_id, request_id)``.
    """
    async with session_factory() as session:
        thread = await create_thread(session, title=title)
        request_id = f"{thread.id}:perm-reject"
        await record_permission_request(
            session,
            request_id=request_id,
            thread_id=thread.id,
            pause_reason_type=pause_reason_type,
            description="Approve?",
            allowed_options=options,
            tool_call=pause_reason_type,
        )
        await record_permission_response_submission(
            session,
            request_id=request_id,
            option_id="reject",
            idempotency_key="response-reject-1",
        )
        if stamp_thread_rejected:
            await set_thread_approval_state(
                session,
                thread.id,
                approval_status="rejected",
                approval_request_id=request_id,
                approval_reason="Approve?",
            )
        await session.commit()
        thread_id = thread.id

    async with session_factory() as session:
        permission = await get_permission_request(session, request_id)
        assert permission is not None
        assert permission.request_status == "answered_pending_apply"
        assert permission.response_option_id == "reject"

    return thread_id, request_id


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
    session_factory,
) -> None:
    """The resolution handler must not overwrite a denial with an approval.

    The control service stamps the thread REJECTED when the response is submitted.
    The ``permission_resolved`` projection then recomputes the verdict, and used to
    recompute it from a rejecting-*kind* set matched against the response option
    *id* -- so the bare ``"reject"`` the plan gate mints read as an approval and was
    written straight over the correct state.
    """
    thread_id, request_id = await _answered_rejection(
        session_factory,
        title="Plan rejection",
        pause_reason_type="plan_approval_request",
        options=_PLAN_OPTIONS,
        stamp_thread_rejected=True,
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
async def test_plan_rejection_inferred_from_progress_settles_as_rejected(
    session_factory,
) -> None:
    """The progress fallback must reach the same verdict as the primary path.

    Progress only says the worker moved on. It used to settle every answered
    permission as APPLIED unconditionally, passing no status at all so the
    repository default decided -- which silently converted a denial into an
    applied approval.
    """
    thread_id, request_id = await _answered_rejection(
        session_factory,
        title="Plan rejection via progress",
        pause_reason_type="plan_approval_request",
        options=_PLAN_OPTIONS,
        stamp_thread_rejected=True,
    )

    await _handle_progress_event(
        thread_id,
        {"type": "message_chunk", "content": "worker resumed"},
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
async def test_a_kimi_tool_denial_settles_as_rejected_on_both_paths(
    session_factory,
) -> None:
    """A provider-defined rejecting id must settle as a denial, not an approval.

    Kimi offers ``{"optionId": "reject", "kind": "reject_once"}`` -- the id is not
    its kind, which is what proves option ids are free-form. The denial is real:
    the ACP agent does receive ``"reject"`` and the tool is refused, so recording
    it as applied corrupts the journal rather than authorising anything.
    """
    resolved_thread, resolved_request = await _answered_rejection(
        session_factory,
        title="Kimi denial via resolution",
        pause_reason_type="bash",
        options=_KIMI_OPTIONS,
        stamp_thread_rejected=False,
    )
    await _handle_permission_event(
        resolved_thread,
        {"type": "permission_resolved", "request_id": resolved_request},
        session_factory=session_factory,
    )

    progress_thread, progress_request = await _answered_rejection(
        session_factory,
        title="Kimi denial via progress",
        pause_reason_type="bash",
        options=_KIMI_OPTIONS,
        stamp_thread_rejected=False,
    )
    await _handle_progress_event(
        progress_thread,
        {"type": "message_chunk", "content": "worker resumed"},
        session_factory=session_factory,
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
    session_factory,
) -> None:
    """The resolution stage no-ops when no matching request row exists.

    After the split into a validation-then-dispatch handler, the resolution
    stage's missing-permission guard is exercised directly through the handler:
    a permission_resolved event for a request that was never recorded must
    settle nothing and append no control action.
    """
    async with session_factory() as session:
        thread = await create_thread(session, title="Unknown Resolution")
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
