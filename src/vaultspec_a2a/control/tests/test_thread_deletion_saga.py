"""End-to-end proofs of failure-atomic thread deletion against real stores.

The deletion saga's promise is narrow and load-bearing: control state stays
authoritative until every store is clean, so an interrupted delete resumes one
durable saga, a replayed delete does not delete twice, a thread under teardown
stays hidden, and control rows are removed only after the checkpoint and
artifact cleanup finish. These drive the real coordinator against a real SQLite
control database and a real AsyncSqliteSaver checkpoint store - no mocks - and
assert on the rows and checkpoints that survive.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

from vaultspec_a2a.control.repositories import (
    CleanupItem,
    CleanupItemResult,
    CleanupItemState,
    CleanupKind,
    advance_deletion_cleanup_item,
    create_deletion_saga,
    finalize_deletion_saga,
)
from vaultspec_a2a.control.thread_service import delete_thread_service
from vaultspec_a2a.database import create_artifact, create_thread, get_thread
from vaultspec_a2a.database.models import Base, ThreadDeletionSagaModel
from vaultspec_a2a.thread.enums import ThreadStatus


@pytest_asyncio.fixture
async def session_factory(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("deletion-saga-control-db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{case_dir / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def checkpointer(tmp_path_factory: pytest.TempPathFactory):
    case_dir = tmp_path_factory.mktemp("deletion-saga-checkpoints")
    async with AsyncSqliteSaver.from_conn_string(
        str(case_dir / "checkpoints.db")
    ) as saver:
        await saver.setup()
        yield saver


def _config(thread_id: str, namespace: str = "") -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace}}


async def _write_checkpoint(
    checkpointer: AsyncSqliteSaver, thread_id: str, checkpoint_id: str
) -> None:
    checkpoint = empty_checkpoint()
    checkpoint["id"] = checkpoint_id
    await checkpointer.aput(
        _config(thread_id),
        checkpoint,
        {"source": "loop", "step": 1, "parents": {}},
        {},
    )


async def _checkpoint_present(checkpointer: AsyncSqliteSaver, thread_id: str) -> bool:
    return await checkpointer.aget_tuple(_config(thread_id)) is not None


@pytest.mark.asyncio
async def test_delete_removes_checkpoint_and_artifact_end_to_end(
    session_factory, checkpointer, tmp_path
) -> None:
    """A terminal thread's checkpoint, artifact file, and rows are all removed."""
    workspace = tmp_path / "workspace"
    (workspace / "outputs").mkdir(parents=True)
    artifact_file = workspace / "outputs" / "report.md"
    artifact_file.write_text("body", encoding="utf-8")

    await _write_checkpoint(checkpointer, "t-e2e", "cp-e2e")
    async with session_factory() as session:
        await create_thread(
            session,
            thread_id="t-e2e",
            status=ThreadStatus.COMPLETED,
            metadata=json.dumps({"workspace_root": workspace.as_posix()}),
        )
        await create_artifact(
            session,
            thread_id="t-e2e",
            artifact_type="file",
            path="outputs/report.md",
        )
        await session.commit()

    async with session_factory() as session:
        result = await delete_thread_service(
            session, "t-e2e", checkpointer=checkpointer
        )

    assert result.deleted is True
    assert not artifact_file.exists()
    assert await _checkpoint_present(checkpointer, "t-e2e") is False
    async with session_factory() as session:
        assert await get_thread(session, "t-e2e") is None
        assert await session.get(ThreadDeletionSagaModel, "t-e2e") is None


@pytest.mark.asyncio
async def test_delete_is_idempotent_under_retry(session_factory, checkpointer) -> None:
    """A second delete of an already-deleted thread reports it not found."""
    await _write_checkpoint(checkpointer, "t-retry", "cp-retry")
    async with session_factory() as session:
        await create_thread(session, thread_id="t-retry", status=ThreadStatus.COMPLETED)
        await session.commit()

    async with session_factory() as session:
        first = await delete_thread_service(
            session, "t-retry", checkpointer=checkpointer
        )
    async with session_factory() as session:
        second = await delete_thread_service(
            session, "t-retry", checkpointer=checkpointer
        )

    assert first.deleted is True
    assert second.deleted is False
    assert second.not_found is True


@pytest.mark.asyncio
async def test_crash_recovery_resumes_a_partial_saga(
    session_factory, checkpointer
) -> None:
    """A saga left mid-flight by a crash resumes and finishes against real stores."""
    await _write_checkpoint(checkpointer, "t-crash", "cp-crash")
    # A crashed first pass: the thread is deleting and the saga exists with its
    # checkpoint item still outstanding.
    async with session_factory() as session:
        await create_thread(session, thread_id="t-crash", status=ThreadStatus.COMPLETED)
        await create_deletion_saga(
            session,
            thread_id="t-crash",
            manifest=[
                CleanupItem(
                    kind=CleanupKind.CHECKPOINT, key="checkpoint", target="t-crash"
                )
            ],
        )
        await session.commit()

    assert await _checkpoint_present(checkpointer, "t-crash") is True

    async with session_factory() as session:
        result = await delete_thread_service(
            session, "t-crash", checkpointer=checkpointer
        )

    assert result.deleted is True
    assert await _checkpoint_present(checkpointer, "t-crash") is False
    async with session_factory() as session:
        assert await get_thread(session, "t-crash") is None
        assert await session.get(ThreadDeletionSagaModel, "t-crash") is None


@pytest.mark.asyncio
async def test_control_rows_survive_until_cleanup_finishes(
    session_factory, checkpointer
) -> None:
    """Control rows are retained and the thread hidden-state held while pending.

    A saga with an outstanding item must not finalize: the thread stays present
    in the ``deleting`` state and the saga row remains, so nothing reports the
    thread deleted while its checkpoint still exists.
    """
    await _write_checkpoint(checkpointer, "t-pending", "cp-pending")
    async with session_factory() as session:
        await create_thread(
            session, thread_id="t-pending", status=ThreadStatus.COMPLETED
        )
        await create_deletion_saga(
            session,
            thread_id="t-pending",
            manifest=[
                CleanupItem(
                    kind=CleanupKind.CHECKPOINT, key="checkpoint", target="t-pending"
                ),
                CleanupItem(
                    kind=CleanupKind.ARTIFACT_FILE,
                    key="artifact:a1",
                    target="/ws/out/report.md",
                    root="/ws",
                ),
            ],
        )
        # Only the checkpoint item completes; the artifact item stays outstanding.
        await advance_deletion_cleanup_item(
            session,
            thread_id="t-pending",
            result=CleanupItemResult("checkpoint", CleanupItemState.DONE),
        )
        await session.commit()

    async with session_factory() as session:
        outcome = await finalize_deletion_saga(session, thread_id="t-pending")
        await session.commit()

    assert outcome.finalized is False
    async with session_factory() as session:
        thread = await get_thread(session, "t-pending")
        assert thread is not None
        assert thread.status == ThreadStatus.DELETING.value
        assert await session.get(ThreadDeletionSagaModel, "t-pending") is not None
