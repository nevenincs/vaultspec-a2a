"""The lease commit refuses to publish work the caller staged beside it.

``commit_control_action_lease`` is the one session-taking repository function
that commits. The commit is load-bearing - durable ownership must be visible to
every other process before the network dispatch - but it cannot distinguish the
claim's own rows from anything else pending on the same session, and would
publish both. These are real-store proofs that the composition is refused rather
than silently committed, and that the ordinary claim path is untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from pathlib import Path

from ...control.action_lease import claim_control_action
from ...thread.enums import ControlActionType
from ..models import Base, ControlActionModel
from ..permission_repository import (
    acquire_control_action_lease,
    commit_control_action_lease,
    reserve_control_action,
)
from ..thread_repository import create_thread, get_thread


async def _store(
    runtime_dir: Path, name: str
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{runtime_dir / name}", connect_args={"timeout": 5}
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.mark.asyncio
async def test_lease_commit_refuses_to_publish_a_callers_staged_write(
    runtime_dir: Path,
) -> None:
    """A future caller cannot have unrelated writes committed as a side effect."""
    engine, sessions = await _store(runtime_dir, "lease-composability.db")
    async with sessions() as session:
        await create_thread(session, thread_id="compose-thread", status="running")
        await session.commit()

    async with sessions() as session:
        reserved = await reserve_control_action(
            session,
            thread_id="compose-thread",
            action_type=ControlActionType.CANCEL,
            idempotency_key="cancel:compose",
            payload={"reason": "operator"},
        )
        # Snapshotted before the rollback below expires the ORM attributes.
        action_id = reserved.action.id
        assert await acquire_control_action_lease(
            session,
            action_id,
            claim_token="composed",
            claim_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )

        # The hazard: unrelated work staged on the same session, which the lease
        # commit would otherwise carry to disk.
        staged = await get_thread(session, "compose-thread")
        assert staged is not None
        staged.status = "cancelling"

        with pytest.raises(RuntimeError, match="unflushed changes"):
            await commit_control_action_lease(
                session, action_id, claim_token="composed"
            )
        await session.rollback()

    async with sessions() as session:
        thread = await get_thread(session, "compose-thread")
        assert thread is not None
        # The caller's staged write was never published.
        assert thread.status == "running"
        # The lease itself was never committed either: the refusal came first, so
        # the row is still unclaimed. (The row exists because the reservation's
        # SAVEPOINT commits independently of the outer transaction on SQLite -
        # separate behaviour, asserted here only so it is not mistaken for the
        # lease commit having gone through.)
        action = await session.get(ControlActionModel, action_id)
        assert action is not None
        assert action.claim_token is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_uncontaminated_claim_still_commits_its_lease(
    runtime_dir: Path,
) -> None:
    """The guard does not disturb the real claim flow it protects."""
    engine, sessions = await _store(runtime_dir, "lease-clean-claim.db")
    async with sessions() as session:
        await create_thread(session, thread_id="clean-thread", status="running")
        await session.commit()

    async with sessions() as session:
        claim = await claim_control_action(
            session,
            thread_id="clean-thread",
            action_type=ControlActionType.CANCEL,
            idempotency_key="cancel:clean",
            payload={"reason": "operator"},
        )

    assert claim.acquired is True
    assert claim.claim_token is not None

    # Durable in a session that never saw the claim: the commit really happened.
    async with sessions() as session:
        action = await session.get(ControlActionModel, claim.action_id)
    assert action is not None
    assert action.claim_token == claim.claim_token

    await engine.dispose()
