"""Focused replay/idempotency tests for worker->gateway event handlers."""

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.event_handlers import (
    _handle_permission_event,
    _handle_progress_event,
)
from vaultspec_a2a.database import (
    create_thread,
    get_permission_request,
    record_permission_request,
    record_permission_response_submission,
)
from vaultspec_a2a.database.models import Base, ControlActionModel


@pytest_asyncio.fixture
async def engine():
    """Create a file-backed engine for replay-focused control tests."""
    case_dir = (
        Path.home()
        / ".codex"
        / "memories"
        / "tmp"
        / "control-event-handler-db"
        / uuid4().hex
    )
    case_dir.mkdir(parents=True, exist_ok=True)
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
