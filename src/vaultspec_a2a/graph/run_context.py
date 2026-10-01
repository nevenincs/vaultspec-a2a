"""The typed per-invocation identity a compiled team graph runs under.

Passed as LangGraph's Runtime context on every ingest and resume rather than
read back out of checkpointed state, so a node always sees the identity of the
invocation executing it - including the dispatch that caused it, which state
alone cannot say once a run has been resumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from langgraph.runtime import Runtime

    from ..thread.state import TeamState

__all__ = ["RunContext", "run_thread_id"]


@dataclass(frozen=True, slots=True)
class RunContext:
    """Who is running this graph invocation, and on whose behalf.

    Attributes:
        thread_id: The run's thread, which is also its checkpoint thread.
        dispatch_id: The dispatch that started this ingest or resume.
        action: ``"ingest"`` or ``"resume"``.
    """

    thread_id: str
    dispatch_id: str
    action: str


def run_thread_id(state: TeamState, runtime: Runtime[Any] | None) -> str | None:
    """The invocation's thread id, falling back to state outside a served run.

    A node driven directly (a unit test, a tool invoked outside the graph)
    carries no Runtime context, and state is the only identity it has.
    """
    context = runtime.context if runtime is not None else None
    if isinstance(context, RunContext):
        return context.thread_id
    thread_id = cast("Mapping[str, object]", state).get("thread_id")
    return thread_id if isinstance(thread_id, str) and thread_id else None
