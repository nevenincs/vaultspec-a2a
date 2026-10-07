"""History depth comes from the checkpoint already read, not a second listing.

The depth was measured by listing the thread again with a limit of two. That
paid a round trip to rediscover what the saver had already handed back in the
tuple's ``parent_config``, and it counted stored ROWS rather than the
checkpoint's ancestry - so it disagreed with the parent id served beside it as
soon as retention had been through the store, and it counted a subgraph's rows
as the root namespace's history.

Driven against a real graph over a real SQLite store, including across a real
settled-history prune, because the disagreement only appears once retention has
removed the rows the old count depended on.
"""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Annotated, Any, TypedDict, cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START

from ...control.snapshot import checkpoint_history_depth
from ...database.checkpoint_retention import prune_settled_checkpoints
from ...testing import add_test_node, compile_test_graph, new_state_graph

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig


class _Log(TypedDict):
    log: Annotated[list[str], operator.add]


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _append(entry: str) -> Any:
    async def node(state: _Log) -> dict[str, list[str]]:
        del state
        return {"log": [entry]}

    return node


def _flat_graph(saver: Any) -> Any:
    builder = new_state_graph(_Log)
    add_test_node(builder, "step", _append("flat"))
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    return compile_test_graph(builder, checkpointer=saver)


def _nested_graph(saver: Any) -> Any:
    """A graph with a subgraph, so the thread spans several namespaces."""
    inner = new_state_graph(_Log)
    add_test_node(inner, "inner_step", _append("inner"))
    inner.add_edge(START, "inner_step")
    inner.add_edge("inner_step", END)

    outer = new_state_graph(_Log)
    add_test_node(outer, "nested", compile_test_graph(inner))
    outer.add_edge(START, "nested")
    outer.add_edge("nested", END)
    return compile_test_graph(outer, checkpointer=saver)


async def _rows(saver: Any, thread_id: str) -> int:
    count = 0
    async for _item in saver.alist(cast("Any", _config(thread_id))):
        count += 1
    return count


def _checkpoint_namespace(config: RunnableConfig) -> str:
    """The namespace a checkpoint's own config names."""
    return _configurable(config)["checkpoint_ns"]


def _configurable(config: RunnableConfig) -> Mapping[str, str]:
    """The config's ``configurable`` block, read as the mapping it is.

    ``configurable`` is not a required key of ``RunnableConfig``, so indexing
    it directly is a possible ``KeyError`` the checker refuses to wave
    through. Reading the config as a plain mapping keeps the same access and
    the same failure where a checkpoint really does arrive without one.
    """
    return cast("Mapping[str, Mapping[str, str]]", config)["configurable"]


def _recorded_parent(checkpoint_tuple: Any) -> str | None:
    parent = cast(
        "Mapping[str, Mapping[str, str]] | None", checkpoint_tuple.parent_config
    )
    return parent.get("configurable", {}).get("checkpoint_id") if parent else None


def test_no_checkpoint_has_no_depth_to_report() -> None:
    """Absent is not zero: the caller degrades the snapshot on an unknown depth."""
    assert checkpoint_history_depth(None) is None


@pytest.mark.asyncio
async def test_the_depth_needs_no_second_read_of_the_store(tmp_path: Path) -> None:
    """The store is gone and the depth is still there.

    The depth is computed from the checkpoint tuple, so there is no second
    listing to time out or fail: this closes the store before asking, which a
    second read could not survive.
    """
    thread_id = f"closed-{uuid4()}"
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.db")) as store:
        await store.setup()
        graph = _flat_graph(store)
        await graph.ainvoke(
            cast("Any", {"log": ["one"]}), cast("Any", _config(thread_id))
        )
        latest = await store.aget_tuple(cast("Any", _config(thread_id)))

    assert latest is not None
    assert checkpoint_history_depth(latest) == 2


@pytest.mark.asyncio
async def test_the_depth_agrees_with_the_parent_id_served_beside_it(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """A snapshot must not report a parent and no ancestry at once.

    Retention keeps a settled run's latest checkpoint and nothing older, so
    counting the rows left reported a depth of one - beside a parent id the
    same snapshot still carried. Both describe what the surviving checkpoint
    RECORDS, and they now say the same thing.
    """
    graph = _flat_graph(checkpointer)
    thread_id = f"pruned-flat-{uuid4()}"
    for turn in ("one", "two", "three"):
        await graph.ainvoke(
            cast("Any", {"log": [turn]}), cast("Any", _config(thread_id))
        )

    assert await prune_settled_checkpoints(checkpointer, thread_id) is True

    latest = await checkpointer.aget_tuple(cast("Any", _config(thread_id)))
    assert latest is not None
    parent_id = _recorded_parent(latest)
    assert parent_id is not None, "the surviving checkpoint still names a parent"
    # One row left, so a row count would have said one, contradicting that id.
    assert await _rows(checkpointer, thread_id) == 1
    assert checkpoint_history_depth(latest) == 2

    # And the named parent really is gone, which is what the served field warns
    # about: the reference outlives the checkpoint it points at.
    assert (
        await checkpointer.aget_tuple(
            cast(
                "Any",
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": parent_id,
                    }
                },
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_the_depth_describes_one_checkpoint_not_the_thread_s_rows(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Listing the thread counted every namespace's rows as root history.

    A thread with a subgraph keeps checkpoints under more than one namespace,
    and the old count did not distinguish them, so the number served for the
    root checkpoint included rows from a subgraph it has no ancestry relation
    to. The depth is now a fact about the checkpoint being described.
    """
    graph = _nested_graph(checkpointer)
    thread_id = f"namespaces-{uuid4()}"
    await graph.ainvoke(cast("Any", {"log": ["one"]}), cast("Any", _config(thread_id)))

    namespaces: set[str] = set()
    async for item in checkpointer.alist(cast("Any", _config(thread_id))):
        namespaces.add(_checkpoint_namespace(item.config))
    assert len(namespaces) > 1, "the thread must span namespaces for this to matter"

    latest = await checkpointer.aget_tuple(cast("Any", _config(thread_id)))
    assert latest is not None
    assert _checkpoint_namespace(latest.config) == ""

    depth = checkpoint_history_depth(latest)
    expected = 2 if _recorded_parent(latest) is not None else 1
    assert depth == expected
    # More rows in the store than the depth: it is not counting them.
    assert await _rows(checkpointer, thread_id) > 2


@pytest.mark.asyncio
async def test_the_first_checkpoint_of_a_thread_reports_no_ancestry(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Depth one means first, and only the checkpoint itself can say so."""
    graph = _flat_graph(checkpointer)
    thread_id = f"first-{uuid4()}"
    await graph.ainvoke(cast("Any", {"log": ["one"]}), cast("Any", _config(thread_id)))

    oldest = None
    async for item in checkpointer.alist(cast("Any", _config(thread_id))):
        if _checkpoint_namespace(item.config) == "":
            oldest = item
    assert oldest is not None
    assert _recorded_parent(oldest) is None

    assert checkpoint_history_depth(oldest) == 1
