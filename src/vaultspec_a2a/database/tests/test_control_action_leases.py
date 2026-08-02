"""Real SQLite proofs for durable control-action dispatch leases."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from pathlib import Path

from ...thread.enums import ControlActionType
from ..models import Base, ControlActionModel
from ..permission_repository import (
    acquire_control_action_lease,
    commit_control_action_lease,
    create_control_action,
    get_control_action_by_dispatch_id,
    release_control_action_lease,
    reserve_control_action,
    settle_control_action_lease,
)
from ..thread_repository import create_thread, delete_thread


async def _store(
    runtime_dir: Path, name: str
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{runtime_dir / name}",
        connect_args={"timeout": 5},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.mark.asyncio
async def test_concurrent_sessions_elect_exactly_one_fresh_lease(
    runtime_dir: Path,
) -> None:
    engine, sessions = await _store(runtime_dir, "lease-election.db")
    async with sessions() as session:
        await create_thread(session, thread_id="lease-thread", status="running")
        reservation = await reserve_control_action(
            session,
            thread_id="lease-thread",
            action_type=ControlActionType.RESUME,
            idempotency_key="resolve:req-1",
            request_id="req-1",
            payload={"prompt": "continue with your judgement"},
            dispatch_id="dispatch-stable",
        )
        await session.commit()
        action_id = reservation.action.id

    start = asyncio.Event()
    expires = datetime.now(UTC) + timedelta(minutes=1)

    async def compete(token: str) -> bool:
        async with sessions() as session:
            await start.wait()
            won = await acquire_control_action_lease(
                session,
                action_id,
                claim_token=token,
                claim_expires_at=expires,
            )
            await session.commit()
            return won

    contenders = [
        asyncio.create_task(compete("claim-a")),
        asyncio.create_task(compete("claim-b")),
    ]
    start.set()
    outcomes = await asyncio.gather(*contenders)

    assert sorted(outcomes) == [False, True]
    async with sessions() as session:
        action = await session.get(ControlActionModel, action_id)
    assert action is not None
    assert action.dispatch_id == "dispatch-stable"
    assert action.claim_token in {"claim-a", "claim-b"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_lease_release_expiry_and_settlement_are_token_conditional(
    runtime_dir: Path,
) -> None:
    engine, sessions = await _store(runtime_dir, "lease-lifecycle.db")
    now = datetime.now(UTC)
    async with sessions() as session:
        await create_thread(session, thread_id="lifecycle-thread", status="running")
        reserved = await reserve_control_action(
            session,
            thread_id="lifecycle-thread",
            action_type=ControlActionType.CANCEL,
            idempotency_key="cancel:1",
            payload={"reason": "operator"},
        )
        assert reserved.created is True
        assert reserved.payload_matches is True
        assert await acquire_control_action_lease(
            session,
            reserved.action.id,
            claim_token="first",
            claim_expires_at=now + timedelta(seconds=1),
            now=now,
        )
        await commit_control_action_lease(
            session, reserved.action.id, claim_token="first"
        )

    async with sessions() as session:
        visible = await session.get(ControlActionModel, reserved.action.id)
        assert visible is not None
        assert visible.claim_token == "first"
        assert not await release_control_action_lease(
            session, visible.id, claim_token="other"
        )
        assert await acquire_control_action_lease(
            session,
            visible.id,
            claim_token="recovery",
            claim_expires_at=now + timedelta(minutes=2),
            now=now + timedelta(seconds=2),
        )
        assert not await settle_control_action_lease(
            session, visible.id, claim_token="first"
        )
        assert await settle_control_action_lease(
            session, visible.id, claim_token="recovery"
        )
        await session.commit()

    async with sessions() as session:
        settled = await session.get(ControlActionModel, reserved.action.id)
        assert settled is not None
        assert settled.applied_at is not None
        assert settled.claim_token is None
        assert settled.claim_expires_at is None
        assert not await acquire_control_action_lease(
            session,
            settled.id,
            claim_token="late",
            claim_expires_at=now + timedelta(minutes=3),
            now=now + timedelta(seconds=3),
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_competing_replay_and_thread_deletion_preserve_lifecycle(
    runtime_dir: Path,
) -> None:
    engine, sessions = await _store(runtime_dir, "lease-deletion.db")
    async with sessions() as session:
        await create_thread(session, thread_id="delete-thread", status="running")
        winner = await reserve_control_action(
            session,
            thread_id="delete-thread",
            action_type=ControlActionType.RESUME,
            idempotency_key="same-key",
            payload={"answers": {"q": "yes"}},
        )
        await session.commit()
    async with sessions() as session:
        competing = await reserve_control_action(
            session,
            thread_id="delete-thread",
            action_type=ControlActionType.RESUME,
            idempotency_key="same-key",
            payload={"answers": {"q": "no"}},
        )
        assert competing.action.id == winner.action.id
        assert competing.created is False
        assert competing.payload_matches is False
        await session.rollback()
    async with sessions() as session:
        assert await delete_thread(session, "delete-thread") is True
        await session.commit()
    async with sessions() as session:
        rows = (await session.execute(select(ControlActionModel))).scalars().all()
    assert rows == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_id_is_globally_unique_and_exactly_lookupable(
    runtime_dir: Path,
) -> None:
    engine, sessions = await _store(runtime_dir, "dispatch-identity.db")
    dispatch_id = "global-receipt-identity"
    async with sessions() as session:
        await create_thread(session, thread_id="receipt-thread-a", status="running")
        await create_thread(session, thread_id="receipt-thread-b", status="running")
        first = await create_control_action(
            session,
            thread_id="receipt-thread-a",
            action_type=ControlActionType.RESUME,
            idempotency_key="resume-a",
            dispatch_id=dispatch_id,
        )
        await session.commit()

    async with sessions() as session:
        exact = await get_control_action_by_dispatch_id(
            session,
            thread_id="receipt-thread-a",
            dispatch_id=dispatch_id,
        )
        wrong_thread = await get_control_action_by_dispatch_id(
            session,
            thread_id="receipt-thread-b",
            dispatch_id=dispatch_id,
        )
    assert exact is not None
    assert exact.id == first.id
    assert wrong_thread is None

    async with sessions() as session:
        with pytest.raises(IntegrityError):
            await create_control_action(
                session,
                thread_id="receipt-thread-b",
                action_type=ControlActionType.RESUME,
                idempotency_key="resume-b",
                dispatch_id=dispatch_id,
            )
        await session.rollback()

    await engine.dispose()
