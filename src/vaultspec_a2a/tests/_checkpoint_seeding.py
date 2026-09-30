"""Seed a real checkpoint for scenarios that must hand-craft its contents.

`langgraph.checkpoint.base.empty_checkpoint` is a deprecated stub that writes
checkpoint format v2, while every real run's checkpointer writes format v4.
A scenario that must hand-craft a checkpoint - a malformed or foreign-writer
one, or one pinned to a literal id an assertion checks - starts from
`real_checkpoint`, the actual structure a real, compiled graph run leaves
behind, then writes the altered copy back through its own saver's `aput`.

The run lands on a private, in-memory saver and a fixed top-level thread and
namespace, never the caller's own store or the thread and namespace the
caller's scenario addresses:

- A scan over every row in the caller's store (a whole-database backfill
  count, an `adelete_thread` sweep, a checkpoint-history listing) would
  otherwise see the seed run's own bookkeeping checkpoints alongside the ones
  the scenario actually means to test.
- A real graph only checkpoints a non-empty `checkpoint_ns` as a nested
  subgraph call already framed by a live parent run; invoked at the top
  level, as a scenario simulating a foreign namespace (e.g. a worker child
  checkpoint) needs to, LangGraph silently writes nothing.

Neither the checkpoint's own shape nor its content depends on which thread or
namespace produced it - `Checkpoint` carries no such field - so the private
run's choice of thread and namespace does not narrow what a caller can seed.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph

from ..graph.tests._state_graph_helpers import add_test_node, compile_test_graph
from ..thread.state import TeamState

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import Checkpoint

__all__ = ["real_checkpoint"]

_SCRATCH_CONFIG: RunnableConfig = {
    "configurable": {"thread_id": "real-checkpoint-seed", "checkpoint_ns": ""}
}


def _seed_node(_state: TeamState) -> dict[str, Any]:
    """Advance the graph one step without claiming any channel value."""
    return {}


async def real_checkpoint() -> Checkpoint:
    """Run one real graph against a private saver and return the checkpoint it wrote.

    The return value is a private copy, safe for the caller to overwrite with
    whatever fields the scenario needs before writing it back through its own
    saver and the `config` that scenario actually addresses.
    """
    builder: StateGraph[Any, None, Any, Any] = StateGraph(cast("Any", TeamState))
    add_test_node(builder, "seed", _seed_node)
    builder.add_edge("__start__", "seed")
    builder.add_edge("seed", "__end__")
    scratch_saver = InMemorySaver()
    graph = compile_test_graph(builder, checkpointer=scratch_saver)
    await graph.ainvoke({}, _SCRATCH_CONFIG)
    written = await scratch_saver.aget_tuple(_SCRATCH_CONFIG)
    assert written is not None
    return copy.deepcopy(written.checkpoint)
