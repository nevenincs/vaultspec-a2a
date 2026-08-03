"""Round-trip accounting for startup reconciliation against a real SQLite store.

Startup reconciliation runs before the gateway serves, so its cost is paid as
readiness latency proportional to the non-terminal backlog. These tests count the
statements SQLAlchemy actually sends - through the engine's own cursor-execute
event, not a substitute for the engine - and pin which of them are now answered
once per pass rather than once per thread.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...conftest import materialize_schema
from ..permission_repository import (
    get_threads_with_pending_permission_requests,
    record_permission_request,
)
from ..reconciliation import reconcile_threads_on_startup
from ..thread_repository import create_thread, get_thread

if TYPE_CHECKING:
    from collections.abc import Iterator


class _StatementLog:
    """Every SQL statement the engine executed inside the recording window."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def against(self, table: str, verb: str) -> int:
        """Count statements of ``verb`` naming ``table``."""
        wanted = verb.lower()
        return sum(
            1
            for sql in self.statements
            if sql.lstrip().lower().startswith(wanted) and table in sql.lower()
        )


@contextmanager
def _record(engine: AsyncEngine) -> Iterator[_StatementLog]:
    """Record the statements issued on ``engine`` for the duration of the block."""
    log = _StatementLog()

    def _on_execute(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        log.statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield log
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on_execute)


async def _store(
    runtime_dir: Path, name: str
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    db_file = runtime_dir / name
    materialize_schema(Path(db_file))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    return engine, async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_permission(session: AsyncSession, thread_id: str) -> None:
    await record_permission_request(
        session,
        request_id=f"{thread_id}:perm",
        thread_id=thread_id,
        pause_reason_type="bash",
        description="Allow action?",
        allowed_options=[
            {"option_id": "allow_once", "name": "Allow once", "kind": "allow_once"}
        ],
        tool_call="bash",
    )


@pytest.mark.asyncio
async def test_pending_permission_lookup_is_one_statement_for_the_backlog(
    runtime_dir: Path,
) -> None:
    """The membership test over the whole backlog costs one query, not N."""
    engine, sessions = await _store(runtime_dir, "pending-lookup.db")
    thread_ids = [f"thread-{index:02d}" for index in range(12)]
    with_pending = {"thread-01", "thread-04", "thread-09"}

    async with sessions() as session:
        for thread_id in thread_ids:
            await create_thread(session, thread_id=thread_id, status="running")
            if thread_id in with_pending:
                await _seed_permission(session, thread_id)
        await session.commit()

    with _record(engine) as log:
        async with sessions() as session:
            found = await get_threads_with_pending_permission_requests(
                session,
                thread_ids,
                include_answered_pending_apply=False,
            )

    assert found == with_pending
    assert log.against("permission_requests", "select") == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_permission_lookup_chunks_past_the_parameter_cap(
    runtime_dir: Path,
) -> None:
    """A backlog wider than one IN clause splits, rather than failing to bind."""
    engine, sessions = await _store(runtime_dir, "pending-lookup-chunked.db")
    thread_ids = [f"thread-{index:05d}" for index in range(1200)]

    async with sessions() as session:
        await create_thread(session, thread_id=thread_ids[700], status="running")
        await _seed_permission(session, thread_ids[700])
        await session.commit()

    with _record(engine) as log:
        async with sessions() as session:
            found = await get_threads_with_pending_permission_requests(
                session, thread_ids
            )

    assert found == {thread_ids[700]}
    # 1200 identifiers at 500 per chunk.
    assert log.against("permission_requests", "select") == 3
    await engine.dispose()


async def _reconcile_backlog(
    runtime_dir: Path, tag: str, backlog: int
) -> tuple[_StatementLog, dict[str, int]]:
    """Reconcile ``backlog`` checkpointed, permission-pending threads once."""
    engine, sessions = await _store(runtime_dir, f"reconcile-{tag}.db")
    checkpoints_file = runtime_dir / f"reconcile-{tag}-checkpoints.db"
    thread_ids = [f"{tag}-thread-{index:03d}" for index in range(backlog)]

    async with AsyncSqliteSaver.from_conn_string(str(checkpoints_file)) as checkpointer:
        await checkpointer.setup()
        for thread_id in thread_ids:
            checkpoint = empty_checkpoint()
            checkpoint["id"] = f"cp-{thread_id}"
            await checkpointer.aput(
                {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
                checkpoint,
                {"source": "loop", "step": 1, "parents": {}},
                {},
            )

        async with sessions() as session:
            for thread_id in thread_ids:
                await create_thread(session, thread_id=thread_id, status="running")
                await _seed_permission(session, thread_id)
            await session.commit()

        with _record(engine) as log:
            async with sessions() as session:
                summary = await reconcile_threads_on_startup(session, checkpointer)
                await session.commit()

        async with sessions() as session:
            for thread_id in thread_ids:
                repaired = await get_thread(session, thread_id)
                assert repaired is not None, thread_id
                assert repaired.status == "input_required"
                assert repaired.repair_status == "paused_resumable"

    await engine.dispose()
    return log, summary


@pytest.mark.asyncio
async def test_reconciliation_lookups_do_not_scale_with_the_backlog(
    runtime_dir: Path,
) -> None:
    """The two per-thread read loops are now one query each, at any backlog size.

    Both the pending-permission membership test and the control-action journal
    existence check were issued once per non-terminal thread. Holding their cost
    flat across a 4x larger backlog is the whole point of the change, so the
    assertion is on the count itself and not on elapsed time.

    The writes are deliberately still per row: each journal insert is a distinct
    row guarded by its own idempotency race, and each thread's status and repair
    state are its own update. Those counts are asserted too, so a later change
    that quietly restructures the transaction shows up here.
    """
    small_log, small_summary = await _reconcile_backlog(runtime_dir, "small", 4)
    large_log, large_summary = await _reconcile_backlog(runtime_dir, "large", 16)

    assert small_summary == {
        "repair_backlog": 4,
        "paused_resumable": 4,
        "checkpoint_unavailable": 0,
    }
    assert large_summary == {
        "repair_backlog": 16,
        "paused_resumable": 16,
        "checkpoint_unavailable": 0,
    }

    for log in (small_log, large_log):
        assert log.against("permission_requests", "select") == 1
        assert log.against("control_actions", "select") == 1

    # Unchanged and honest: two journal rows written per thread.
    assert small_log.against("control_actions", "insert") == 8
    assert large_log.against("control_actions", "insert") == 32
