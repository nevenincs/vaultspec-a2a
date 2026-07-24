"""Idempotency proofs for the deletion saga repository against real SQLite.

The saga is the durable spine of failure-atomic thread deletion, so its four
operations must converge under replay and resume rather than duplicate work or
tear down a thread whose cleanup has not finished. These drive the real
repository against a real SQLite database - no mocks - and assert on the rows
and hydrated views they produce.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultspec_a2a.control.repositories import (
    CleanupItem,
    CleanupItemResult,
    CleanupItemState,
    CleanupKind,
    advance_deletion_cleanup_item,
    claim_deletion_saga,
    create_deletion_saga,
    deserialize_manifest,
    deserialize_results,
    finalize_deletion_saga,
    serialize_manifest,
    serialize_results,
)
from vaultspec_a2a.database import create_thread, get_thread
from vaultspec_a2a.database.models import Base, ThreadDeletionSagaModel
from vaultspec_a2a.thread.enums import ThreadStatus


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("deletion-saga-db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _manifest(thread_id: str) -> list[CleanupItem]:
    return [
        CleanupItem(kind=CleanupKind.CHECKPOINT, key="checkpoint", target=thread_id),
        CleanupItem(
            kind=CleanupKind.ARTIFACT_FILE,
            key="artifact:a1",
            target="/ws/out/report.md",
            root="/ws",
        ),
    ]


def _count_saga_rows(thread_id: str):
    return (
        select(func.count())
        .select_from(ThreadDeletionSagaModel)
        .where(ThreadDeletionSagaModel.thread_id == thread_id)
    )


async def _seed_terminal_thread(session_factory, thread_id: str = "t-del") -> str:
    async with session_factory() as session:
        await create_thread(session, thread_id=thread_id, status=ThreadStatus.COMPLETED)
        await session.commit()
    return thread_id


def test_manifest_and_results_round_trip_through_json() -> None:
    """The codec preserves every field of the manifest and result ledger."""
    manifest = _manifest("t1")
    restored = deserialize_manifest(serialize_manifest(manifest))
    assert restored == manifest

    results = {
        "checkpoint": CleanupItemResult("checkpoint", CleanupItemState.DONE),
        "artifact:a1": CleanupItemResult(
            "artifact:a1", CleanupItemState.FAILED, detail="locked"
        ),
    }
    restored_results = deserialize_results(serialize_results(results))
    assert restored_results == results


@pytest.mark.asyncio
async def test_create_transitions_thread_and_captures_manifest(session_factory) -> None:
    """Creating the saga marks the thread deleting and stores the manifest."""
    thread_id = await _seed_terminal_thread(session_factory)

    async with session_factory() as session:
        saga = await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    assert saga.created is True
    assert [item.key for item in saga.manifest] == ["checkpoint", "artifact:a1"]

    async with session_factory() as session:
        thread = await get_thread(session, thread_id)
        assert thread is not None
        assert thread.status == ThreadStatus.DELETING.value
        assert thread.is_active is False


@pytest.mark.asyncio
async def test_create_is_idempotent_and_keeps_the_first_manifest(
    session_factory,
) -> None:
    """A replayed create returns the existing saga without duplicating it."""
    thread_id = await _seed_terminal_thread(session_factory)

    async with session_factory() as session:
        first = await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    async with session_factory() as session:
        second = await create_deletion_saga(
            session,
            thread_id=thread_id,
            manifest=[
                CleanupItem(
                    kind=CleanupKind.CHECKPOINT, key="different", target=thread_id
                )
            ],
        )
        await session.commit()

    assert first.created is True
    assert second.created is False
    # The authoritative manifest is the one captured first, not the replay's.
    assert [item.key for item in second.manifest] == ["checkpoint", "artifact:a1"]

    async with session_factory() as session:
        rows = (await session.execute(_count_saga_rows(thread_id))).scalar_one()
        assert rows == 1


@pytest.mark.asyncio
async def test_claim_stamps_ownership_once(session_factory) -> None:
    """The first claim marks ownership; a repeated claim leaves it unchanged."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    async with session_factory() as session:
        first = await claim_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert first is not None
        assert first.claimed is True
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        stamped = row.claimed_at

    async with session_factory() as session:
        again = await claim_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert again is not None
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        assert row.claimed_at == stamped


@pytest.mark.asyncio
async def test_claim_absent_saga_returns_none(session_factory) -> None:
    """Claiming a saga that does not exist reports absence rather than raising."""
    async with session_factory() as session:
        assert await claim_deletion_saga(session, thread_id="missing") is None


@pytest.mark.asyncio
async def test_advance_records_and_is_idempotent(session_factory) -> None:
    """Advancing records terminal state once; the same state again is a no-op."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    done = CleanupItemResult("checkpoint", CleanupItemState.DONE)
    async with session_factory() as session:
        assert await advance_deletion_cleanup_item(
            session, thread_id=thread_id, result=done
        )
        await session.commit()

    async with session_factory() as session:
        assert not await advance_deletion_cleanup_item(
            session, thread_id=thread_id, result=done
        )
        await session.commit()

    async with session_factory() as session:
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        results = deserialize_results(row.result_json)
        assert results["checkpoint"].state is CleanupItemState.DONE


@pytest.mark.asyncio
async def test_advance_supersedes_a_prior_failure(session_factory) -> None:
    """A later success replaces an earlier recorded failure for the same item."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    async with session_factory() as session:
        await advance_deletion_cleanup_item(
            session,
            thread_id=thread_id,
            result=CleanupItemResult(
                "artifact:a1", CleanupItemState.FAILED, detail="locked"
            ),
        )
        await session.commit()

    async with session_factory() as session:
        changed = await advance_deletion_cleanup_item(
            session,
            thread_id=thread_id,
            result=CleanupItemResult("artifact:a1", CleanupItemState.DONE),
        )
        await session.commit()
        assert changed is True

    async with session_factory() as session:
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        results = deserialize_results(row.result_json)
        assert results["artifact:a1"].state is CleanupItemState.DONE


@pytest.mark.asyncio
async def test_finalize_refuses_until_every_item_is_done(session_factory) -> None:
    """Finalization leaves all rows in place while any item is unfinished."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    # Only one of the two manifest items is done.
    async with session_factory() as session:
        await advance_deletion_cleanup_item(
            session,
            thread_id=thread_id,
            result=CleanupItemResult("checkpoint", CleanupItemState.DONE),
        )
        await session.commit()

    async with session_factory() as session:
        outcome = await finalize_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert outcome.finalized is False

    async with session_factory() as session:
        assert await get_thread(session, thread_id) is not None
        assert await session.get(ThreadDeletionSagaModel, thread_id) is not None


@pytest.mark.asyncio
async def test_finalize_removes_rows_only_when_complete(session_factory) -> None:
    """Once every item is done finalization removes the saga and the thread."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    async with session_factory() as session:
        for key in ("checkpoint", "artifact:a1"):
            await advance_deletion_cleanup_item(
                session,
                thread_id=thread_id,
                result=CleanupItemResult(key, CleanupItemState.DONE),
            )
        await session.commit()

    async with session_factory() as session:
        outcome = await finalize_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert outcome.finalized is True

    async with session_factory() as session:
        assert await get_thread(session, thread_id) is None
        assert await session.get(ThreadDeletionSagaModel, thread_id) is None


@pytest.mark.asyncio
async def test_finalize_is_idempotent_after_completion(session_factory) -> None:
    """Finalizing an already-finalized saga is a no-op success."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(session, thread_id=thread_id, manifest=[])
        await session.commit()

    async with session_factory() as session:
        first = await finalize_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert first.finalized is True

    async with session_factory() as session:
        second = await finalize_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert second.finalized is True
        assert second.already_final is True
