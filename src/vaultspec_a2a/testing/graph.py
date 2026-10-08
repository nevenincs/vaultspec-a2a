"""Test-side entry points to the compiler's typed ``StateGraph`` boundary.

Every test that builds a ``StateGraph`` routes through these helpers instead of
the library methods directly. They delegate to the graph compiler's own typed
builder, node, and compile helpers, so the irreducible langgraph typing
diagnostic (its ``add_node``/``compile`` overloads default several parameters
to a bare, unparametrized generic in their own shipped source) is paid in one
place for production and tests alike, rather than at every call site across the
test tree. The stand-in definition digest an injected graph's cache key binds to
sits beside them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..graph.compiler import add_graph_node, compile_graph_builder, new_graph_builder
from ..thread import sha256_hex
from ..thread.state import TeamState

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph import StateGraph
    from langgraph.store.base import BaseStore
    from langgraph.types import Command, RetryPolicy, TimeoutPolicy

__all__ = [
    "add_test_node",
    "ainvoke_test_graph",
    "compile_test_graph",
    "new_state_graph",
    "stand_in_definition_digest",
]


def new_state_graph(
    state_schema: type[Any] = TeamState,
    *,
    context_schema: type[Any] | None = None,
) -> StateGraph[Any, Any, Any, Any]:
    """Return a builder over ``state_schema`` (``TeamState`` unless given)."""
    return new_graph_builder(state_schema, context_schema=context_schema)


def add_test_node(
    builder: StateGraph[Any, Any, Any, Any],
    name: str,
    node: Callable[..., Any],
    *,
    metadata: dict[str, str] | None = None,
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = None,
    timeout: TimeoutPolicy | None = None,
) -> None:
    """Add a node to ``builder`` through the compiler's typed boundary."""
    add_graph_node(
        builder,
        name,
        node,
        metadata=metadata,
        retry_policy=retry_policy,
        timeout=timeout,
    )


def compile_test_graph(
    builder: StateGraph[Any, Any, Any, Any],
    *,
    checkpointer: BaseCheckpointSaver[str] | bool | None = None,
    interrupt_before: list[str] | None = None,
    store: BaseStore | None = None,
    name: str | None = None,
) -> Any:
    """Compile ``builder`` through the compiler's typed boundary.

    The result is untyped: a test graph's surface (``astream``, ``aget_state``,
    ``aupdate_state``) is wider than the compiler's team-graph protocol.
    """
    return compile_graph_builder(
        builder,
        checkpointer=checkpointer,
        interrupt_before=interrupt_before,
        store=store,
        name=name,
    )


async def ainvoke_test_graph(
    graph: Any,
    state: dict[str, Any] | Command[str],
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Invoke a compiled test graph behind one fully-typed call boundary."""
    result = await graph.ainvoke(state, config)
    return cast("dict[str, Any]", result)


def stand_in_definition_digest(team_preset: str) -> str:
    """Return a deterministic stand-in for a frozen graph definition's digest.

    Injected graphs bypass compilation, so no ``ExecutableGraphDefinition`` is
    ever frozen for them; the cache key still requires a digest-shaped value
    that binds the injected entry to the preset it stands in for.
    """
    return sha256_hex(team_preset.encode())
