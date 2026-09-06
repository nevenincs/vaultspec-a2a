"""Real-store proofs for exact durable recovery scheduling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database.models import Base, RecoveryAttemptModel, RunWriteAuthority
from ...database.permission_repository import create_control_action
from ...database.session import configure_sqlite_transactions
from ...database.thread_repository import create_thread
from ...thread.dispatch_policy import FailureType
from ...thread.enums import ControlActionType, RecoveryCondition
from ..action_lease import ControlActionClaim, record_dispatch_failure
from ..recovery import (
    acquire_due_recovery_attempts,
    record_recovery_failure,
    reschedule_recovery_attempt,
    seed_recovery_attempts,
    settle_recovery_attempt,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest_asyncio.fixture
async def sessions(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'attempts.db'}")
    configure_sqlite_transactions(engine)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _thread(db: AsyncSession, *, deadline_at: datetime) -> RunWriteAuthority:
    authority = RunWriteAuthority(
        7,
        4,
        ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        "receipt-current",
    )
    await create_thread(db, thread_id="run", write_authority=authority)
    await create_control_action(
        db,
        thread_id="run",
        action_type=authority.action_type,
        idempotency_key="accepted:run",
        dispatch_id=authority.action_receipt_id,
        payload={"schema_version": "test-current"},
        recovery_deadline_at=deadline_at,
    )
    return authority


@pytest.mark.asyncio
async def test_failure_updates_one_exact_schedule(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    deadline = now + timedelta(minutes=10)
    async with sessions() as db:
        authority = await _thread(db, deadline_at=deadline)
        first = await record_recovery_failure(
            db,
            thread_id="run",
            authority=authority,
            condition=RecoveryCondition.CIRCUIT_OPEN,
            observed_at=now,
            next_eligible_at=now + timedelta(seconds=5),
            deadline_at=deadline,
            detail="breaker open",
        )
        first_id = first.id
        second = await record_recovery_failure(
            db,
            thread_id="run",
            authority=authority,
            condition=RecoveryCondition.AT_CAPACITY,
            observed_at=now + timedelta(seconds=5),
            next_eligible_at=now + timedelta(seconds=15),
            deadline_at=deadline,
            detail="capacity",
        )
        await db.commit()

        assert second.id == first_id
        assert second.attempt_count == 2
        assert second.condition == RecoveryCondition.AT_CAPACITY.value
        count = await db.scalar(select(func.count()).select_from(RecoveryAttemptModel))
        assert count == 1


@pytest.mark.asyncio
async def test_live_dispatch_failure_persists_condition_and_releases_known_non_delivery(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 7, 0, tzinfo=UTC)
    deadline = now + timedelta(minutes=10)
    authority = RunWriteAuthority(
        3,
        2,
        ControlActionType.CANCEL,
        "cancel-current",
    )
    async with sessions() as db:
        await create_thread(db, thread_id="cancel-run", write_authority=authority)
        action = await create_control_action(
            db,
            thread_id="cancel-run",
            action_type=authority.action_type,
            idempotency_key="cancel:current",
            dispatch_id=authority.action_receipt_id,
            payload={"schema_version": "test-current"},
            recovery_deadline_at=deadline,
        )
        action.claim_token = "live-owner"
        action.claim_expires_at = now + timedelta(seconds=90)
        await db.commit()

    claim = ControlActionClaim(
        action_id=action.id,
        dispatch_id=authority.action_receipt_id,
        created=True,
        payload_matches=True,
        acquired=True,
        authority_matches=True,
        applied=False,
        result_status=action.result_status,
        claim_token="live-owner",
    )
    async with sessions() as db:
        assert await record_dispatch_failure(
            db,
            claim,
            FailureType.AT_CAPACITY,
            detail="worker capacity reached",
            observed_at=now,
        )
        await db.commit()

    async with sessions() as db:
        stored_action = await db.get(type(action), action.id)
        attempt = await db.scalar(
            select(RecoveryAttemptModel).where(
                RecoveryAttemptModel.thread_id == "cancel-run"
            )
        )
    assert stored_action is not None
    assert stored_action.claim_token is None
    assert stored_action.claim_expires_at is None
    assert attempt is not None
    assert attempt.condition == RecoveryCondition.AT_CAPACITY.value
    assert attempt.attempt_count == 1
    assert attempt.detail == "worker capacity reached"
    assert attempt.settled_at is None


@pytest.mark.asyncio
async def test_failure_refuses_stale_or_fabricated_writer(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    async with sessions() as db:
        authority = await _thread(db, deadline_at=now + timedelta(minutes=1))
        stale = RunWriteAuthority(
            authority.run_revision + 1,
            authority.writer_generation,
            authority.action_type,
            authority.action_receipt_id,
        )
        with pytest.raises(
            ValueError, match="does not own the current accepted action"
        ):
            await record_recovery_failure(
                db,
                thread_id="run",
                authority=stale,
                condition=RecoveryCondition.UNREACHABLE,
                observed_at=now,
                next_eligible_at=now + timedelta(seconds=5),
                deadline_at=now + timedelta(minutes=1),
                detail="stale",
            )

        count = await db.scalar(select(func.count()).select_from(RecoveryAttemptModel))
        assert count == 0


@pytest.mark.asyncio
async def test_claim_is_exclusive_and_reschedule_is_token_guarded(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    deadline = now + timedelta(minutes=10)
    async with sessions() as db:
        authority = await _thread(db, deadline_at=deadline)
        await record_recovery_failure(
            db,
            thread_id="run",
            authority=authority,
            condition=RecoveryCondition.UNREACHABLE,
            observed_at=now,
            next_eligible_at=now,
            deadline_at=deadline,
            detail="transport",
        )
        await db.commit()

    async with sessions() as db:
        claims = await acquire_due_recovery_attempts(
            db,
            acquired_at=now,
            claim_expires_at=now + timedelta(seconds=30),
            limit=10,
        )
        await db.commit()
        assert len(claims) == 1
        claim = claims[0]
        assert claim.authority == authority

    async with sessions() as db:
        assert not await acquire_due_recovery_attempts(
            db,
            acquired_at=now + timedelta(seconds=1),
            claim_expires_at=now + timedelta(seconds=31),
            limit=10,
        )
        wrong = claim.__class__(
            attempt_id=claim.attempt_id,
            claim_token="wrong",
            thread_id=claim.thread_id,
            authority=claim.authority,
            condition=claim.condition,
            attempt_count=claim.attempt_count,
            deadline_at=claim.deadline_at,
        )
        assert not await reschedule_recovery_attempt(
            db,
            wrong,
            condition=RecoveryCondition.AT_CAPACITY,
            observed_at=now + timedelta(seconds=2),
            next_eligible_at=now + timedelta(seconds=20),
            detail="wrong owner",
        )
        assert await reschedule_recovery_attempt(
            db,
            claim,
            condition=RecoveryCondition.AT_CAPACITY,
            observed_at=now + timedelta(seconds=2),
            next_eligible_at=now + timedelta(seconds=20),
            detail="retry later",
        )
        await db.commit()

    async with sessions() as db:
        assert not await acquire_due_recovery_attempts(
            db,
            acquired_at=now + timedelta(seconds=19),
            claim_expires_at=now + timedelta(seconds=49),
            limit=10,
        )
        [second_claim] = await acquire_due_recovery_attempts(
            db,
            acquired_at=now + timedelta(seconds=20),
            claim_expires_at=now + timedelta(seconds=50),
            limit=10,
        )
        assert second_claim.attempt_count == 2
        assert await settle_recovery_attempt(
            db, second_claim, settled_at=now + timedelta(seconds=21)
        )
        await db.commit()

    async with sessions() as db:
        assert not await acquire_due_recovery_attempts(
            db,
            acquired_at=now + timedelta(minutes=1),
            claim_expires_at=now + timedelta(minutes=2),
            limit=10,
        )


@pytest.mark.asyncio
async def test_seed_captures_the_post_acceptance_crash_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    deadline = now + timedelta(minutes=10)
    async with sessions() as db:
        authority = await _thread(db, deadline_at=deadline)
        await db.commit()

    async with sessions() as db:
        assert await seed_recovery_attempts(db, observed_at=now, limit=10) == 1
        assert await seed_recovery_attempts(db, observed_at=now, limit=10) == 0
        await db.commit()

    async with sessions() as db:
        [claim] = await acquire_due_recovery_attempts(
            db,
            acquired_at=now,
            claim_expires_at=now + timedelta(seconds=30),
            limit=10,
        )
        assert claim.authority == authority
        assert claim.condition is RecoveryCondition.DISPATCH_PENDING
