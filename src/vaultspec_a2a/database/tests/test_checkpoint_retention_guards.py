"""Retention writes to another library's tables only when it still may.

Pruning is a stand-in: the saver this project ships offers no pruning of its
own, so the statements go straight at its tables. That is safe only while
three conditions hold, and recognising the saver's CLASS alone establishes
none of them.

Each test here breaks exactly one condition against a real store and requires
the store to come back untouched, because the failure mode is silent: the
deletes succeed and the damage shows up on the next read.
"""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast, override
from uuid import uuid4

import pytest
from langgraph.channels import DeltaChannel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START

from ...testing import add_test_node, compile_test_graph, new_state_graph
from ..checkpoint_retention import prune_settled_checkpoints
from ._checkpoint_history import config_for, stored_history

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..checkpoints import Checkpointer


class _Log(TypedDict):
    log: Annotated[list[str], operator.add]


def _accumulate(state: Any, writes: Sequence[Any]) -> list[str]:
    return [*(state or []), *(str(write) for write in writes)]


class _DeltaLog(TypedDict):
    # snapshot_frequency high enough that the surviving latest checkpoint is
    # not a snapshot point, which is exactly the case a prune would break.
    log: Annotated[list[str], DeltaChannel(_accumulate, list, snapshot_frequency=1000)]


class _SnapshottingDeltaLog(TypedDict):
    # snapshot_frequency of one: every checkpoint that writes the log is a
    # snapshot point, so the surviving latest checkpoint carries the whole value.
    log: Annotated[list[str], DeltaChannel(_accumulate, list, snapshot_frequency=1)]


def _one_step_graph(saver: Checkpointer, state_schema: type[Any]) -> Any:
    """One node appending a turn to *state_schema*'s log, compiled over *saver*.

    The two schemas differ only in the channel behind that log - one plain,
    one a delta channel whose value is rebuilt from the history a prune
    removes. Building both from one graph is what keeps the channel the only
    difference between the cases below.
    """

    async def step(state: Any) -> dict[str, list[str]]:
        del state
        return {"log": ["step"]}

    builder = new_state_graph(state_schema)
    add_test_node(builder, "step", step)
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return compile_test_graph(builder, checkpointer=saver)


@pytest.mark.asyncio
async def test_a_delta_channel_thread_is_left_alone(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Its value lives in the history, so deleting the history deletes the value.

    A delta channel stores a sentinel and rebuilds state by walking back to the
    nearest snapshot. Pruning to the latest checkpoint severs that walk, and
    nothing raises: the channel simply reconstructs as empty. The guard is the
    only thing standing between a settled delta thread and silent data loss.
    """
    graph = _one_step_graph(checkpointer, _DeltaLog)
    thread_id = f"delta-{uuid4()}"
    for turn in ("one", "two", "three"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", config_for(thread_id))
        )
    before = await stored_history(checkpointer, thread_id)
    settled = (await graph.aget_state(cast("Any", config_for(thread_id)))).values
    assert settled["log"], "the delta channel must hold a value to lose"
    assert all(len(ids) > 1 for ids in before.values())

    assert await prune_settled_checkpoints(checkpointer, thread_id) is False

    assert await stored_history(checkpointer, thread_id) == before
    assert (
        await graph.aget_state(cast("Any", config_for(thread_id)))
    ).values == settled


@pytest.mark.asyncio
async def test_a_delta_thread_whose_head_is_a_snapshot_is_pruned_without_loss(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A snapshot head needs no history, so refusing it only keeps dead rows.

    When every delta channel snapshotted in the latest checkpoint, that
    checkpoint holds each channel's whole value and LangGraph records no
    writes since a snapshot. Pruning it must succeed and leave the value
    exactly as it was - the check that refused this case guarded nothing and
    leaned on a type LangGraph does not publish.
    """
    graph = _one_step_graph(checkpointer, _SnapshottingDeltaLog)
    thread_id = f"delta-snapshot-{uuid4()}"
    for turn in ("one", "two", "three"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", config_for(thread_id))
        )
    before = await stored_history(checkpointer, thread_id)
    settled = (await graph.aget_state(cast("Any", config_for(thread_id)))).values
    assert settled["log"], "the delta channel must hold a value to lose"
    assert all(len(ids) > 1 for ids in before.values())

    assert await prune_settled_checkpoints(checkpointer, thread_id) is True

    assert await stored_history(checkpointer, thread_id) == {
        namespace: [max(ids)] for namespace, ids in before.items()
    }
    assert (
        await graph.aget_state(cast("Any", config_for(thread_id)))
    ).values == settled


@pytest.mark.asyncio
async def test_a_plain_thread_on_the_same_store_is_still_pruned(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """The delta guard is per thread, not a blanket refusal for the store."""
    graph = _one_step_graph(checkpointer, _Log)
    thread_id = f"plain-{uuid4()}"
    for turn in ("one", "two"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", config_for(thread_id))
        )
    before = await stored_history(checkpointer, thread_id)
    assert all(len(ids) > 1 for ids in before.values())

    assert await prune_settled_checkpoints(checkpointer, thread_id) is True

    assert await stored_history(checkpointer, thread_id) == {
        namespace: [max(ids)] for namespace, ids in before.items()
    }


@pytest.mark.asyncio
async def test_a_sqlite_store_with_another_table_layout_is_refused(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """SQLite keeps no migration ledger, so the tables are their own version.

    A column the saver did not have when these deletes were written is a
    layout they were not written for, and the class of the saver holding it
    says nothing about that.
    """
    graph = _one_step_graph(checkpointer, _Log)
    thread_id = f"layout-{uuid4()}"
    for turn in ("one", "two"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", config_for(thread_id))
        )
    before = await stored_history(checkpointer, thread_id)
    await checkpointer.conn.execute("ALTER TABLE writes ADD COLUMN retained INTEGER")
    await checkpointer.conn.commit()

    assert await prune_settled_checkpoints(checkpointer, thread_id) is False

    assert await stored_history(checkpointer, thread_id) == before


@pytest.mark.asyncio
async def test_a_saver_that_prunes_itself_is_asked_to(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A saver's own pruning is authoritative where these statements guess.

    The shipped saver does not implement it today, so this drives the branch
    with a real saver subclass that does - the shape a LangGraph release adding
    ``aprune`` would take.
    """
    calls: list[tuple[list[str], str]] = []

    class _PruningSaver(AsyncSqliteSaver):
        @override
        async def aprune(
            self, thread_ids: Any, *, strategy: str = "keep_latest"
        ) -> None:
            calls.append((list(thread_ids), strategy))

    saver = _PruningSaver(checkpointer.conn)
    saver.is_setup = True
    graph = _one_step_graph(saver, _Log)
    thread_id = f"self-pruning-{uuid4()}"
    for turn in ("one", "two"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", config_for(thread_id))
        )
    before = await stored_history(saver, thread_id)

    assert await prune_settled_checkpoints(saver, thread_id) is True

    # The saver was asked, and the direct statements did not also run.
    assert calls == [([thread_id], "keep_latest")]
    assert await stored_history(saver, thread_id) == before
    assert type(saver).aprune is not cast("object", BaseCheckpointSaver.aprune)
