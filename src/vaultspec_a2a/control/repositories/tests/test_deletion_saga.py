"""Idempotency and liveness proofs for the deletion saga against real SQLite.

The saga is the durable spine of failure-atomic thread deletion, so its four
operations must converge under replay and resume rather than duplicate work or
tear down a thread whose cleanup has not finished. Convergence is only half of
it: the saga must also always end. Two ways it could fail to - two passes
racing the shared result ledger, and an item that can never succeed - are
driven here as real concurrency and real repeated failure against a real SQLite
database, no mocks, asserting on the rows and hydrated views they produce.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ....conftest import materialize_schema
from ....control.repositories import (
    CleanupItem,
    CleanupItemResult,
    CleanupItemState,
    advance_deletion_cleanup_item,
    claim_deletion_saga,
    create_deletion_saga,
    deserialize_manifest,
    deserialize_results,
    finalize_deletion_saga,
    serialize_manifest,
    serialize_results,
)
from ....database import create_thread, get_thread
from ....database.models import ThreadDeletionSagaModel
from ....thread.enums import CleanupKind, ThreadStatus


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("deletion-saga-db")
    materialize_schema(Path(case_dir / "test.db"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
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


async def _seed_terminal_thread(
    session_factory: async_sessionmaker[AsyncSession], thread_id: str = "t-del"
) -> str:
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
            "artifact:a1", CleanupItemState.FAILED, detail="locked", attempts=2
        ),
    }
    restored_results = deserialize_results(serialize_results(results))
    assert restored_results == results


def test_a_ledger_written_before_attempt_counts_restores_at_zero() -> None:
    """A result recorded by an earlier build restores without a migration."""
    legacy = '{"checkpoint": {"key": "checkpoint", "state": "failed", "detail": "x"}}'
    restored = deserialize_results(legacy)
    assert restored["checkpoint"] == CleanupItemResult(
        "checkpoint", CleanupItemState.FAILED, detail="x", attempts=0
    )


@pytest.mark.asyncio
async def test_create_transitions_thread_and_captures_manifest(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
    session_factory: async_sessionmaker[AsyncSession],
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
async def test_claim_stamps_ownership_once_and_refuses_a_second_pass(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The first claim owns the saga; a second pass is refused while it is live.

    Ownership that is recorded but not enforced is not ownership: a second pass
    admitted here takes a result snapshot predating the first pass's progress,
    and its ledger write drops the first pass's recorded item permanently.
    """
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
        assert first.owned is True
        assert first.claimed is True
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        assert row is not None
        stamped = row.claimed_at

    async with session_factory() as session:
        again = await claim_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert again is not None
        # The saga exists and is marked claimed, but this caller does not own it.
        assert again.claimed is True
        assert again.owned is False
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        assert row is not None
        assert row.claimed_at == stamped


@pytest.mark.asyncio
async def test_concurrent_claims_grant_exactly_one_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two delete requests racing for one saga produce exactly one cleanup pass."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    async def _claim() -> bool:
        async with session_factory() as session:
            saga = await claim_deletion_saga(session, thread_id=thread_id)
            await session.commit()
            assert saga is not None
            return saga.owned

    owners = await asyncio.gather(*(_claim() for _ in range(4)))
    assert sum(owners) == 1


@pytest.mark.asyncio
async def test_a_claim_left_by_a_dead_pass_is_reclaimable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An expired claim is granted again so exclusion is not its own wedge.

    A pass killed mid-teardown leaves the ownership marker behind. If that
    marker excluded every later pass forever, the thread would stay hidden with
    its rows intact - exactly the failure exclusion exists to prevent.
    """
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    async with session_factory() as session:
        first = await claim_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert first is not None and first.owned is True

    # The owning pass dies; its claim ages past the lease.
    async with session_factory() as session:
        await session.execute(
            update(ThreadDeletionSagaModel)
            .where(ThreadDeletionSagaModel.thread_id == thread_id)
            .values(claimed_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()

    async with session_factory() as session:
        resumed = await claim_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert resumed is not None
        assert resumed.owned is True


@pytest.mark.asyncio
async def test_claim_absent_saga_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Claiming a saga that does not exist reports absence rather than raising."""
    async with session_factory() as session:
        assert await claim_deletion_saga(session, thread_id="missing") is None


@pytest.mark.asyncio
async def test_advance_records_and_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
        assert row is not None
        results = deserialize_results(row.result_json)
        assert results["checkpoint"].state is CleanupItemState.DONE


@pytest.mark.asyncio
async def test_advance_supersedes_a_prior_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
        assert row is not None
        results = deserialize_results(row.result_json)
        assert results["artifact:a1"].state is CleanupItemState.DONE


@pytest.mark.asyncio
async def test_concurrent_advances_preserve_every_recorded_item(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Results recorded concurrently all survive; none is overwritten.

    Every item's result lives in one serialized blob, so passes advancing at the
    same time read and rewrite the same value. A write built on a read taken
    before another's commit would drop that item permanently - the manifest
    could never settle, finalization would refuse forever, and the thread would
    stay hidden with its rows intact. This drives real concurrent sessions
    against a real database rather than a simulated interleaving.
    """
    thread_id = await _seed_terminal_thread(session_factory)
    keys = tuple(f"artifact:a{index}" for index in range(6))
    manifest = [
        CleanupItem(
            kind=CleanupKind.ARTIFACT_FILE,
            key=key,
            target=f"/ws/out/{key}.md",
            root="/ws",
        )
        for key in keys
    ]
    async with session_factory() as session:
        await create_deletion_saga(session, thread_id=thread_id, manifest=manifest)
        await session.commit()

    async def _advance(key: str) -> None:
        async with session_factory() as session:
            await advance_deletion_cleanup_item(
                session,
                thread_id=thread_id,
                result=CleanupItemResult(key, CleanupItemState.DONE),
            )
            await session.commit()

    await asyncio.gather(*(_advance(key) for key in keys))

    async with session_factory() as session:
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        assert row is not None
        results = deserialize_results(row.result_json)
    assert sorted(results) == sorted(keys)
    assert all(results[key].state is CleanupItemState.DONE for key in keys), results

    # The real cost of a dropped result is a saga that can never finalize.
    async with session_factory() as session:
        outcome = await finalize_deletion_saga(session, thread_id=thread_id)
        await session.commit()
        assert outcome.finalized is True


@pytest.mark.asyncio
async def test_repeated_failures_abandon_the_item_and_release_the_saga(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An item that keeps failing becomes terminal instead of blocking forever.

    Without a ceiling, one target that can never be removed keeps the saga
    unfinalizable for the life of the deployment: the thread is hidden from
    product reads, every retry re-runs the same failing item, and finalization
    refuses. The ceiling converts that into a recorded, bounded leak.
    """
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await advance_deletion_cleanup_item(
            session,
            thread_id=thread_id,
            result=CleanupItemResult("checkpoint", CleanupItemState.DONE),
        )
        await session.commit()

    failure = CleanupItemResult(
        "artifact:a1", CleanupItemState.FAILED, detail="permission denied"
    )
    states: list[CleanupItemState] = []
    for _ in range(3):
        async with session_factory() as session:
            # Each pass re-runs the item, records the same failure, and refuses
            # to finalize until the item stops being retryable.
            assert await advance_deletion_cleanup_item(
                session, thread_id=thread_id, result=failure
            )
            row = await session.get(ThreadDeletionSagaModel, thread_id)
            assert row is not None
            states.append(deserialize_results(row.result_json)["artifact:a1"].state)
            outcome = await finalize_deletion_saga(session, thread_id=thread_id)
            await session.commit()

    assert states == [
        CleanupItemState.FAILED,
        CleanupItemState.FAILED,
        CleanupItemState.ABANDONED,
    ]
    assert outcome.finalized is True
    assert [item.key for item in outcome.abandoned] == ["artifact:a1"]
    assert outcome.abandoned[0].detail == "permission denied"
    assert outcome.abandoned[0].attempts == 3
    # The reportable projection of the same fact: the kind of state stranded,
    # read off the manifest, with no key, path, or diagnostic detail in it.
    assert outcome.abandoned_kinds == (CleanupKind.ARTIFACT_FILE,)

    async with session_factory() as session:
        assert await get_thread(session, thread_id) is None
        assert await session.get(ThreadDeletionSagaModel, thread_id) is None


@pytest.mark.asyncio
async def test_abandoned_kinds_are_distinct_and_follow_manifest_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every stranded kind is reported once, in the manifest's own order.

    The reportable projection has to answer "what class of state was left
    behind", so two abandoned artifact files are one kind, not two, and the
    order cannot depend on how the result ledger happens to iterate.
    """
    thread_id = await _seed_terminal_thread(session_factory)
    manifest = [
        *_manifest(thread_id),
        CleanupItem(
            kind=CleanupKind.ARTIFACT_FILE,
            key="artifact:a2",
            target="/ws/out/second.md",
            root="/ws",
        ),
    ]
    async with session_factory() as session:
        await create_deletion_saga(session, thread_id=thread_id, manifest=manifest)
        await session.commit()

    for _ in range(3):
        async with session_factory() as session:
            for key in ("artifact:a2", "artifact:a1", "checkpoint"):
                await advance_deletion_cleanup_item(
                    session,
                    thread_id=thread_id,
                    result=CleanupItemResult(
                        key, CleanupItemState.FAILED, detail="unreachable store"
                    ),
                )
            await session.commit()

    async with session_factory() as session:
        outcome = await finalize_deletion_saga(session, thread_id=thread_id)
        await session.commit()

    assert outcome.finalized is True
    assert sorted(item.key for item in outcome.abandoned) == [
        "artifact:a1",
        "artifact:a2",
        "checkpoint",
    ]
    assert outcome.abandoned_kinds == (
        CleanupKind.CHECKPOINT,
        CleanupKind.ARTIFACT_FILE,
    )


@pytest.mark.asyncio
async def test_a_success_after_abandonment_still_supersedes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A retry that finally cleans an abandoned item records it as done."""
    thread_id = await _seed_terminal_thread(session_factory)
    async with session_factory() as session:
        await create_deletion_saga(
            session, thread_id=thread_id, manifest=_manifest(thread_id)
        )
        await session.commit()

    async with session_factory() as session:
        for _ in range(3):
            await advance_deletion_cleanup_item(
                session,
                thread_id=thread_id,
                result=CleanupItemResult(
                    "artifact:a1", CleanupItemState.FAILED, detail="locked"
                ),
            )
        await session.commit()
        row = await session.get(ThreadDeletionSagaModel, thread_id)
        assert row is not None
        assert (
            deserialize_results(row.result_json)["artifact:a1"].state
            is CleanupItemState.ABANDONED
        )

    async with session_factory() as session:
        assert await advance_deletion_cleanup_item(
            session,
            thread_id=thread_id,
            result=CleanupItemResult("artifact:a1", CleanupItemState.DONE),
        )
        await advance_deletion_cleanup_item(
            session,
            thread_id=thread_id,
            result=CleanupItemResult("checkpoint", CleanupItemState.DONE),
        )
        outcome = await finalize_deletion_saga(session, thread_id=thread_id)
        await session.commit()

    assert outcome.finalized is True
    # A cleanly finished saga reports nothing abandoned.
    assert outcome.abandoned == ()
    assert outcome.abandoned_kinds == ()


@pytest.mark.asyncio
async def test_finalize_refuses_until_every_item_is_done(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
async def test_finalize_removes_rows_only_when_complete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
async def test_finalize_is_idempotent_after_completion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
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
