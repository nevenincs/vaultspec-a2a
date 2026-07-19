"""Real-database performance checks for indexed active-run discovery."""

from __future__ import annotations

import os
import statistics
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ...control.run_discovery_service import discover_active_runs
from ..models import Base, ThreadModel
from ..thread_repository import _active_thread_page_statement

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

_HISTORY_ROWS = 100_000


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine]:
    database = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as database_session:
        yield database_session


@pytest.mark.asyncio
async def test_active_discovery_stays_indexed_and_bounded_at_large_history(
    engine: AsyncEngine,
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    """A 100k-row history must not turn the bounded read into a table scan."""
    workspace = os.path.normcase(os.path.realpath(tmp_path / "workspace"))
    foreign_workspace = os.path.normcase(os.path.realpath(tmp_path / "foreign"))
    started_at = datetime(2026, 7, 19, tzinfo=UTC)
    insert_statement = insert(ThreadModel)

    for offset in range(0, _HISTORY_ROWS, 5_000):
        batch = []
        for index in range(offset, min(offset + 5_000, _HISTORY_ROWS)):
            matching = index >= _HISTORY_ROWS - 10
            created_at = started_at + timedelta(microseconds=index)
            batch.append(
                {
                    "id": f"history-{index:06d}",
                    "created_at": created_at,
                    "updated_at": created_at,
                    "status": "running" if matching else "completed",
                    "is_active": matching,
                    "workspace_root": workspace if matching else foreign_workspace,
                    "feature_tag": "a2a" if matching else "other",
                }
            )
        await session.execute(insert_statement, batch)
    await session.commit()

    statement = _active_thread_page_statement(
        limit=6,
        workspace_root=workspace,
        feature_tag="a2a",
        after_created_at=None,
        after_id=None,
    )
    compiled = statement.compile(
        dialect=engine.sync_engine.dialect,
        compile_kwargs={"literal_binds": True},
    )
    plan = (await session.execute(text(f"EXPLAIN QUERY PLAN {compiled}"))).all()
    plan_details = "\n".join(str(row[-1]) for row in plan)

    assert "ix_threads_active_workspace_feature_order" in plan_details
    assert "SCAN threads" not in plan_details
    assert "USE TEMP B-TREE" not in plan_details

    feature_statement = _active_thread_page_statement(
        limit=6,
        workspace_root=None,
        feature_tag="a2a",
        after_created_at=None,
        after_id=None,
    )
    feature_compiled = feature_statement.compile(
        dialect=engine.sync_engine.dialect,
        compile_kwargs={"literal_binds": True},
    )
    feature_plan = (
        await session.execute(text(f"EXPLAIN QUERY PLAN {feature_compiled}"))
    ).all()
    feature_plan_details = "\n".join(str(row[-1]) for row in feature_plan)

    assert "ix_threads_active_feature_order" in feature_plan_details
    assert "SCAN threads" not in feature_plan_details
    assert "USE TEMP B-TREE" not in feature_plan_details

    await discover_active_runs(
        session,
        workspace_root=tmp_path / "workspace",
        feature_tag="a2a",
        limit=5,
    )
    samples_ms = []
    tracemalloc.start()
    try:
        for _ in range(20):
            before = time.perf_counter()
            result = await discover_active_runs(
                session,
                workspace_root=tmp_path / "workspace",
                feature_tag="a2a",
                limit=5,
            )
            samples_ms.append((time.perf_counter() - before) * 1_000)
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert [run.run_id for run in result.runs] == [
        "history-099999",
        "history-099998",
        "history-099997",
        "history-099996",
        "history-099995",
    ]
    assert result.truncated is True
    p95_ms = statistics.quantiles(samples_ms, n=20)[-1]
    assert p95_ms < 250, {"p95_ms": p95_ms, "samples_ms": samples_ms}
    assert peak_bytes < 5 * 1024 * 1024, {
        "peak_bytes": peak_bytes,
        "samples_ms": samples_ms,
    }
