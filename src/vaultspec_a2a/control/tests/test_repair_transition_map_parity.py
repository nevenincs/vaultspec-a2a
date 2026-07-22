"""The transition functions must write what the policy map says.

The repair-state values used to be spelled out in each of seven transition
functions and again in the policy map - two definitions of one rule, free to
drift. The functions now read the map, and this proves the two agree by running
the real functions against a real database and reading back what they persisted.

Testing the map alone would not have caught the divergence, because the map was
already right; it was the functions that duplicated it.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.repair_transitions import (
    mark_cancel_requested,
    mark_ingest_applied,
    mark_ingest_requested,
    mark_message_followup_applied,
    mark_message_followup_requested,
    mark_permission_response_applied,
    mark_permission_response_requested,
)
from vaultspec_a2a.database import create_thread
from vaultspec_a2a.database.models import Base
from vaultspec_a2a.thread.enums import ControlActionType
from vaultspec_a2a.thread.repair_policy import repair_state_for_action


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("repair-parity-db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


_CASES = [
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
