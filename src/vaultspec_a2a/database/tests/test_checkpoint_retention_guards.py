"""Retention writes to another library's tables only when it still may.

Pruning is a stand-in: the savers this project ships offer no pruning of their
own, so the statements go straight at their tables. That is safe only while
three conditions hold, and recognising the saver's CLASS - which is all the
retention code used to do - establishes none of them.

Each test here breaks exactly one condition against a real store and requires
the store to come back untouched, because the failure mode is silent: the
deletes succeed and the damage shows up on the next read.
"""

from __future__ import annotations

import operator
import os
import sqlite3
from collections import defaultdict
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast
from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.channels.delta import DeltaChannel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ..checkpoint_retention import prune_settled_checkpoints

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from langgraph.graph.state import CompiledStateGraph

    from ...conftest import ExternalPrerequisiteRule
    from ..checkpoints import Checkpointer

_POSTGRES_URL_ENV = "VAULTSPEC_A2A_TEST_POSTGRES_URL"


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def _history(saver: Checkpointer, thread_id: str) -> dict[str, list[str]]:
    by_namespace: dict[str, list[str]] = defaultdict(list)
    async for item in saver.alist(cast("Any", _config(thread_id))):
        configurable = item.config["configurable"]
        by_namespace[configurable["checkpoint_ns"]].append(
            configurable["checkpoint_id"]
        )
    return dict(by_namespace)


class _Log(TypedDict):
    log: Annotated[list[str], operator.add]


def _plain_graph(saver: Checkpointer) -> CompiledStateGraph[Any, Any, Any, Any]:
    async def step(state: _Log) -> dict[str, list[str]]:
        del state
        return {"log": ["step"]}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Log))
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=saver)


def _accumulate(state: Any, writes: Sequence[Any]) -> list[str]:
    return [*(state or []), *(str(write) for write in writes)]


class _DeltaLog(TypedDict):
    # snapshot_frequency high enough that the surviving latest checkpoint is
    # not a snapshot point, which is exactly the case a prune would break.
    log: Annotated[list[str], DeltaChannel(_accumulate, list, snapshot_frequency=1000)]


def _delta_graph(saver: Checkpointer) -> CompiledStateGraph[Any, Any, Any, Any]:
    async def step(state: _DeltaLog) -> dict[str, list[str]]:
        del state
        return {"log": ["step"]}

    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _DeltaLog))
    builder.add_node("step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return builder.compile(checkpointer=saver)


@pytest_asyncio.fixture
async def sqlite_saver(tmp_path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:
        await saver.setup()
        yield saver


@pytest.mark.asyncio
async def test_a_delta_channel_thread_is_left_alone(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    """Its value lives in the history, so deleting the history deletes the value.

    A delta channel stores a sentinel and rebuilds state by walking back to the
    nearest snapshot. Pruning to the latest checkpoint severs that walk, and
    nothing raises: the channel simply reconstructs as empty. The guard is the
    only thing standing between a settled delta thread and silent data loss.
    """
    graph = _delta_graph(sqlite_saver)
    thread_id = f"delta-{uuid4()}"
    for turn in ("one", "two", "three"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", _config(thread_id))
        )
    before = await _history(sqlite_saver, thread_id)
    settled = (await graph.aget_state(cast("Any", _config(thread_id)))).values
    assert settled["log"], "the delta channel must hold a value to lose"
    assert all(len(ids) > 1 for ids in before.values())

    assert await prune_settled_checkpoints(sqlite_saver, thread_id) is False

    assert await _history(sqlite_saver, thread_id) == before
    assert (await graph.aget_state(cast("Any", _config(thread_id)))).values == settled


@pytest.mark.asyncio
async def test_a_plain_thread_on_the_same_store_is_still_pruned(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    """The delta guard is per thread, not a blanket refusal for the store."""
    graph = _plain_graph(sqlite_saver)
    thread_id = f"plain-{uuid4()}"
    for turn in ("one", "two"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", _config(thread_id))
        )
    before = await _history(sqlite_saver, thread_id)
    assert all(len(ids) > 1 for ids in before.values())

    assert await prune_settled_checkpoints(sqlite_saver, thread_id) is True

    assert await _history(sqlite_saver, thread_id) == {
        namespace: [max(ids)] for namespace, ids in before.items()
    }


@pytest.mark.asyncio
async def test_a_sqlite_store_with_another_table_layout_is_refused(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    """SQLite keeps no migration ledger, so the tables are their own version.

    A column the saver did not have when these deletes were written is a
    layout they were not written for, and the class of the saver holding it
    says nothing about that.
    """
    graph = _plain_graph(sqlite_saver)
    thread_id = f"layout-{uuid4()}"
    for turn in ("one", "two"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", _config(thread_id))
        )
    before = await _history(sqlite_saver, thread_id)
    await sqlite_saver.conn.execute("ALTER TABLE writes ADD COLUMN retained INTEGER")
    await sqlite_saver.conn.commit()

    assert await prune_settled_checkpoints(sqlite_saver, thread_id) is False

    assert await _history(sqlite_saver, thread_id) == before


@pytest.mark.asyncio
async def test_a_saver_that_prunes_itself_is_asked_to(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    """A saver's own pruning is authoritative where these statements guess.

    Neither shipped saver implements it today, so this drives the branch with
    a real saver subclass that does - the shape a LangGraph release adding
    ``aprune`` would take.
    """
    calls: list[tuple[list[str], str]] = []

    class _PruningSaver(AsyncSqliteSaver):
        async def aprune(
            self, thread_ids: Any, *, strategy: str = "keep_latest"
        ) -> None:
            calls.append((list(thread_ids), strategy))

    saver = _PruningSaver(sqlite_saver.conn)
    saver.is_setup = True
    graph = _plain_graph(saver)
    thread_id = f"self-pruning-{uuid4()}"
    for turn in ("one", "two"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", _config(thread_id))
        )
    before = await _history(saver, thread_id)

    assert await prune_settled_checkpoints(saver, thread_id) is True

    # The saver was asked, and the direct statements did not also run.
    assert calls == [([thread_id], "keep_latest")]
    assert await _history(saver, thread_id) == before
    assert type(saver).aprune is not BaseCheckpointSaver.aprune


@pytest_asyncio.fixture
async def postgres_saver(
    external_prerequisite: ExternalPrerequisiteRule,
) -> AsyncIterator[Any]:
    """The production pooled Postgres saver against the live server."""
    external_prerequisite("postgres")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from ..checkpoints import _postgres_checkpoint_pool, setup_postgres_checkpointer

    pool = _postgres_checkpoint_pool(os.environ[_POSTGRES_URL_ENV])
    await pool.open(wait=True)
    try:
        saver = AsyncPostgresSaver(conn=pool)
        await setup_postgres_checkpointer(saver, pool)
        yield saver
    finally:
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.requires_prerequisites("postgres")
async def test_a_postgres_store_at_another_schema_version_is_refused(
    postgres_saver: Any,
) -> None:
    """The saver's class is not its schema; its migration ledger is.

    A store the saver has migrated past the version these statements were
    written against must be left alone, and the ledger is where that shows.
    """
    graph = _plain_graph(postgres_saver)
    thread_id = f"pg-version-{uuid4()}"
    try:
        for turn in ("one", "two"):
            await graph.ainvoke(
                cast("Any", {"log": [turn]}), cast("Any", _config(thread_id))
            )
        before = await _history(postgres_saver, thread_id)
        assert all(len(ids) > 1 for ids in before.values())

        async with postgres_saver.conn.connection() as connection:
            cursor = await connection.execute(
                "SELECT MAX(v) AS v FROM checkpoint_migrations"
            )
            row = await cursor.fetchone()
            ahead = int(row["v"]) + 1
            await connection.execute(
                "INSERT INTO checkpoint_migrations (v) VALUES (%s)", (ahead,)
            )
        try:
            assert await prune_settled_checkpoints(postgres_saver, thread_id) is False
            assert await _history(postgres_saver, thread_id) == before
        finally:
            async with postgres_saver.conn.connection() as connection:
                await connection.execute(
                    "DELETE FROM checkpoint_migrations WHERE v = %s", (ahead,)
                )

        # Back at the version the statements were written for, it prunes again.
        assert await prune_settled_checkpoints(postgres_saver, thread_id) is True
        assert await _history(postgres_saver, thread_id) == {
            namespace: [max(ids)] for namespace, ids in before.items()
        }
    finally:
        await postgres_saver.adelete_thread(thread_id)


@pytest.mark.asyncio
async def test_a_sqlite_prune_still_rolls_back_a_failure(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    """The guards must not have moved the rollback off the failure path.

    The saver shares one connection, so deletes a failed prune leaves open are
    committed by its next write.
    """
    graph = _plain_graph(sqlite_saver)
    thread_id = f"refused-{uuid4()}"
    await graph.ainvoke(cast("Any", {"log": ["one"]}), cast("Any", _config(thread_id)))
    before = await _history(sqlite_saver, thread_id)
    await sqlite_saver.conn.execute(
        "CREATE TRIGGER refuse_prune BEFORE DELETE ON checkpoints "
        "BEGIN SELECT RAISE(ABORT, 'prune refused'); END"
    )
    await sqlite_saver.conn.commit()

    with pytest.raises(sqlite3.DatabaseError, match="prune refused"):
        await prune_settled_checkpoints(sqlite_saver, thread_id)

    await sqlite_saver.conn.execute("DROP TRIGGER refuse_prune")
    await graph.ainvoke(cast("Any", {"log": ["two"]}), cast("Any", _config("other")))

    assert await _history(sqlite_saver, thread_id) == before
