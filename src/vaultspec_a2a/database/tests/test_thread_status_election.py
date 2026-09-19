"""Atomic durable thread-status ownership election tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

from ...thread.enums import ControlActionType, InvalidTransitionError, ThreadStatus
from ..models import Base, RunWriteAuthority
from ..permission_repository import create_control_action
from ..thread_repository import (
    ThreadStatusElectionOutcome,
    ThreadWriteExpectation,
    create_thread,
    elect_thread_status,
    get_thread,
    thread_write_expectation,
)


@pytest_asyncio.fixture
async def engine(runtime_dir: Path) -> AsyncIterator[AsyncEngine]:
    """Create a file-backed database so independent sessions share locks."""
    database = runtime_dir / "thread-status-election.sqlite"
    value = create_async_engine(f"sqlite+aiosqlite:///{database}")
    async with value.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield value
    await value.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed(
    sessions: async_sessionmaker[AsyncSession],
    thread_id: str,
    status: ThreadStatus,
    receipt: str,
) -> ThreadWriteExpectation:
    authority = RunWriteAuthority(0, 1, ControlActionType.INGEST, receipt)
    async with sessions() as session:
        thread = await create_thread(
            session,
            thread_id=thread_id,
            status=status,
            write_authority=authority,
        )
        await create_control_action(
            session,
            thread_id=thread_id,
            action_type=ControlActionType.INGEST,
            idempotency_key=f"{thread_id}-ingest",
            dispatch_id=receipt,
        )
        expectation = thread_write_expectation(thread)
        await session.commit()
    return expectation


def _successor(
    expectation: ThreadWriteExpectation,
    *,
    action_type: ControlActionType | None = None,
    receipt: str | None = None,
    generation: int | None = None,
) -> RunWriteAuthority:
    current = expectation.authority
    return RunWriteAuthority(
        current.run_revision + 1,
        current.writer_generation if generation is None else generation,
        action_type or current.action_type,
        receipt or current.action_receipt_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("winner_status", "loser_status"),
    [
        (ThreadStatus.COMPLETED, ThreadStatus.CANCELLED),
        (ThreadStatus.CANCELLED, ThreadStatus.COMPLETED),
    ],
)
async def test_stale_terminal_sessions_elect_exactly_one_winner(
    sessions: async_sessionmaker[AsyncSession],
    winner_status: ThreadStatus,
    loser_status: ThreadStatus,
) -> None:
    thread_id = f"winner-{winner_status.value}"
    expected = await _seed(
        sessions, thread_id, ThreadStatus.RUNNING, f"receipt-{winner_status.value}"
    )
    successor = _successor(expected)

    async with sessions() as winner:
        first = await elect_thread_status(
            winner,
            thread_id,
            expectation=expected,
            status=winner_status,
            successor=successor,
        )
        await winner.commit()
    async with sessions() as stale:
        second = await elect_thread_status(
            stale,
            thread_id,
            expectation=expected,
            status=loser_status,
            successor=successor,
        )
        await stale.commit()
    async with sessions() as reader:
        durable = await get_thread(reader, thread_id)

    assert first.outcome is ThreadStatusElectionOutcome.WON
    assert second.outcome is ThreadStatusElectionOutcome.LOST
    assert durable is not None
    assert durable.status == winner_status.value
    assert durable.run_revision == 1
    assert durable.writer_generation == 1


@pytest.mark.asyncio
async def test_completion_before_running_wins_and_late_running_loses(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "early-completion"
    expected = await _seed(
        sessions, thread_id, ThreadStatus.SUBMITTED, "early-completion-receipt"
    )
    successor = _successor(expected)
    async with sessions() as completion:
        completed = await elect_thread_status(
            completion,
            thread_id,
            expectation=expected,
            status=ThreadStatus.COMPLETED,
            successor=successor,
        )
        await completion.commit()
    async with sessions() as late_running:
        running = await elect_thread_status(
            late_running,
            thread_id,
            expectation=expected,
            status=ThreadStatus.RUNNING,
            successor=successor,
        )
        await late_running.commit()

    assert completed.outcome is ThreadStatusElectionOutcome.WON
    assert running.outcome is ThreadStatusElectionOutcome.LOST


@pytest.mark.asyncio
async def test_winner_refreshes_same_session_identity_map(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "same-session-truth"
    await _seed(sessions, thread_id, ThreadStatus.RUNNING, "same-session-truth-receipt")
    async with sessions() as session:
        loaded = await get_thread(session, thread_id)
        assert loaded is not None
        expected = thread_write_expectation(loaded)
        await create_control_action(
            session,
            thread_id=thread_id,
            action_type=ControlActionType.CANCEL,
            idempotency_key="same-session-cancel",
            dispatch_id="same-session-cancel-receipt",
        )
        successor = _successor(
            expected,
            action_type=ControlActionType.CANCEL,
            receipt="same-session-cancel-receipt",
            generation=2,
        )
        result = await elect_thread_status(
            session,
            thread_id,
            expectation=expected,
            status=ThreadStatus.CANCELLED,
            successor=successor,
        )
        same_object = await get_thread(session, thread_id)
        assert same_object is loaded
        assert loaded.status == ThreadStatus.CANCELLED.value
        assert loaded.run_revision == 1
        assert loaded.writer_generation == 2
        assert loaded.writer_action_type == ControlActionType.CANCEL.value
        assert loaded.writer_action_receipt_id == "same-session-cancel-receipt"
        await session.commit()
        assert loaded.status == ThreadStatus.CANCELLED.value
        assert loaded.run_revision == 1
        assert loaded.writer_generation == 2
        assert loaded.writer_action_type == ControlActionType.CANCEL.value
        assert loaded.writer_action_receipt_id == "same-session-cancel-receipt"

    assert result.outcome is ThreadStatusElectionOutcome.WON


@pytest.mark.asyncio
async def test_each_stale_authority_dimension_loses(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "all-dimensions"
    current = await _seed(
        sessions, thread_id, ThreadStatus.RUNNING, "all-dimensions-receipt"
    )
    altered = (
        (
            ThreadWriteExpectation(ThreadStatus.SUBMITTED, current.authority),
            ThreadStatusElectionOutcome.LOST,
        ),
        (
            ThreadWriteExpectation(
                ThreadStatus.RUNNING,
                RunWriteAuthority(
                    1, 1, ControlActionType.INGEST, "all-dimensions-receipt"
                ),
            ),
            ThreadStatusElectionOutcome.LOST,
        ),
        (
            ThreadWriteExpectation(
                ThreadStatus.RUNNING,
                RunWriteAuthority(
                    0, 2, ControlActionType.INGEST, "all-dimensions-receipt"
                ),
            ),
            ThreadStatusElectionOutcome.LOST,
        ),
        (
            ThreadWriteExpectation(
                ThreadStatus.RUNNING,
                RunWriteAuthority(0, 1, ControlActionType.CANCEL, "other-receipt"),
            ),
            ThreadStatusElectionOutcome.RECEIPT_MISMATCH,
        ),
        (
            ThreadWriteExpectation(
                ThreadStatus.RUNNING,
                RunWriteAuthority(0, 1, ControlActionType.INGEST, "other-receipt"),
            ),
            ThreadStatusElectionOutcome.RECEIPT_MISMATCH,
        ),
    )
    for expectation, expected_outcome in altered:
        async with sessions() as session:
            result = await elect_thread_status(
                session,
                thread_id,
                expectation=expectation,
                status=ThreadStatus.COMPLETED,
                successor=_successor(expectation),
            )
            await session.rollback()
        assert result.outcome is expected_outcome


@pytest.mark.asyncio
async def test_successor_requires_same_thread_action_receipt(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    expected = await _seed(
        sessions, "receipt-owner", ThreadStatus.RUNNING, "receipt-owner-ingest"
    )
    await _seed(
        sessions, "foreign-owner", ThreadStatus.RUNNING, "foreign-cancel-receipt"
    )
    async with sessions() as session:
        await create_control_action(
            session,
            thread_id="receipt-owner",
            action_type=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
            idempotency_key="wrong-action",
            dispatch_id="wrong-action-receipt",
        )
        await session.commit()

    for receipt in (
        "missing-receipt",
        "foreign-cancel-receipt",
        "wrong-action-receipt",
    ):
        successor = _successor(
            expected,
            action_type=ControlActionType.CANCEL,
            receipt=receipt,
            generation=2,
        )
        async with sessions() as session:
            result = await elect_thread_status(
                session,
                "receipt-owner",
                expectation=expected,
                status=ThreadStatus.CANCELLED,
                successor=successor,
            )
            await session.rollback()
        assert result.outcome is ThreadStatusElectionOutcome.RECEIPT_MISMATCH


@pytest.mark.asyncio
async def test_changed_action_advances_generation_and_exact_receipt_wins(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "changed-action"
    expected = await _seed(
        sessions, thread_id, ThreadStatus.RUNNING, "changed-action-ingest"
    )
    async with sessions() as session:
        await create_control_action(
            session,
            thread_id=thread_id,
            action_type=ControlActionType.CANCEL,
            idempotency_key="changed-action-cancel",
            dispatch_id="changed-action-cancel-receipt",
        )
        await session.commit()
    successor = _successor(
        expected,
        action_type=ControlActionType.CANCEL,
        receipt="changed-action-cancel-receipt",
        generation=2,
    )
    async with sessions() as session:
        result = await elect_thread_status(
            session,
            thread_id,
            expectation=expected,
            status=ThreadStatus.CANCELLED,
            successor=successor,
        )
        await session.commit()
    async with sessions() as reader:
        durable = await get_thread(reader, thread_id)

    assert result.outcome is ThreadStatusElectionOutcome.WON
    assert durable is not None
    assert durable.run_revision == 1
    assert durable.writer_generation == 2
    assert durable.writer_action_type == ControlActionType.CANCEL.value
    assert durable.writer_action_receipt_id == "changed-action-cancel-receipt"


@pytest.mark.asyncio
async def test_invalid_successor_and_terminal_reopen_refuse_before_sql(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "terminal-refusal"
    expected = await _seed(
        sessions, thread_id, ThreadStatus.COMPLETED, "terminal-refusal-receipt"
    )
    async with sessions() as session:
        with pytest.raises(InvalidTransitionError):
            await elect_thread_status(
                session,
                thread_id,
                expectation=expected,
                status=ThreadStatus.RUNNING,
                successor=_successor(expected),
            )
        with pytest.raises(ValueError, match="run_revision"):
            await elect_thread_status(
                session,
                thread_id,
                expectation=expected,
                status=ThreadStatus.ARCHIVED,
                successor=RunWriteAuthority(
                    2, 1, ControlActionType.INGEST, "terminal-refusal-receipt"
                ),
            )


@pytest.mark.asyncio
async def test_noop_and_wrong_generation_successors_are_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    thread_id = "successor-refusal"
    expected = await _seed(
        sessions, thread_id, ThreadStatus.RUNNING, "successor-refusal-receipt"
    )
    async with sessions() as session:
        with pytest.raises(ValueError, match="advance state or install"):
            await elect_thread_status(
                session,
                thread_id,
                expectation=expected,
                status=ThreadStatus.RUNNING,
                successor=_successor(expected),
            )
        with pytest.raises(ValueError, match="writer_generation"):
            await elect_thread_status(
                session,
                thread_id,
                expectation=expected,
                status=ThreadStatus.CANCELLED,
                successor=_successor(
                    expected,
                    action_type=ControlActionType.CANCEL,
                    receipt="new-cancel-receipt",
                ),
            )


@pytest.mark.asyncio
async def test_missing_thread_and_failure_reason_bound(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    missing = ThreadWriteExpectation(
        ThreadStatus.RUNNING,
        RunWriteAuthority(0, 1, ControlActionType.INGEST, "missing-receipt"),
    )
    async with sessions() as session:
        absent = await elect_thread_status(
            session,
            "missing-thread",
            expectation=missing,
            status=ThreadStatus.FAILED,
            successor=_successor(missing),
        )
    assert absent.outcome is ThreadStatusElectionOutcome.NOT_FOUND

    thread_id = "bounded-reason"
    expected = await _seed(
        sessions, thread_id, ThreadStatus.RUNNING, "bounded-reason-receipt"
    )
    async with sessions() as session:
        result = await elect_thread_status(
            session,
            thread_id,
            expectation=expected,
            status=ThreadStatus.FAILED,
            successor=_successor(expected),
            failure_reason="字" * 1000,
        )
        await session.commit()
    async with sessions() as reader:
        durable = await get_thread(reader, thread_id)

    assert result.outcome is ThreadStatusElectionOutcome.WON
    assert durable is not None
    assert durable.failure_reason is not None
    assert len(durable.failure_reason.encode("utf-8")) <= 500
    assert durable.failure_reason.endswith("…")
