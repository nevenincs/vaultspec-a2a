"""A real graph whose run parks on a clarification and is then signalled.

Two branches of one superstep, sent in parallel: one parks on a real
clarification ``interrupt()``, and the other waits until the run's own
checkpoint shows that park before it acts. So the stream has already reported
the park when the second branch either finishes normally or raises
:class:`InjectedSignal` - the order a worker sees when a run parks on a
question and is then stopped by a signal from outside it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START
from langgraph.types import Send, interrupt

from ...graph.nodes._config_contract import accepting_runnable_config
from ...testing import add_test_node, compile_test_graph, new_state_graph
from ...thread.clarification import CLARIFICATION_INTERRUPT_TYPE
from ._error_injecting_graph import InjectedSignal

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

__all__ = ["ParkedSignalInput", "build_parked_then_signalled_graph"]

_PARK_BRANCH = "park"
_SIGNAL_BRANCH = "signal"
_PARK_WAIT_SECONDS = 10.0
_PARK_POLL_SECONDS = 0.01


class ParkedSignalInput(TypedDict, total=False):
    """What the run is asked to do once its question has parked."""

    request_id: str
    """The clarification request the parking branch raises."""

    raise_signal: bool
    """Raise :class:`InjectedSignal` after the park instead of finishing."""


def build_parked_then_signalled_graph() -> Any:
    """Compile a fresh parked-then-signalled graph over its own saver."""
    holder: dict[str, Any] = {}

    async def _park(state: ParkedSignalInput) -> dict[str, Any]:
        interrupt(
            {
                "type": CLARIFICATION_INTERRUPT_TYPE,
                "request_id": state.get("request_id", "parked-question"),
            }
        )
        return {}

    async def _signal(
        state: ParkedSignalInput, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        configurable = (config or {}).get("configurable") or {}
        thread = {"configurable": {"thread_id": configurable["thread_id"]}}
        deadline = asyncio.get_running_loop().time() + _PARK_WAIT_SECONDS
        while not await _parked(holder["graph"], thread):
            if asyncio.get_running_loop().time() > deadline:
                # Not a signal: a run that never parked is a broken fixture,
                # and it must fail the test rather than pass it vacuously.
                raise RuntimeError("the parking branch never parked")
            await asyncio.sleep(_PARK_POLL_SECONDS)
        if state.get("raise_signal"):
            raise InjectedSignal("stop")
        return {}

    builder = new_state_graph(ParkedSignalInput)
    add_test_node(builder, _PARK_BRANCH, _park)
    add_test_node(builder, _SIGNAL_BRANCH, accepting_runnable_config(_signal))
    builder.add_conditional_edges(START, _both_branches, [_PARK_BRANCH, _SIGNAL_BRANCH])
    holder["graph"] = compile_test_graph(builder, checkpointer=InMemorySaver())
    return holder["graph"]


def _both_branches(state: ParkedSignalInput) -> list[Send]:
    """Send the parking branch and the signalling branch in one superstep."""
    return [Send(_PARK_BRANCH, state), Send(_SIGNAL_BRANCH, state)]


async def _parked(graph: Any, thread: dict[str, Any]) -> bool:
    """Return whether the run's checkpoint already holds the parked question."""
    snapshot = await graph.aget_state(thread)
    return any(task.interrupts for task in snapshot.tasks)
