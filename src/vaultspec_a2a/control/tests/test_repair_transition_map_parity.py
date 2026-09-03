"""The transition functions must write what the policy map says.

The repair-state values used to be spelled out in each of seven transition
functions and again in the policy map - two definitions of one rule, free to
drift. The functions now read the map, and this proves the two agree by running
the real functions against a real database and reading back what they persisted.

Testing the map alone would not have caught the divergence, because the map was
already right; it was the functions that duplicated it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...conftest import materialize_schema
from ...control.repair_transitions import (
    apply_dispatch_failure,
    mark_cancel_requested,
    mark_dispatch_failed,
    mark_ingest_applied,
    mark_ingest_requested,
    mark_message_followup_applied,
    mark_message_followup_requested,
    mark_permission_response_applied,
    mark_permission_response_requested,
)
from ...database import create_thread
from ...thread.enums import ControlActionType, ThreadStatus
from ...thread.repair_policy import (
    DISPATCH_FAILED_TRANSITION,
    repair_state_for_action,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from ...database.models import ThreadModel

    _TransitionFn = Callable[[AsyncSession, str], Awaitable[ThreadModel | None]]


@pytest_asyncio.fixture
async def session_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    case_dir = tmp_path_factory.mktemp("repair-parity-db")
    materialize_schema(Path(case_dir / "test.db"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


_CASES: list[tuple[_TransitionFn, ControlActionType, str]] = [
    (mark_ingest_requested, ControlActionType.INGEST, "requested"),
    (mark_ingest_applied, ControlActionType.INGEST, "applied"),
    (
        mark_permission_response_requested,
        ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        "requested",
    ),
    (
        mark_permission_response_applied,
        ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        "applied",
    ),
    (
        mark_message_followup_requested,
        ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        "requested",
    ),
    (
        mark_message_followup_applied,
        ControlActionType.MESSAGE_FOLLOWUP_APPLIED,
        "applied",
    ),
    (mark_cancel_requested, ControlActionType.CANCEL, "requested"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("fn", "action", "phase"), _CASES)
async def test_each_transition_persists_what_the_map_declares(
    session_factory, fn, action, phase
) -> None:
    """What the function writes to the database is what the policy map holds."""
    expected = repair_state_for_action(action, phase)

    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="parity",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

        updated = await fn(session, thread.id)
        await session.commit()

    assert updated is not None
    assert updated.repair_status == expected.repair_status.value
    assert updated.execution_readiness == expected.execution_readiness


@pytest.mark.asyncio
async def test_dispatch_failed_persists_the_pure_policy_transition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Dispatch failure writes exactly the pure ``DISPATCH_FAILED_TRANSITION``.

    Dispatch failure has no ``(action, phase)`` map key, but its repair state is
    still owned by the pure policy rather than spelled out inline in the
    transition function; this proves the function persists that one authority.
    """
    expected = DISPATCH_FAILED_TRANSITION

    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="parity",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

        updated = await mark_dispatch_failed(session, thread.id, reason="boom")
        await session.commit()

    assert updated is not None
    assert updated.repair_status == expected.repair_status.value
    assert updated.execution_readiness == expected.execution_readiness
    assert updated.repair_reason == "boom"


@pytest.mark.asyncio
async def test_apply_dispatch_failure_moves_status_and_repair_state_together(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The shared helper pairs the thread-status change with the repair transition.

    The three dispatch callers used to spell both mutations inline; the helper is
    the single place that performs them, so a caller cannot update one without the
    other.
    """
    expected = DISPATCH_FAILED_TRANSITION

    async with session_factory() as session:
        thread = await create_thread(
            session,
            title="apply",
            repair_status="healthy",
            execution_readiness="healthy",
        )
        await session.commit()

        updated = await apply_dispatch_failure(
            session, thread.id, failed_status=ThreadStatus.FAILED
        )
        await session.commit()

    assert updated is not None
    assert updated.status == ThreadStatus.FAILED.value
    assert updated.repair_status == expected.repair_status.value
    assert updated.execution_readiness == expected.execution_readiness
