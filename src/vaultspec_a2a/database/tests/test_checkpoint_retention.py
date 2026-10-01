"""A settled thread keeps only its latest checkpoint, on every shipped saver.

Real graphs run to completion (and to failure) on a real SQLite file and on a
real PostgreSQL server - through a single connection, through a connection
pool, and through the selector-thread saver Windows uses - and the pruned
thread must read back exactly as it did before, resume where it stood, and
leave every other thread alone.
"""

from __future__ import annotations

import operator
import os
import sqlite3
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast
from uuid import uuid4

import pytest
import pytest_asyncio
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ...graph.tests._state_graph_helpers import add_test_node, compile_test_graph
from ..checkpoints import _SelectorThreadPostgresCheckpointer, prune_settled_thread
from ._checkpoint_history import config_for, stored_history

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ...conftest import ExternalPrerequisiteRule
    from ..checkpoints import Checkpointer

_POSTGRES_URL_ENV = "VAULTSPEC_A2A_TEST_POSTGRES_URL"


class _Log(TypedDict):
    log: Annotated[list[str], operator.add]


def _append(entry: str) -> Any:
    async def node(state: _Log) -> dict[str, list[str]]:
        del state
        return {"log": [entry]}

    return node


async def _fail(state: _Log) -> dict[str, list[str]]:
    del state
    raise RuntimeError("the step failed")


def _settling_graph(saver: Checkpointer) -> Any:
    inner: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Log))
    add_test_node(inner, "inner_step", _append("inner"))
    inner.add_edge(START, "inner_step")
    inner.add_edge("inner_step", END)

    outer: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Log))
    add_test_node(outer, "first", _append("first"))
    add_test_node(outer, "nested", compile_test_graph(inner))
    add_test_node(outer, "last", _append("last"))
    outer.add_edge(START, "first")
    outer.add_edge("first", "nested")
    outer.add_edge("nested", "last")
    outer.add_edge("last", END)
    return compile_test_graph(outer, checkpointer=saver)


def _failing_graph(saver: Checkpointer) -> Any:
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", _Log))
    add_test_node(builder, "first", _append("first"))
    add_test_node(builder, "sibling", _append("sibling"))
    add_test_node(builder, "boom", _fail)
    builder.add_edge(START, "first")
    builder.add_edge("first", "sibling")
    builder.add_edge("first", "boom")
    builder.add_edge("sibling", END)
    builder.add_edge("boom", END)
    return compile_test_graph(builder, checkpointer=saver)


async def _prove_a_settled_thread_keeps_only_its_latest(saver: Checkpointer) -> None:
    graph = _settling_graph(saver)
    # The control thread takes the same turns and is never pruned: it is both
    # the neighbour pruning must not touch and the reference the pruned thread
    # must keep matching.
    thread_id, control_id = f"settled-{uuid4()}", f"control-{uuid4()}"
    try:
        for turn in ("one", "two"):
            for target in (thread_id, control_id):
                await graph.ainvoke(
                    cast("Any", {"log": [turn]}), cast("Any", config_for(target))
                )
        before = await stored_history(saver, thread_id)
        control_before = await stored_history(saver, control_id)
        settled = (await graph.aget_state(cast("Any", config_for(thread_id)))).values
        # The root namespace plus one subgraph namespace per turn, each with a
        # history - otherwise there is nothing for retention to prove.
        assert len(before) == 3
        assert all(len(ids) > 1 for ids in before.values())

        assert await prune_settled_thread(saver, thread_id) is True

        assert await stored_history(saver, thread_id) == {
            namespace: [max(ids)] for namespace, ids in before.items()
        }
        pruned = await graph.aget_state(cast("Any", config_for(thread_id)))
        assert pruned.values == settled
        assert await stored_history(saver, control_id) == control_before

        for target in (thread_id, control_id):
            await graph.ainvoke(
                cast("Any", {"log": ["three"]}), cast("Any", config_for(target))
            )
        resumed = await graph.aget_state(cast("Any", config_for(thread_id)))
        control = await graph.aget_state(cast("Any", config_for(control_id)))
        assert resumed.values == control.values
        assert len(resumed.values["log"]) > len(settled["log"])
    finally:
        await saver.adelete_thread(thread_id)
        await saver.adelete_thread(control_id)


async def _prove_a_failed_thread_keeps_its_error_writes(saver: Checkpointer) -> None:
    graph = _failing_graph(saver)
    thread_id = f"failed-{uuid4()}"
    try:
        with pytest.raises(RuntimeError, match="the step failed"):
            await graph.ainvoke(
                cast("Any", {"log": ["go"]}), cast("Any", config_for(thread_id))
            )
        latest = await saver.aget_tuple(cast("Any", config_for(thread_id)))
        assert latest is not None
        assert latest.pending_writes
        channels = {write[1] for write in latest.pending_writes}
        # The failure and the sibling's finished work are both pending on the
        # latest checkpoint: recovery reads the one, a retry reuses the other.
        assert {"__error__", "log"} <= channels
        assert len((await stored_history(saver, thread_id))[""]) > 1

        assert await prune_settled_thread(saver, thread_id) is True

        kept = await saver.aget_tuple(cast("Any", config_for(thread_id)))
        assert kept is not None
        assert kept.checkpoint["id"] == latest.checkpoint["id"]
        assert sorted(kept.pending_writes or []) == sorted(latest.pending_writes)
        assert await stored_history(saver, thread_id) == {"": [latest.checkpoint["id"]]}
    finally:
        await saver.adelete_thread(thread_id)


@pytest_asyncio.fixture
async def sqlite_saver(tmp_path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as saver:
        await saver.setup()
        yield saver


@pytest.mark.asyncio
async def test_sqlite_keeps_only_the_latest_checkpoint_of_a_settled_thread(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    await _prove_a_settled_thread_keeps_only_its_latest(sqlite_saver)


@pytest.mark.asyncio
async def test_sqlite_keeps_the_error_writes_of_a_failed_thread(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    await _prove_a_failed_thread_keeps_its_error_writes(sqlite_saver)


async def _write_count(saver: AsyncSqliteSaver, thread_id: str) -> int:
    async with saver.conn.execute(
        "SELECT COUNT(*) FROM writes WHERE thread_id = ?", (thread_id,)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_a_failed_sqlite_prune_leaves_nothing_for_the_next_write_to_commit(
    sqlite_saver: AsyncSqliteSaver,
) -> None:
    """A prune that fails part-way takes back what it had already deleted.

    The saver shares one connection, so deletes a failed prune left open would
    be committed by whatever the saver wrote next. A real trigger refuses the
    second statement after the first has run.
    """
    graph = _settling_graph(sqlite_saver)
    thread_id, other_id = f"refused-{uuid4()}", f"other-{uuid4()}"
    await graph.ainvoke(
        cast("Any", {"log": ["one"]}), cast("Any", config_for(thread_id))
    )
    writes = await _write_count(sqlite_saver, thread_id)
    history = await stored_history(sqlite_saver, thread_id)
    await sqlite_saver.conn.execute(
        "CREATE TRIGGER refuse_prune BEFORE DELETE ON checkpoints "
        "BEGIN SELECT RAISE(ABORT, 'prune refused'); END"
    )
    await sqlite_saver.conn.commit()

    with pytest.raises(sqlite3.DatabaseError, match="prune refused"):
        await prune_settled_thread(sqlite_saver, thread_id)

    await sqlite_saver.conn.execute("DROP TRIGGER refuse_prune")
    await graph.ainvoke(
        cast("Any", {"log": ["one"]}), cast("Any", config_for(other_id))
    )

    assert await _write_count(sqlite_saver, thread_id) == writes
    assert await stored_history(sqlite_saver, thread_id) == history


@pytest.mark.asyncio
async def test_an_unrecognised_saver_is_left_untouched() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    graph = _settling_graph(saver)
    await graph.ainvoke(
        cast("Any", {"log": ["one"]}), cast("Any", config_for("memory"))
    )
    before = await stored_history(saver, "memory")

    assert await prune_settled_thread(saver, "memory") is False
    assert await stored_history(saver, "memory") == before


@pytest_asyncio.fixture(params=["connection", "pool", "selector-thread"])
async def postgres_saver(
    request: pytest.FixtureRequest, external_prerequisite: ExternalPrerequisiteRule
) -> AsyncIterator[Checkpointer]:
    external_prerequisite("postgres")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    url = os.environ[_POSTGRES_URL_ENV]
    if request.param == "connection":
        async with AsyncPostgresSaver.from_conn_string(url) as saver:
            await saver.setup()
            yield saver
    elif request.param == "pool":
        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            url,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        await pool.open()
        try:
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            yield saver
        finally:
            await pool.close()
    else:
        wrapped = _SelectorThreadPostgresCheckpointer(url)
        await wrapped.start()
        try:
            await wrapped.setup()
            yield wrapped
        finally:
            await wrapped.close()


async def _blob_count(thread_id: str) -> int:
    import psycopg

    async with await psycopg.AsyncConnection.connect(
        os.environ[_POSTGRES_URL_ENV]
    ) as connection:
        cursor = await connection.execute(
            "SELECT count(*) FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,)
        )
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_postgres_keeps_only_the_latest_checkpoint_of_a_settled_thread(
    postgres_saver: Checkpointer,
) -> None:
    await _prove_a_settled_thread_keeps_only_its_latest(postgres_saver)


@pytest.mark.asyncio
async def test_postgres_keeps_the_error_writes_of_a_failed_thread(
    postgres_saver: Checkpointer,
) -> None:
    await _prove_a_failed_thread_keeps_its_error_writes(postgres_saver)


@pytest.mark.asyncio
async def test_postgres_drops_the_blobs_only_superseded_checkpoints_named(
    postgres_saver: Checkpointer,
) -> None:
    graph = _settling_graph(postgres_saver)
    thread_id = f"blobs-{uuid4()}"
    try:
        for turn in ("one", "two", "three"):
            await graph.ainvoke(
                cast("Any", {"log": [turn]}), cast("Any", config_for(thread_id))
            )
        settled = (await graph.aget_state(cast("Any", config_for(thread_id)))).values
        blobs_before = await _blob_count(thread_id)

        assert await prune_settled_thread(postgres_saver, thread_id) is True

        assert 0 < await _blob_count(thread_id) < blobs_before
        assert (
            await graph.aget_state(cast("Any", config_for(thread_id)))
        ).values == settled
    finally:
        await postgres_saver.adelete_thread(thread_id)
