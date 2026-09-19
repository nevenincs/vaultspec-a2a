"""Fully-typed call boundary around langgraph's `StateGraph` for tests.

langgraph's own `add_node`/`compile`/`ainvoke` overloads default several
parameters (`cache_policy`, `checkpointer`) to bare `CachePolicy[Unknown]` /
`BaseCheckpointSaver[Unknown]` shapes in their shipped source, so the member
access itself is permanently partially-typed regardless of the arguments
passed at a given call site - even a fully-typed local, as production's own
boundary (`vaultspec_a2a.graph.compiler._add_node`/`_compile_graph`)
demonstrates. The only way to stop the unknown-ness in the library's own
declared overload from propagating is to route the two calls through an
`Any`-typed alias of the builder at this single boundary; the parameter and
return types on `add_node`/`compile_graph` themselves stay concrete, so no
`Any` leaks into a caller's signature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from langgraph.graph import StateGraph

from ..state import TeamState

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.types import Command

__all__ = ["CompiledTestGraph", "add_node", "compile_graph", "new_builder"]


def new_builder() -> StateGraph[Any, None, Any, Any]:
    """Return a `TeamState`-shaped builder behind one typed call boundary."""
    return StateGraph(cast("Any", TeamState))


def add_node(
    builder: StateGraph[Any, None, Any, Any],
    name: str,
    node: Callable[..., Any],
) -> None:
    """Add `node` to `builder` behind one fully-typed call boundary."""
    untyped_builder = cast("Any", builder)
    untyped_builder.add_node(name, node)


class CompiledTestGraph(Protocol):
    """The subset of a compiled graph these tests actually invoke."""

    async def ainvoke(
        self,
        input: Mapping[str, Any] | Command[str] | None,
        config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def aget_state(self, config: Mapping[str, Any]) -> Any: ...


def compile_graph(
    builder: StateGraph[Any, None, Any, Any],
    *,
    checkpointer: BaseCheckpointSaver[str],
    interrupt_before: list[str] | None = None,
) -> CompiledTestGraph:
    """Compile `builder` behind one fully-typed call boundary."""
    untyped_builder = cast("Any", builder)
    return cast(
        "CompiledTestGraph",
        untyped_builder.compile(
            checkpointer=checkpointer, interrupt_before=interrupt_before
        ),
    )
