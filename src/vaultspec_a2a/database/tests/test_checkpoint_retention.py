"""A settled thread keeps only its latest checkpoint.

Real graphs run to completion (and to failure) on a real SQLite file, and the
pruned thread must read back exactly as it did before, resume where it stood,
and leave every other thread alone.
"""

from __future__ import annotations

import operator
import sqlite3
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast
from uuid import uuid4

import pytest
from langgraph.graph import END, START

from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..checkpoint_retention import prune_settled_checkpoints
from ._checkpoint_history import config_for, stored_history

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..checkpoints import Checkpointer


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
    inner = new_state_graph(_Log)
    add_test_node(inner, "inner_step", _append("inner"))
    inner.add_edge(START, "inner_step")
    inner.add_edge("inner_step", END)

    outer = new_state_graph(_Log)
    add_test_node(outer, "first", _append("first"))
    add_test_node(outer, "nested", compile_test_graph(inner))
    add_test_node(outer, "last", _append("last"))
    outer.add_edge(START, "first")
    outer.add_edge("first", "nested")
    outer.add_edge("nested", "last")
    outer.add_edge("last", END)
    return compile_test_graph(outer, checkpointer=saver)


def _failing_graph(saver: Checkpointer) -> Any:
    builder = new_state_graph(_Log)
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

        assert await prune_settled_checkpoints(saver, thread_id) is True

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

        assert await prune_settled_checkpoints(saver, thread_id) is True

        kept = await saver.aget_tuple(cast("Any", config_for(thread_id)))
        assert kept is not None
        assert kept.checkpoint["id"] == latest.checkpoint["id"]
        assert sorted(kept.pending_writes or []) == sorted(latest.pending_writes)
        assert await stored_history(saver, thread_id) == {"": [latest.checkpoint["id"]]}
    finally:
        await saver.adelete_thread(thread_id)


@pytest.mark.asyncio
async def test_sqlite_keeps_only_the_latest_checkpoint_of_a_settled_thread(
    checkpointer: AsyncSqliteSaver,
) -> None:
    await _prove_a_settled_thread_keeps_only_its_latest(checkpointer)


@pytest.mark.asyncio
async def test_sqlite_keeps_the_error_writes_of_a_failed_thread(
    checkpointer: AsyncSqliteSaver,
) -> None:
    await _prove_a_failed_thread_keeps_its_error_writes(checkpointer)


async def _write_count(saver: AsyncSqliteSaver, thread_id: str) -> int:
    async with saver.conn.execute(
        "SELECT COUNT(*) FROM writes WHERE thread_id = ?", (thread_id,)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_a_failed_sqlite_prune_leaves_nothing_for_the_next_write_to_commit(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A prune that fails part-way takes back what it had already deleted.

    The saver shares one connection, so deletes a failed prune left open would
    be committed by whatever the saver wrote next. A real trigger refuses the
    second statement after the first has run.
    """
    graph = _settling_graph(checkpointer)
    thread_id, other_id = f"refused-{uuid4()}", f"other-{uuid4()}"
    await graph.ainvoke(
        cast("Any", {"log": ["one"]}), cast("Any", config_for(thread_id))
    )
    writes = await _write_count(checkpointer, thread_id)
    history = await stored_history(checkpointer, thread_id)
    await checkpointer.conn.execute(
        "CREATE TRIGGER refuse_prune BEFORE DELETE ON checkpoints "
        "BEGIN SELECT RAISE(ABORT, 'prune refused'); END"
    )
    await checkpointer.conn.commit()

    with pytest.raises(sqlite3.DatabaseError, match="prune refused"):
        await prune_settled_checkpoints(checkpointer, thread_id)

    await checkpointer.conn.execute("DROP TRIGGER refuse_prune")
    await graph.ainvoke(
        cast("Any", {"log": ["one"]}), cast("Any", config_for(other_id))
    )

    assert await _write_count(checkpointer, thread_id) == writes
    assert await stored_history(checkpointer, thread_id) == history


@pytest.mark.asyncio
async def test_an_unrecognised_saver_is_left_untouched() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    graph = _settling_graph(saver)
    await graph.ainvoke(
        cast("Any", {"log": ["one"]}), cast("Any", config_for("memory"))
    )
    before = await stored_history(saver, "memory")

    assert await prune_settled_checkpoints(saver, "memory") is False
    assert await stored_history(saver, "memory") == before
